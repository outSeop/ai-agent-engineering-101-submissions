"""Choose a stocked SKU and shop, negotiate, then hand a guarded receipt to kit v4."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import time

from buyer_memory import brief, context, import_broken, import_payments, read_events, record, register_shops
from context_compaction import BUYER_PROMPT_BYTES, size, text
from buyer_policy import acceptance, price_cap, receipt_problem
from buyer_r3 import negotiate
from harness import decide_json, trace


def review_summary(reviews: list[dict]) -> dict:
    stars = [r.get("stars") for r in reviews if isinstance(r, dict)
             and type(r.get("stars")) in (int, float) and 1 <= r["stars"] <= 5]
    examples=[{'stars':r.get('stars'),'review':text(r.get('review'),100),'round':r.get('round')}
              for r in reviews if isinstance(r,dict) and type(r.get('stars')) in (int,float) and 1<=r['stars']<=5]
    adverse=next((r for r in examples if r['stars']<=2),None)
    recent=examples[:1]
    if adverse and adverse not in recent:recent.append(adverse)
    return {"count": len(stars), "average": round(sum(stars) / len(stars), 2) if stars else None,
            "low_rating_count": sum(s <= 2 for s in stars),'examples':recent,
            'source':'public reviews; not first-hand verified outcomes'}


def candidates(order: dict, shops: list[dict], catalog: dict,
               own_shop_name: str) -> list[dict]:
    acceptable = set(order.get("acceptable") or [])
    history=read_events()
    found = []
    for shop in shops:
        if not isinstance(shop, dict) or shop.get("name") == own_shop_name or not shop.get("url"):
            continue
        for offer in shop.get("offers") or []:
            if not isinstance(offer, dict) or offer.get("sku") not in acceptable or offer.get("qty", 0) < 1:
                continue
            sku = offer["sku"]
            product = catalog.get(sku)
            cap = price_cap(order, product)
            if cap < 1:
                continue
            first_hand = context(shop["url"], sku, shop_name=shop.get('name'),
                                 product_name=product.get("name"),history=history)
            refusals = (first_hand["same_sku_payment_outcomes"].get("refused", 0)
                        + 2 * first_hand["observed_receipt_problems"])
            paid = first_hand["same_sku_payment_outcomes"].get("paid", 0)
            found.append({"shop": shop["name"], "url": shop["url"], "sku": sku,
                          "name": product.get("name") or offer.get("name") or sku,
                          "list_price": product["list_price"], "cap": cap,
                          "stock": offer["qty"], "reviews": review_summary(shop.get("reviews") or []),
                          "first_hand": first_hand, "paid": paid, "refusals": refusals})
    # Compact model input while preserving different shops and SKUs when possible.
    found.sort(key=lambda c: (c["paid"] - c["refusals"],
                              c["reviews"]["average"] or 3,
                              c["list_price"] - c["cap"]), reverse=True)
    selected = []
    per_shop = {}
    for choice in found:
        if per_shop.get(choice["url"], 0) >= 2:
            continue
        selected.append(choice)
        per_shop[choice["url"]] = per_shop.get(choice["url"], 0) + 1
        if len(selected) == 16:
            break
    for index, choice in enumerate(selected):
        choice["id"] = str(index)
    return selected


def choose(candidates_: list[dict], order: dict) -> tuple[dict, int]:
    displayed = [{**{key: row[key] for key in ("id", "list_price",
                                              "cap", "stock", "reviews")},
                  'shop':text(row['shop'],80),'sku':text(row['sku'],80),
                  'name':text(row['name'],100),'first_hand':brief(row['first_hand']),
                  "opening_offer_range": [max(1, math.floor(row["cap"] * 0.7)),
                                          max(1, math.floor(row["cap"] * 0.85))]}
                 for row in candidates_]
    prompt = {"phase": "buyer_selection", "order_item": text(order.get("item"),120),
              "kind": order.get("kind"), "use_within_hours": order.get("use_within_hours"),
              "candidate_shop_skus": displayed,
              "objective": "Choose one available SKU and shop, plus a first offer. Maximize likely "
                           "positive surplus and settlement chance. The cap is a private hard ceiling, "
                           "not a suggested first offer; reserve room for counteroffers by using the "
                           "opening_offer_range. Public reviews are unverified claims. A failed "
                           "negotiation alone is not proof of dishonesty. Tool candidate order is a "
                           "heuristic, not your decision. Read the first-hand counts, price conditions "
                           "and cases as evidence; do not turn a single past outcome into a permanent rule."}
    while size(prompt)>BUYER_PROMPT_BYTES and len(displayed)>1:
        displayed.pop()
    trace('buyer_context_compacted',candidate_count=len(displayed),prompt_bytes=size(prompt),
          memory_source='name-keyed facts and bounded cases')
    schema = {"type": "object", "properties": {
        "candidate_id": {"type": "string", "enum": [c["id"] for c in displayed]},
        "opening_offer": {"type": "integer"}, "reason": {"type": "string"},
    }, "required": ["candidate_id", "opening_offer", "reason"], "additionalProperties": False}
    try:
        answer = decide_json("buyer shop selector", prompt, schema)
        chosen = next(c for c in candidates_ if c["id"] == answer["candidate_id"])
        proposed = answer["opening_offer"]
        if type(proposed) is not int:
            raise ValueError("non-integer opening offer")
        opening = min(max(1, math.floor(chosen["cap"] * 0.85)),
                      max(max(1, math.floor(chosen["cap"] * 0.7)), proposed))
        trace("buyer_selection", candidate_id=chosen["id"], sku=chosen["sku"],
              shop=chosen["shop"], proposed=proposed, opening=opening, reason=answer["reason"])
        return chosen, opening
    except Exception as error:
        chosen = candidates_[0]
        opening = max(1, math.floor(chosen["cap"] * 0.8))
        trace("buyer_selection_fallback", error=type(error).__name__,
              candidate_id=chosen["id"], opening=opening)
        return chosen, opening


def run(order: dict, shops: list[dict], catalog: dict, own_shop_name: str) -> dict:
    started = time.monotonic()
    register_shops(shops)
    imported = import_payments()
    if imported:
        trace("buyer_payments_imported", count=imported)
    broken = import_broken()
    if broken:
        trace("buyer_breakage_imported", count=broken)
    available = candidates(order, shops, catalog, own_shop_name)
    if not available:
        record("no_candidate", order=order.get("order"), item=order.get("item"))
        return {"shop": "", "receipt": None, "stars": 3,
                "review": "No suitable stocked SKU was available."}
    chosen, first_offer = choose(available, order)
    fallback = next((c for c in available if c["url"] != chosen["url"]), None)
    attempts = [(chosen, first_offer)]
    if fallback:
        attempts.append((fallback, max(1, math.floor(fallback["cap"] * 0.9))))
    expires = order.get("expires")
    deadline = min(started + 235,
                   time.monotonic() + max(0, float(expires) - time.time() - 5)
                   if isinstance(expires, (int, float)) else float("inf"))
    last_shop = chosen["url"]
    for index, (choice, opening) in enumerate(attempts):
        if deadline - time.monotonic() < 75:
            break
        last_shop = choice["url"]
        try:
            def log_message(row):
                record('dialogue_message',order=order.get('order'),shop=choice['url'],
                       shop_name=choice['shop'],sku=choice['sku'],**row)
            outcome = negotiate(choice["url"], choice["sku"], choice["name"], order,
                                opening_offer=opening, cap=choice["cap"],
                                list_price=choice["list_price"], memory=choice["first_hand"],
                                deadline=deadline,on_message=log_message)
            final_offer = outcome["offers"][-1] if outcome["offers"] else 0
            problem = receipt_problem(outcome.get("receipt"), selected_sku=choice["sku"],
                                      order=order, final_offer=final_offer,
                                      task_id=outcome.get("task_id"), cap=choice["cap"])
            record("negotiation", order=order.get("order"), shop=choice["url"],shop_name=choice['shop'],
                   sku=choice["sku"], cap=choice["cap"], offers=outcome["offers"],
                   result=("receipt_pending" if problem is None else
                           "invalid_receipt" if outcome.get("receipt") else "no_receipt"),
                   reason=problem or outcome["reason"],task_id=outcome.get('task_id'),
                   transcript=outcome.get('transcript',[]))
            if problem is None:
                return {"shop": choice["url"], "receipt": outcome["receipt"],
                        "stars": 4, "review": "Agreed receipt; awaiting checkout and settlement.",
                        "accept": acceptance(order, outcome["receipt"])}
        except Exception as error:
            trace("buyer_shop_error", shop=choice["url"], error=type(error).__name__,
                  detail=str(error)[-200:])
            record("negotiation", order=order.get("order"), shop=choice["url"],shop_name=choice['shop'],
                   sku=choice["sku"], result="shop_error", reason=type(error).__name__)
    return {"shop": last_shop, "receipt": None, "stars": 3,
            "review": "No verified receipt within the order time limit."}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shops", type=Path, required=True)
    parser.add_argument("--order", type=Path, required=True)
    parser.add_argument("--own-shop-name", required=True)
    args = parser.parse_args()
    order = json.loads(args.order.read_text(encoding="utf-8"))
    shops = json.loads(args.shops.read_text(encoding="utf-8"))
    catalog = json.loads((args.order.parent / "catalog.json").read_text(encoding="utf-8"))
    result = run(order, shops, catalog, args.own_shop_name)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
