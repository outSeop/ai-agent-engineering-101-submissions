"""Read-only offer adapter for the genuine representative-card staging tool."""
import argparse
from contextlib import closing, redirect_stderr, redirect_stdout
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import sys
import time

from forum_official_mind_canary import NoWallet, verify_source
from class_variant_support import read_intent
from card_compact_view import compact_card_candidates


TOOL = "stage_representative_card"
PIN = {
    "permission.yml":"a607c48ed5f23a28a6402edcf1445ccc07e8af067888cae1d93803299659b20d",
    "logic.py":"e883b594583e1abf8587a963154d58020a0f0e214451dee1fa3c771d11514fbb",
    "test.py":"65f4378e3a301b871c1a54348d116800eb6aeaa74b86125f162b211a048b8b5e",
}
DEPENDENCIES = {
    "dispatcher.py":"84e0eca3a0211e80772ed78f2ba3c166902ba0125577e7153b06cc5bb13de0cd",
    "price_policy.py":"6e101702c38d47b3f2c68c860dc0198fd1d7557e311c2753dc4a71fed127118f",
    "worker_bootstrap.py":"083e127a2e08aa17949aaa808e61b859cee988389afc2073a6aa1b39de612514",
    "broker.py":"78e4f929e56b2083cd39e65e2f5ce0125e24f4fc20befb40632e284e01b9d27a",
    "refund_admin.py":"d1d5026ceef7f5f9b2e63a81c3c56f459cd708e1d0fd75c560171614520ce80d",
}
TOKEN_PATTERN = re.compile(r"0x[a-fA-F0-9]{40,}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
SKU = re.compile(r"[FG][A-Fa-f0-9]{8}")
CARD_STATES = {"ready","staged","already_staged","unchanged","rejected"}


def digest(raw):
    return sha256(raw).hexdigest()


def load_bundle(path):
    bundle = {name:(path/name).read_bytes() for name in (*PIN,"forge.json")}
    manifest = json.loads(bundle["forge.json"])
    if ((manifest.get("tool"),manifest.get("version"),manifest.get("sha256")) != (TOOL,1,PIN)
        or any(digest(bundle[k]) != value for k,value in PIN.items())):
        raise ValueError("unreviewed staging source")
    return bundle


def label(text):
    return isinstance(text,str) and 0 < len(text) <= 160 and text.strip()==text and text.isprintable() and not TOKEN_PATTERN.search(text)


def produce_view(card_raw, replace_text, offers, catalog, observed_at):
    card = json.loads(card_raw)
    if (card.get("name")!="outseop-r4" or not isinstance(card.get("skills"),list) or len(card["skills"])!=3
        or not isinstance(card.get("description"),str) or not replace_text.strip()
        or card["description"].count(replace_text)!=1):
        raise ValueError("reviewed card replacement span does not match")
    if not isinstance(catalog,list):
        raise ValueError("unexpected public catalog")
    products = {}
    ambiguous = set()
    for row in catalog:
        if not isinstance(row,dict):
            continue
        sku,name,category = row.get("sku"),row.get("name"),row.get("category")
        if not isinstance(sku,str) or not SKU.fullmatch(sku) or not label(name) or not isinstance(category,str):
            continue
        parts = [part.strip() for part in category.split(">")]
        if not all(label(part) for part in parts):
            continue
        value = (name,parts)
        if sku in products and products[sku] != value:
            ambiguous.add(sku)
        products[sku] = value
    projected = {}
    for row in offers:
        sku,grade,price,expiry = (row.get(k) for k in ("sku","grade","price","expiry"))
        if sku not in products or grade not in ("A","B","C") or type(price) is not int or price<1:
            continue
        if expiry is not None and (type(expiry) not in (int,float) or not math.isfinite(expiry) or expiry<=observed_at):
            continue
        name,parts = products[sku]
        entry = {"sku":sku,"name":name,"category_path":parts,"state":"available","grade":grade,
                 "price_credits":price,"standard_fee_credits":None,"valid_until":observed_at+150,
                 "expires_at":int(expiry) if expiry is not None else None}
        if sku in projected and projected[sku]!=entry:
            ambiguous.add(sku)
        projected[sku]=entry
    rows = [row for sku,row in projected.items() if sku not in ambiguous]
    return {"schema":"outseop-r4.card-offers.v1","shop":"outseop-r4","observed_at":observed_at,
            "valid_until":observed_at+150,"card_sha256":digest(card_raw),"replace_text":replace_text,
            "offers":rows,"market":None}


class CardGate:
    tools = {TOOL:{}}

    def __init__(self, execute, view, view_sha):
        self.execute=execute
        self.view=view
        self.view_sha=view_sha
        self.ready=False
        self.used=False
        self.result={"status":"not_staged"}

    def listing(self):
        return "- stage_representative_card: use {op: compare}, then {op: stage, skus: [exact listed SKUs]} once; private preview only."

    def forge(self,args):
        return {"status":"disabled"}

    def read(self,name):
        return {"status":"disabled"}

    def call(self,name,args):
        if name!=TOOL or not isinstance(args,dict):
            return {"status":"invalid_arguments"}
        if args=={"op":"compare"}:
            result=self.raw(args)
            self.ready=result.get("status")=="ready" and result.get("view_sha256")==self.view_sha
            if not self.ready:
                return {"status":"comparison_unavailable"}
            allowed = {row["sku"]:row for row in self.view["offers"]}
            shown = result.get("candidates",[])
            self.ready = isinstance(shown,list) and all(isinstance(row,dict) and row.get("sku") in allowed for row in shown)
            self.eligible = {row["sku"] for row in shown} if self.ready else set()
            if not self.ready:
                return {"status":"comparison_unavailable"}
            displayed=compact_card_candidates([allowed[row["sku"]] for row in shown])
            self.ready=displayed["status"]=="ready"
            return displayed
        if (set(args)!={"op","skus"} or args["op"]!="stage" or not self.ready or self.used
            or not isinstance(args["skus"],list) or not 1<=len(args["skus"])<=6
            or not all(isinstance(s,str) and s in self.eligible for s in args["skus"])
            or len(set(args["skus"]))!=len(args["skus"])):
            return {"status":"invalid_selection"}
        self.used=True
        result=self.raw(dict(args,view_sha256=self.view_sha))
        status=result.get("status")
        self.result={"status":status if status in CARD_STATES else "staging_unavailable"}
        record=result.get("record_id")
        if isinstance(record,str) and re.fullmatch(r"[a-f0-9]{64}",record):
            self.result["record_id"]=record
        return dict(self.result)

    def raw(self,args):
        envelope=self.execute(args)
        if (not isinstance(envelope,dict) or set(envelope)!={"ok","result"} or envelope["ok"] is not True
            or not isinstance(envelope["result"],dict)):
            return {}
        return envelope["result"]


def acquire(prod, *, stock_state=None):
    legacy = verify_source(prod)
    for name,pin in DEPENDENCIES.items():
        if digest((prod/"codex-r4"/name).read_bytes())!=pin:
            raise ValueError("offer validation dependency changed")
    sys.path.insert(0,str(prod/"codex-r4"))
    import worker_bootstrap
    registered = worker_bootstrap.validated_kit(prod)
    scope={}
    source=(legacy/"logic.py").read_bytes()
    exec(compile(source,str(legacy/"logic.py"),"exec"),scope)
    market=scope["Market"](registered)
    from public_reservation_sidecar import public_stock_state
    inventory = []
    if stock_state is not None:
        inventory = market.inventory()
        market.inventory = lambda: inventory
        chain = market.chain()
        market.chain = lambda: chain
    ledger=prod/"state/r4-benefits/benefits.sqlite3"
    with closing(sqlite3.connect(ledger.resolve().as_uri()+"?mode=ro",uri=True,timeout=3)) as db:
        db.row_factory=sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        identity=db.execute("SELECT shop,wallet FROM identity WHERE singleton=1").fetchone()
        if identity is None or tuple(identity)!=(registered.name,registered.address("shop")):
            raise ValueError("local offer ledger identity differs")
        observed_at=int(time.time())
        offers=scope["stock_offers"](db,market,observed_at)
        if stock_state is not None:
            core=scope["shop"]
            _, bps, network, _ = chain
            policy_path=prod/"codex-r4/launch-price-policy.json"
            if core.price_policy.POLICY_PATH!=policy_path:
                raise ValueError("stock state requires canonical absolute launch pricing")
            launch=bool(core.price_policy.current(observed_at))
            usable=core.usable_units(inventory,observed_at)
            def preferred(unit):
                terms=core.price_terms(unit,bps,network)
                return core.preferred_sale_price(unit,terms,bps,network,launch=launch) if terms else None
            stock_state.extend(public_stock_state(db,usable,observed_at,preferred_price=preferred))
    catalog=market.get("/api/catalog")
    if not worker_bootstrap.active():
        raise ValueError("shop stopped during observation")
    return registered, observed_at, offers, catalog


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operator",type=Path,required=True)
    parser.add_argument("--session",type=Path,required=True)
    parser.add_argument("--replace-text-file",type=Path,required=True)
    parser.add_argument("--prepare-only",action="store_true")
    parser.add_argument("--intent",type=Path)
    args=parser.parse_args()
    try:
        intent=read_intent(args.intent) if args.intent else {}
    except (OSError, ValueError, TypeError) as error:
        parser.error(str(error))
    op=args.operator.resolve(strict=True)
    session=args.session.resolve()
    runtime=(op/"runtime").resolve(strict=True)
    if session.parent!=runtime or not session.name.startswith("card-offer-mind-") or session.exists():
        parser.error("expected fresh card staging session")
    prod=op.parent/"round-4"
    bundle=load_bundle(runtime/"class-rebuild-reach-20261125"/"tools"/TOOL)
    os.umask(0o077)
    session.mkdir(mode=0o700)
    for name in ("logs","host_inputs","card_update_stage","tools"):
        (session/name).mkdir(mode=0o700)
    sys.path.insert(0,str(op/"kit"))
    import agent_kit as official
    official.mk.LOG_FILE=session/"logs"/"agent-kit.log"
    with (session/"logs"/"console-private.log").open("x") as log, redirect_stdout(log), redirect_stderr(log):
        raw=(prod/"card.json").read_bytes()
        registered, observed, offers, catalog=acquire(prod)
        view=produce_view(raw,args.replace_text_file.read_text(),offers,catalog,observed)
        if not view["offers"] or (prod/"card.json").read_bytes()!=raw:
            raise ValueError("no stable card offer view")
        encoded=json.dumps(view,ensure_ascii=False,separators=(",",":"),allow_nan=False).encode()
        for path,data in ((session/"card.json",raw),(session/"host_inputs/card_offer_context.json",encoded)):
            path.write_bytes(data)
            path.chmod(0o400)
        target=session/"tools"/TOOL
        target.mkdir()
        for name,data in bundle.items():
            (target/name).write_bytes(data)
        result={"status":"prepared","offer_count":len(view["offers"])}
        if not args.prepare_only:
            for key in ("AGENT_LLM_BASE","AGENT_LLM_MODEL","AGENT_LLM_KEY"):
                os.environ.pop(key,None)
            ctx={"name":"outseop-r4","market":registered.market,"tokens":{},"addresses":{},"signer":NoWallet()}
            toolbox=official.Toolbox(session,ctx)

            def invoke(request):
                load_bundle(target)
                return toolbox.run(TOOL,"call",request)

            gate=CardGate(invoke,view,digest(encoded))
            agent={"llm":{"base":"market"},"max_steps":5,"run_minutes":3,
                   "persona":"공개 재고를 정직하게 소개하는 운영 모델",
                   "goal":"공개 제안에서 대표 상품과 순서를 고른다. 여러 카테고리와 현재 등급을 고려하고 비교 후 격리 변경안만 저장한다. 이후 sleep."}
            agent.update(intent)
            model=official.Model(agent,registered.market,{"tokens":{"shop":registered.token("shop")}})
            official.Mind(session,agent,model,gate,ctx,[]).run_once([])
            result=gate.result
    result={**result,"applied_live":False,"offer_source":"pinned legacy externally authored stock_offers"}
    (session/"summary.json").write_text(json.dumps(result)+"\n")
    print(json.dumps(result))


if __name__=="__main__":
    main()

