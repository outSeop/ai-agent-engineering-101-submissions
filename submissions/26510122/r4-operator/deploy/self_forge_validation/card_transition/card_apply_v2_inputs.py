"""Binding checks for the genuine apply v2. No card writes or renderer."""
import json
from pathlib import Path
import re

from card_apply_authority_host import StageOrigin, sha

NATIVE = {
    "apply_staged_card_v2": {
        "location":"tools/apply_staged_card", "version":2,
        "logic_sha256":"4fecb5a59aba74173e10f88a3c79171daa8f729c6ac37b2f037aa7d4ced05c90",
        "permission_sha256":"546d5da9e2db2b565ca6420610b1686ca371da9ac4a21d7417e44cf54e0b7a52",
        "test_sha256":"306e81b3f42c1afe924cb61e16e58e0f91e4bf0affa9f62e44400199e9a426dc",
    },
    "apply_staged_card_v1_archive": {
        "location":"tools/.deprecated/apply_staged_card@1", "version":1,
        "logic_sha256":"14143d58859493f56b3b736dab10fe384211d8c0c8b58a1b3db59a50a9d5500f",
        "forge_sha256":"f11267a0efd3c9c995083c53515083f858ebdbe8daf222b0b3be3509c5b72e05",
        "permission_sha256":"a856de475325229ff7e7745d5912c53dbf7e931ed8d7fa1909b751291901b673",
        "test_sha256":"c96e43d06d9d30a2548d35e59a2628d0552b2a36978fba2b8d67d715d5041e55",
    },
    "stage_representative_card_v1": {
        "location":"tools/stage_representative_card", "version":1,
        "logic_sha256":"e883b594583e1abf8587a963154d58020a0f0e214451dee1fa3c771d11514fbb",
    },
}
POLICY_SKILLS = {"mileage":"repeat-benefits","wait":"repeat-benefits","refund":"refund-review"}


def make_authority(origin, old_view_raw, fresh_raw, before_raw, policies, head, now):
    """Shape an ephemeral authority from a captured same-run stage. Does not install it."""
    if not isinstance(origin,StageOrigin) or origin.source_sha256!=NATIVE["stage_representative_card_v1"]["logic_sha256"]:
        raise ValueError("unrecognized native stage provenance")
    if sha(origin.record_raw)!=origin.record_id or sha(old_view_raw)!=origin.view_sha256:
        raise ValueError("stage or view bytes changed")
    stage, old, fresh = (json.loads(data) for data in (origin.record_raw,old_view_raw,fresh_raw))
    before=json.loads(before_raw)
    staged=stage["after_card_json"].encode()
    after=json.loads(staged)
    if (stage["before_card_json"].encode()!=before_raw or sha(before_raw)!=stage["before_sha256"]
        or sha(staged)!=stage["after_sha256"] or old["card_sha256"]!=sha(before_raw)
        or fresh["card_sha256"]!=sha(before_raw) or stage["view_sha256"]!=origin.view_sha256
        or tuple(stage["skus"])!=origin.selected or sha(fresh_raw)==origin.view_sha256
        or not old["observed_at"]<fresh["observed_at"]<=now
        or origin.mtime_ns>fresh["observed_at"]*10**9
        or old["replace_text"]!=fresh["replace_text"]):
        raise ValueError("card/evidence binding differs")
    expires=min(stage["valid_until"],old["valid_until"],fresh["valid_until"],now+30)
    if type(now) is not int or now>=expires:
        raise ValueError("expired card stage")
    for sku in origin.selected:
        first=[row for row in old["offers"] if row["sku"]==sku]
        again=[row for row in fresh["offers"] if row["sku"]==sku]
        if len(first)!=1 or first!=again or first[0]["state"]!="available":
            raise ValueError("selected terms changed")
    if ({k:v for k,v in before.items() if k!="description"}
        !={k:v for k,v in after.items() if k!="description"}):
        raise ValueError("protected card metadata changed")
    if not isinstance(policies,dict) or set(policies)!=set(POLICY_SKILLS):
        raise ValueError("three reviewed policy clauses required")
    original=before["description"]
    region=old["replace_text"]
    if not region.strip() or original.count(region)!=1:
        raise ValueError("original replacement region conflict")
    kept=original.replace(region,"",1)
    tail="\n\n"+kept if kept else ""
    after_text=after["description"]
    if tail and not after_text.endswith(tail):
        raise ValueError("staged card does not preserve original surrounding text")
    block=after_text[:-len(tail)] if tail else after_text
    if not block.strip() or after_text.count(block)!=1:
        raise ValueError("ambiguous staged replacement")
    for key,clause in policies.items():
        if not isinstance(clause,str) or not clause.strip():
            raise ValueError("empty approved policy")
        skills=[s for s in before["skills"] if s.get("id")==POLICY_SKILLS[key]]
        if len(skills)!=1 or clause not in skills[0].get("description",""):
            raise ValueError("approved skill policy clause is missing")
        if kept.count(clause)!=original.count(clause):
            raise ValueError("replacement removes protected policy")
    if head is not None and (not isinstance(head,str) or not re.fullmatch(r"[a-f0-9]{64}",head)):
        raise ValueError("invalid committed publication head")
    return {"schema":"outseop-r4.card-publication-authority.v1","shop":"outseop-r4","owner":"native",
            "op":"apply","record_id":origin.record_id,"head":head,"before_sha256":sha(before_raw),
            "after_sha256":sha(staged),"issued_at":now,"valid_until":expires,
            "details":{"fresh_view_sha256":sha(fresh_raw),"replacement_sha256":sha(block.encode()),
                       "policies":dict(policies)}}

