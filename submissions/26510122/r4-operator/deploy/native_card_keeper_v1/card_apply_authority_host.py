"""Host boundary for same-run card stage provenance; does not publish a card."""
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import time


def sha(raw):
    return sha256(raw).hexdigest()


def read_regular(path):
    fd = os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,"rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1:
            raise ValueError("unsafe stage file")
        return stream.read(24*1024*1024+1),info.st_mtime_ns


@dataclass(frozen=True)
class StageOrigin:
    record_id: str
    source_sha256: str
    view_sha256: str
    record_raw: bytes
    mtime_ns: int
    selected: tuple

    @classmethod
    def capture(cls, directory, response, view_raw, source_pin, call_start_ns, skus):
        """Call immediately after the pinned genuine stage tool returns."""
        record_id = response.get("record_id")
        if (response.get("status")!="staged" or not isinstance(record_id,str)
            or not re.fullmatch(r"[a-f0-9]{64}",record_id)
            or response.get("view_sha256")!=sha(view_raw)):
            raise ValueError("no newly generated stage in this invocation")
        data, stamped = read_regular(directory/(record_id+".json"))
        body = json.loads(data)
        if (sha(data)!=record_id or stamped<call_start_ns or len(data)>24*1024*1024
            or body.get("schema")!="outseop-r4.card-stage.v1" or body.get("shop")!="outseop-r4"
            or body.get("view_sha256")!=sha(view_raw) or body.get("skus")!=skus
            or not 1<=len(skus)<=3 or len(set(skus))!=len(skus)):
            raise ValueError("stage origin mismatch")
        return cls(record_id,source_pin,sha(view_raw),data,stamped,tuple(skus))


def normalized_fresh(origin, original_raw, fresh, before_raw, observed_ns):
    """Pin eligibility to original deadline only. Business facts must be identical."""
    old = json.loads(original_raw)
    staged = json.loads(origin.record_raw)
    if (origin.view_sha256!=sha(original_raw) or old["card_sha256"]!=sha(before_raw)
        or fresh["card_sha256"]!=old["card_sha256"] or staged["before_sha256"]!=sha(before_raw)
        or staged["before_card_json"].encode()!=before_raw or fresh["replace_text"]!=old["replace_text"]
        or fresh["schema"]!=old["schema"] or fresh["shop"]!=old["shop"]):
        raise ValueError("baseline or staged card binding changed")
    if (observed_ns<origin.mtime_ns or fresh["observed_at"]*10**9<origin.mtime_ns
        or fresh["observed_at"]<=old["observed_at"]):
        raise ValueError("fresh observation must follow genuine stage")
    fresh = {**fresh,"offers":[dict(row) for row in fresh["offers"]]}
    fresh["valid_until"] = min(old["valid_until"],fresh["valid_until"])
    if fresh["observed_at"]>=fresh["valid_until"]:
        raise ValueError("original observation expired")
    prior = {row["sku"]:row for row in old["offers"]}
    fresh_rows = {row["sku"]:row for row in fresh["offers"]}
    for sku in origin.selected:
        if sku not in prior or sku not in fresh_rows:
            raise ValueError("selected SKU unavailable")
        observed, first = fresh_rows[sku],prior[sku]
        observed["valid_until"]=min(observed["valid_until"],first["valid_until"])
        if observed!=first or fresh["observed_at"]>=observed["valid_until"]:
            raise ValueError("selected SKU changed")
    return fresh


def save_view(directory, raw):
    directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    path=directory/(sha(raw)+".json")
    with path.open("xb") as stream:
        stream.write(raw)
    path.chmod(0o400)
    return path

