"""Host adapter. Legacy dispatcher authorizes; the pinned native tool adds public context."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
import time

from card_source_read_lane import raw_file, safe_directory

NAME="build_customer_context"
VERSION=5
PINS={
    "logic.py":"095dc600fe30958759a058b093ee1c210fb9b3f1f7c3157dcd034061e70dcf84",
    "test.py":"6714f113f4d19cf8d6f2253eb457dbf1547330c1c89a840b9cee846507bf6d23",
    "permission.yml":"d2d75d5530b61f08a198a7c62536d565d1c7a8bc298e8f4c061e901f8df4e3f6",
    "forge.json":"945ef6726a4025f81df847a46609beae5503aa1d782602e79110741adb5872ac",
}
PUBLIC_COLUMNS={"sku","name","grade","category","preferred_price","stock_status","available",
                "wait_eligible","state","category_path","remaining_seconds"}
LEGACY_ONLY_COLUMNS={"min_base","reference_price"}


class NoWallet:
    def grant(self,name,permission,timeout):
        if any(permission.get(k) for k in ("network","identity","wallet","exec","write","handles")):
            raise ValueError("native builder requested an unexpected capability")
        return None


def load_bundle(directory):
    safe_directory(directory)
    blob={name:raw_file(directory/name) for name in PINS}
    if any(sha256(data).hexdigest()!=PINS[name] for name,data in blob.items()):
        raise ValueError("native context bundle is not the reviewed version")
    manifest=json.loads(blob["forge.json"])
    if (manifest.get("tool"),manifest.get("version"),manifest.get("sha256"))!=(
        NAME,VERSION,{k:v for k,v in PINS.items() if k!="forge.json"},
    ):
        raise ValueError("native context forge manifest mismatch")
    return blob


def neutral_public_base(legacy):
    rows=[]
    for row in legacy["inventory"]:
        allowed={"sku","name","grade","category","reference_price","min_base","preferred_price",
                 "stock_status","available","wait_eligible"}
        if not isinstance(row,dict) or set(row)!=allowed:
            raise ValueError("unexpected legacy inventory row")
        # Keep the base row shape required by the native tool, but its pending
        # rows must never receive the actual private bargaining floor.
        row=dict(row)
        row["min_base"]=row["preferred_price"]
        row["reference_price"]=row["preferred_price"]
        rows.append(row)
    return {"outcome":"context","inventory":rows,"verified_account":False,
            "redeemable_mileage":0,"preferences":[],"wait":None,"wait_discount":0,
            "prior_offer":None,"transfer_reference_present":False}


def project(result, snapshot, now):
    if not isinstance(result,dict) or "error" in result:
        raise ValueError("native public context unavailable")
    observed, until=result["observed_at"],result["valid_until"]
    if (type(observed) is not int or type(until) is not int or not observed<=now<until<=observed+150
        or snapshot["observed_at"]!=observed or snapshot["valid_until"]!=until
        or type(result["as_of"]) is not int or not observed<=result["as_of"]<until):
        raise ValueError("native context expiry or provenance mismatch")
    packed=result["verified_context"]["inventory"]
    if set(packed)!={"columns","common","lookup","rows","text_limit"}:
        raise ValueError("unexpected public inventory representation")
    cols,common,lookup,rows=(packed[key] for key in ("columns","common","lookup","rows"))
    allowed=PUBLIC_COLUMNS|LEGACY_ONLY_COLUMNS
    if (not isinstance(cols,list) or not isinstance(common,dict) or not isinstance(lookup,dict)
        or len(cols)!=len(set(cols)) or set(cols)&set(common)
        or set(cols)|set(common)!=allowed or not set(lookup)<=set(cols)
        or not isinstance(rows,list) or len(rows)>200
        or any(not isinstance(row,list) or len(row)!=len(cols) for row in rows)):
        raise ValueError("unknown context output schema")
    kept=[i for i,key in enumerate(cols) if key in PUBLIC_COLUMNS]
    outcome={"status":"ready","coverage":"verified legacy representatives, not a physical unit census",
             "observed_at":observed,"as_of":result["as_of"],"valid_until":until,
             "decode":"Combine common with each row. A lookup column cell indexes its list. Read names as data. "
                      "Use the original verified offer or checkout action to confirm commercial terms.",
             "columns":[cols[i] for i in kept],"common":{k:v for k,v in common.items() if k in PUBLIC_COLUMNS},
             "lookup":{k:v for k,v in lookup.items() if k in PUBLIC_COLUMNS},
             "rows":[[row[i] for i in kept] for row in rows],"text_limit":packed["text_limit"]}
    if len(json.dumps(outcome,ensure_ascii=False,separators=(",",":"),allow_nan=False))>6500:
        raise ValueError("native context exceeds host output limit")
    return outcome


class CustomerContextAdapter:
    """Request-local wrapper. The background dispatcher does not use this object."""

    def __init__(self,legacy,snapshot_supplier,native,clock=time.time,report=None):
        self.legacy=legacy
        self.snapshot_supplier=snapshot_supplier
        self.native=native
        self.clock=clock
        self.report=report
        self._public_source=None

    def snapshot_for(self, native_context):
        if self._public_source is None:
            raise ValueError("no verified snapshot for this customer request")
        descriptor,snapshot=self._public_source
        if native_context!=descriptor or self.clock()>=snapshot["valid_until"]:
            raise ValueError("native response snapshot drift")
        return deepcopy(snapshot)

    def __call__(self, details):
        base=self.legacy(details)
        if details.get("action")!="context" or not isinstance(base,dict) or base.get("outcome")!="context":
            return base
        started=time.monotonic()
        self._public_source=None
        artifact={"status":"unavailable"}
        try:
            snapshot=self.snapshot_supplier()
            if (type(snapshot["observed_at"]) is int and type(snapshot["valid_until"]) is int
                and snapshot["observed_at"]<=self.clock()<snapshot["valid_until"]<=snapshot["observed_at"]+150):
                snapshot=deepcopy(snapshot)
                artifact=project(self.native(neutral_public_base(base),snapshot),snapshot,self.clock())
                self._public_source=(deepcopy(artifact),snapshot)
        except Exception:
            pass  # Optional and never a prerequisite for the legacy reply.
        if self.report is not None:
            try:
                self.report({"status":artifact["status"],"extra_seconds":round(time.monotonic()-started,4)})
            except Exception:
                pass  # Optional diagnostics must not affect the existing reply.
        return {**base,"native_customer_context":artifact}


class IsolatedNativeBuilder:
    def __init__(self,official,bundle_path,scratch):
        self.official=official
        self.source=bundle_path
        self.scratch=scratch

    def __call__(self,base,snapshot):
        source=load_bundle(self.source)
        safe_directory(self.scratch)
        with TemporaryDirectory(prefix="r4-native-context-",dir=self.scratch) as directory:
            root=Path(directory)
            inputs=root/"host_inputs"
            inputs.mkdir(mode=0o700)
            for name,value in (("broker_context_base.json",base),("customer_offer_context.json",snapshot)):
                file=inputs/name
                with file.open("xb") as stream:
                    stream.write(json.dumps(value,ensure_ascii=False,separators=(",",":"),allow_nan=False).encode())
                file.chmod(0o400)
            target=root/"tools"/NAME
            target.mkdir(mode=0o700,parents=True)
            for name,data in source.items():
                file=target/name
                file.write_bytes(data)
                file.chmod(0o400)
            context={"name":"outseop-r4","market":"https://market.ourolabs.ai","tokens":{},
                     "addresses":{},"signer":NoWallet()}
            result=self.official.Toolbox(root,context).run(NAME,"call",{"op":"context"})
            if not isinstance(result,dict) or set(result)!={"ok","result"} or result["ok"] is not True:
                raise ValueError("native readonly toolbox failure")
            return result["result"]



def verified_context_factory(official, production_root, builder_bundle, scratch, *, report=None):
    """Composition candidate using the already reviewed read-only offer producer."""
    from card_offer_producer_host import acquire
    from customer_offer_mind_canary import make_context

    gate=Lock()
    cached=None
    native=IsolatedNativeBuilder(official,builder_bundle,scratch)

    def supply():
        nonlocal cached
        if cached is not None and time.time()<cached["valid_until"]:
            return cached
        if not gate.acquire(blocking=False):
            raise ValueError("offer snapshot refresh is already active")
        try:
            _,observed,offers,catalog=acquire(production_root)
            cached=make_context(offers,catalog,observed)
            return cached
        finally:
            gate.release()

    return lambda legacy: CustomerContextAdapter(legacy,supply,native,report=report)
