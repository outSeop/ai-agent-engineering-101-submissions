"""First-hand buyer outcomes, separated from unsigned receipts and public reviews."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any


EVENTS = Path("logs/buyer-events.jsonl")
PAYMENTS = Path(".market/payments.jsonl")
BROKEN = Path(".market/broken.jsonl")


def read_events(path: Path = EVENTS) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    result = []
    with path.open(encoding="utf-8", errors="replace") as source:
        for line in source:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and isinstance(event.get("event"), str):
                result.append(event)
    return result


def record(event: str, *, path: Path = EVENTS, **fields: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "event": event, **fields}
    data = (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        if os.write(fd, data) != len(data):
            raise OSError("short buyer event write")
    finally:
        os.close(fd)


def import_payments(payment_path: Path = PAYMENTS, *, event_path: Path = EVENTS) -> int:
    """Import kit payment evidence once; a negotiated receipt is not a purchase."""
    if not payment_path.exists():
        return 0
    seen = {e.get("order") for e in read_events(event_path) if e["event"] == "payment"}
    count = 0
    with payment_path.open(encoding="utf-8", errors="replace") as source:
        for line in source:
            try:
                payment = json.loads(line)
            except ValueError:
                continue
            if not isinstance(payment, dict) or not payment.get("order") or payment["order"] in seen:
                continue
            record("payment", path=event_path, order=payment["order"],
                   shop=payment.get("shop"), sku=payment.get("item"),
                   price=payment.get("price"), paid=payment.get("paid") is True,
                   ledger=payment.get("ledger"), reason=payment.get("reason"))
            seen.add(payment["order"])
            count += 1
    return count


def import_broken(broken_path: Path = BROKEN, *, event_path: Path = EVENTS) -> int:
    """Keep post-sale breakage evidence without guessing which seller caused it."""
    if not broken_path.exists():
        return 0
    seen = {(e.get("name"), e.get("broke_at")) for e in read_events(event_path)
            if e["event"] == "broken"}
    count = 0
    with broken_path.open(encoding="utf-8", errors="replace") as source:
        for line in source:
            try:
                news = json.loads(line)
            except ValueError:
                continue
            if not isinstance(news, dict) or not news.get("name") or not news.get("broke_at"):
                continue
            key = (news["name"], news["broke_at"])
            if key in seen:
                continue
            record("broken", path=event_path, name=news["name"], broke_at=news["broke_at"])
            seen.add(key)
            count += 1
    return count


def context(shop_url: str, sku: str, *, product_name: str | None = None,
            path: Path = EVENTS) -> dict[str, Any]:
    all_events = read_events(path)
    first_hand = [e for e in all_events if e.get("shop") == shop_url]
    payments = [e for e in first_hand if e["event"] == "payment"]
    same_sku = [e for e in payments if e.get("sku") == sku]
    settled = [e for e in first_hand if e["event"] == "settled" and e.get("sku") == sku]
    negotiations = [e for e in first_hand if e["event"] == "negotiation" and e.get("sku") == sku]
    outcomes = Counter("paid" if e.get("paid") else "refused" for e in same_sku)
    return {
        "shop_payment_count": len(payments),
        "same_sku_payment_outcomes": dict(outcomes),
        "recent_same_sku": [{"paid": e.get("paid"), "price": e.get("price"),
                             "reason": e.get("reason"), "ledger": e.get("ledger")}
                            for e in same_sku[-5:]],
        "recent_shop_refusals": [{"sku": e.get("sku"), "reason": e.get("reason")}
                                 for e in payments if not e.get("paid")][-4:],
        "recent_settled_quality": [{"grade": e.get("grade"), "value": e.get("value"),
                                    "price": e.get("price"), "warranty_hours": e.get("warranty_hours")}
                                   for e in settled[-5:]],
        "recent_negotiations": [{"result": e.get("result"), "offers": e.get("offers"),
                                 "reason": e.get("reason")}
                                for e in negotiations[-4:]],
        "observed_receipt_problems": sum(e.get("result") == "invalid_receipt" for e in negotiations),
        "same_product_broken_reports": sum(e["event"] == "broken" and e.get("name") == product_name
                                           for e in all_events) if product_name else 0,
        "note": "Only payment.paid=true is settled evidence. Reviews are public claims. "
                "Broken-item news names a product but cannot identify its seller or exact purchase.",
    }
