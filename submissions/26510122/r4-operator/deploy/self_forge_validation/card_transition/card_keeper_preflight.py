"""Host-only policy-neutral continuation of a prior classroom SKU selection."""
from hashlib import sha256
import json


def digest(raw):
    return sha256(raw).hexdigest()


def retained_selection(event_id, event, old_view_raw, new_view, card_raw, *, now):
    """Validate the previous decision without repricing, ranking, or modifying a card."""
    if (event.get("schema")!="outseop-r4.card-publication-event.v1"
        or event.get("op")!="apply" or event.get("shop")!="outseop-r4"
        or event.get("after_sha256")!=digest(card_raw) or event.get("view_sha256")!=digest(old_view_raw)
        or now>=event["offer_until"] or now>=new_view["valid_until"]
        or new_view["card_sha256"]!=digest(card_raw)):
        raise ValueError("active event or observation is stale")
    old=json.loads(old_view_raw)
    card=json.loads(card_raw)
    block=event["block"]
    replacement=block["text"]
    if (not replacement or card["description"].count(replacement)!=1
        or card["description"][block["start"]:block["end"]]!=replacement
        or new_view["replace_text"]!=replacement):
        raise ValueError("active replacement block differs")
    skus=event["skus"]
    if (not isinstance(skus,list) or not 1<=len(skus)<=3
        or any(not isinstance(sku,str) for sku in skus) or len(set(skus))!=len(skus)):
        raise ValueError("active selection differs")
    old_rows={row["sku"]:row for row in old["offers"]}
    new_rows={row["sku"]:row for row in new_view["offers"]}
    for sku in skus:
        first,new=old_rows.get(sku),new_rows.get(sku)
        if (not first or not new or new["state"]!="available"
            or (new["expires_at"] is not None and new["expires_at"]<=now)
            or {k:v for k,v in new.items() if k!="valid_until"}!={k:v for k,v in first.items() if k!="valid_until"}):
            return {"status":"requires_class_selection"}
    return {"status":"retained","selection_origin":"derived_continue_prior_class_selection",
            "source_event":event_id,"skus":list(skus),"replace_text":replacement}

