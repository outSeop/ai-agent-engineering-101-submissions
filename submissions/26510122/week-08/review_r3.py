"""Review a settled purchase and publish occasional ledger-backed buyer notes."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time

from buyer_memory import read_events, record


OUTBOX = Path(".market/outbox.jsonl")
POST_INTERVAL = 1800


def append_outbox(post: dict, path: Path = OUTBOX) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(post, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        if os.write(fd, data) != len(data):
            raise OSError("short forum outbox write")
    finally:
        os.close(fd)


def run(deal: dict, catalog: dict) -> dict:
    order, settled = deal["order"], deal["settled"]
    sku = settled.get("sku") or deal["receipt"].get("item")
    product = catalog.get(sku, {})
    price = int(deal["receipt"]["price"])
    list_price = int(product.get("list_price") or 0)
    value = int(settled.get("value") or 0)
    grade = settled.get("grade")
    ledger = settled.get("ledger")
    shop = settled.get("shop")
    record("settled", order=order.get("order"), shop=shop, sku=sku,
           name=settled.get("name"), price=price, list_price=list_price,
           grade=grade, value=value, ledger=ledger,
           claim_honest=settled.get("claim_honest"),
           warranty_hours=settled.get("warranty_hours"))
    if value <= 0:
        stars = 2
        review = f"Paid {price} for {sku}; the item had no usable value at settlement."
    else:
        discount = (list_price - price) / list_price if list_price > 0 else 0.0
        stars = 5 if discount >= 0.25 and settled.get("claim_honest") is not False else 4
        review = f"Paid {price} for {sku}; certified grade {grade or 'unknown'} at settlement."
    if settled.get("claim_honest") is False:
        stars = min(stars, 2)
        review += " The seller's grade claim did not match the market record."

    recent_posts = [e.get("epoch", 0) for e in read_events() if e["event"] == "forum_post"]
    if (value > 0 and list_price > 0 and price <= list_price * 0.8
            and isinstance(ledger, int) and time.time() - max(recent_posts, default=0) >= POST_INTERVAL):
        discount_pct = round((1 - price / list_price) * 100)
        text = (f"Settled purchase: {settled.get('name') or sku} ({sku}), grade {grade}, "
                f"paid {price} vs list {list_price} ({discount_pct}% less). "
                "Ledger reference attached; quality can change after settlement.")
        append_outbox({"post": text, "refs": [ledger], "as": "buyer"})
        record("forum_post", epoch=time.time(), ledger=ledger, sku=sku)
    return {"stars": stars, "review": review}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deal", type=Path, required=True)
    args = parser.parse_args()
    deal = json.loads(args.deal.read_text(encoding="utf-8"))
    catalog = json.loads((args.deal.parent / "catalog.json").read_text(encoding="utf-8"))
    print(json.dumps(run(deal, catalog), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
