"""Append-only seller evidence and compact context for the next model call.

A signed receipt is deliberately distinct from a settled sale. Settlement is
observed from the kit log, whose [acp] line includes the shipped unit and ledger
number. No receipt-only result is counted as revenue or conversion.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any


EVENTS = Path("logs/shop-events.jsonl")
KIT_LOG = Path("logs/market-kit.log")
CURSOR = Path("state/settlement-cursor.json")
SETTLED = re.compile(r"\[acp\] settled .*? at (?P<price>\d+), ledger #(?P<ledger>\d+), "
                     r"unit (?P<unit>[^\s,]+) grade (?P<grade>[ABC])")


def events(path: Path = EVENTS) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    result = []
    with path.open(encoding="utf-8", errors="replace") as source:
        for line in source:
            try:
                row = json.loads(line)
            except ValueError:
                continue                         # interrupted last write is never evidence
            if isinstance(row, dict) and row.get("event"):
                result.append(row)
    return result


def record(event: str, *, path: Path = EVENTS, **fields: Any) -> dict[str, Any]:
    row = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "event": event, **fields}
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        if os.write(fd, data) != len(data):
            raise OSError("short event-log write")
    finally:
        os.close(fd)
    return row


def sync_settlements(kit_log: Path = KIT_LOG, *, event_log: Path = EVENTS,
                     cursor_path: Path = CURSOR) -> int:
    """Import only complete new [acp] settlement lines; survive log rotation."""
    if not kit_log.exists():
        return 0
    old = events(event_log)
    seen = {int(e["ledger"]) for e in old if e["event"] == "settled" and "ledger" in e}
    receipt_by_unit = {e["unit"]: e for e in old
                       if e["event"] == "receipt_signed" and e.get("unit")}
    stat = kit_log.stat()
    try:
        cursor = json.loads(cursor_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cursor = {}
    offset = (int(cursor["offset"]) if cursor.get("inode") == stat.st_ino
              and 0 <= cursor.get("offset", -1) <= stat.st_size else 0)
    added = 0
    with kit_log.open(encoding="utf-8", errors="replace") as source:
        source.seek(offset)
        while True:
            before = source.tell()
            line = source.readline()
            if not line:
                break
            if not line.endswith("\n"):
                source.seek(before)             # the kit is still writing this line
                break
            match = SETTLED.search(line)
            if not match:
                continue
            ledger = int(match["ledger"])
            if ledger in seen:
                continue
            receipt = receipt_by_unit.get(match["unit"], {})
            record("settled", path=event_log, ledger=ledger, unit=match["unit"],
                   grade=match["grade"], price=int(match["price"]),
                   sku=receipt.get("sku"), task_id=receipt.get("task_id"))
            seen.add(ledger)
            added += 1
        next_offset = source.tell()
    cursor_path.parent.mkdir(parents=True, exist_ok=True)
    temp = cursor_path.with_suffix(".tmp")
    temp.write_text(json.dumps({"inode": stat.st_ino, "offset": next_offset}), encoding="utf-8")
    os.replace(temp, cursor_path)
    return added


def compact_context(sku: str, grade: str, *, path: Path = EVENTS,
                    recent_limit: int = 12) -> dict[str, Any]:
    """Bound model context while retaining both failures and confirmed sales."""
    attempts: dict[str, dict[str, Any]] = {}
    settled_by_task: dict[str, dict[str, Any]] = {}
    for row in events(path):
        task = row.get("task_id")
        kind = row["event"]
        if kind == "settled" and task:
            settled_by_task[task] = row
        elif kind == "opening" and task:
            attempts[task] = {"task_id": task, "sku": row.get("sku"),
                              "grade": row.get("grade"), "category": row.get("category"),
                              "unit": row.get("unit"), "opening_ask": row.get("ask"),
                              "list_price": row.get("list_price"), "at": row.get("at"),
                              "offers": [], "counters": [], "outcome": "OPEN"}
        elif task in attempts and kind == "offer":
            attempts[task]["offers"].append(row.get("price"))
        elif task in attempts and kind == "counter":
            attempts[task]["counters"].append(row.get("ask"))
        elif task in attempts and kind == "receipt_signed":
            attempts[task]["outcome"] = "RECEIPT_PENDING"
            attempts[task]["agreed_price"] = row.get("price")
        elif task in attempts and kind in {"rejected", "cancelled"}:
            attempts[task]["outcome"] = kind.upper()
    for task, settlement in settled_by_task.items():
        if task in attempts:
            attempts[task]["outcome"] = "SETTLED"
            attempts[task]["settled_price"] = settlement["price"]
            attempts[task]["ledger"] = settlement["ledger"]

    relevant = [a for a in attempts.values() if a["sku"] == sku and a["grade"] == grade]
    broader = [a for a in attempts.values() if a["sku"] == sku and a["grade"] != grade]
    counts = defaultdict(int)
    for a in relevant:
        counts[a["outcome"]] += 1
    return {
        "sku": sku, "grade": grade, "same_grade_attempts": len(relevant),
        "same_sku_other_grade_attempts": len(broader),
        "outcomes": dict(counts),
        "recent_same_grade": relevant[-recent_limit:],
        "recent_other_grade": broader[-min(4, recent_limit):],
        "caution": "A receipt is pending until [acp] settled; OPEN is unknown, not a failed sale. "
                   "Only shops visited by buyers appear here, so this is not total market demand.",
    }
