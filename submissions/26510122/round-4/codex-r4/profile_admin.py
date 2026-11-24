"""Private operator views and structured customer self-reports. OpenAI Codex GPT-6.2 Sol."""
import argparse
import json
from pathlib import Path
import sys
import time

import dispatcher as shop


UNKNOWN = {"value": None, "source": None, "confidence": "unknown", "at": None}


def profile_rows(db, limit=100, after=""):
    return [dict(row) for row in db.execute("""
        SELECT p.profile_id, a.created FROM customer_profile p JOIN account a ON a.key=p.owner
        WHERE p.profile_id>? ORDER BY p.profile_id LIMIT ?
    """, (after, limit))]


def ensure_profiles(db):
    # Existing accounts receive independent random identifiers. No historical
    # visits or profile facts can be inferred from the financial rows.
    with shop.atomic(db):
        for account in db.execute("SELECT key FROM account WHERE key NOT IN (SELECT owner FROM customer_profile)").fetchall():
            shop.ensure_profile(db, account["key"])


def resolve(db, profile_id):
    profile = shop.one(db, "SELECT owner FROM customer_profile WHERE profile_id=?", profile_id)
    if not profile:
        raise shop.Unavailable("unknown internal profile identifier")
    return profile["owner"]


def _fact(row):
    return {"field": row["field"], "key": row["fact_key"],
            "value": json.loads(row["value"]) if row["value"] is not None else None,
            "source": row["source"], "confidence": row["confidence"],
            "at": row["at"], "discarded": bool(row["discarded"])}


def facts(db, profile_id, history=False):
    owner = resolve(db, profile_id)
    if history:
        rows = db.execute("SELECT * FROM profile_fact WHERE owner=? ORDER BY id", (owner,))
    else:
        rows = db.execute("""
            SELECT * FROM profile_fact
            WHERE id IN (
                SELECT max(id) FROM profile_fact WHERE owner=? GROUP BY field,fact_key
            ) AND discarded=0 ORDER BY field,fact_key
        """, (owner,))
    return [_fact(row) for row in rows]


def profile(db, profile_id, now):
    owner = resolve(db, profile_id)
    visit = shop.one(db, "SELECT count(*) visits,min(started) first_visit,max(last_seen) last_seen FROM visit WHERE owner=?",
                     owner)
    status = shop.one(db, """
        SELECT coalesce(sum(a.amount) FILTER (WHERE a.status='held'),0) reserved,
               coalesce(sum(a.amount) FILTER (WHERE a.status='offset' AND l.revoked IS NULL),0) offset
        FROM lot l JOIN allocation a ON a.lot_id=l.sale_id WHERE l.owner=?
    """, owner)
    expired = shop.one(db, """
        SELECT count(*) lots, coalesce(sum(expired_credits),0) credits
        FROM (SELECT l.amount-coalesce(sum(a.amount),0) expired_credits FROM lot l
              LEFT JOIN allocation a ON a.lot_id=l.sale_id AND a.status!='released'
              WHERE l.owner=? AND l.revoked IS NULL AND l.expires<=? GROUP BY l.sale_id)
    """, owner, now)
    active = shop.remaining_lots(db, owner, now)
    next_expiration = shop.one(db, "SELECT min(expires) FROM lot WHERE sale_id=?", active[0]["sale_id"])[0] if active else None
    spent_per_item = """
        SELECT {expression} AS item, count(*) AS settled,
            count(*) FILTER (WHERE s.status='refunded') AS refunded,
            count(*) FILTER (WHERE s.broken IS NOT NULL) AS broken,
            count(*) FILTER (WHERE s.status='settled' AND s.broken IS NULL) AS retained
        FROM sale s LEFT JOIN sale_category c ON c.sale_id=s.id
        WHERE s.owner=? AND s.market_order IS NOT NULL GROUP BY item
        ORDER BY retained DESC,settled DESC,item
    """
    items = [dict(row) for row in db.execute(spent_per_item.format(expression="s.sku"), (owner,))]
    categories = [dict(row) for row in db.execute(spent_per_item.format(expression="c.category"), (owner,))]
    buyer_links = [dict(row) for row in db.execute("""
        SELECT b.market_buyer, s.payer AS payment_wallet, count(*) AS settlements,
               max(b.verified_at) AS last_verified, 'market_ledger_and_rpc' AS source
        FROM sale s JOIN sale_buyer b ON b.sale_id=s.id WHERE s.owner=?
        GROUP BY b.market_buyer,s.payer ORDER BY last_verified DESC
    """, (owner,))]
    current = facts(db, profile_id)
    household = next((row for row in current if row["field"] == "household_size"), UNKNOWN)
    income = next((row for row in current if row["field"] == "income_bracket"), UNKNOWN)
    return {"profile_id": profile_id, "visits": dict(visit, definition="authenticated_contact_sessions", inactivity_seconds=shop.VISIT_GAP),
            "mileage": {"available": sum(lot["available"] for lot in active), "reserved": status["reserved"],
                        "debt": max(0, shop.debt_amount(db, owner) - status["offset"]),
                        "expired_unused": expired["credits"], "expired_lots": expired["lots"],
                        "next_expiration": next_expiration},
            "purchases": {"by_sku": items, "by_category": categories},
            "market_buyer_links": buyer_links,
            "self_reported": {"household_size": household, "income_bracket": income,
                              "family": [row for row in current if row["field"] == "family"],
                              "preferences": [row for row in current if row["field"] == "preference"]}}


def convert(entry):
    if not isinstance(entry, dict) or type(entry.get("discard", False)) is not bool:
        raise shop.Unavailable("invalid fact")
    field, clear = entry.get("type"), entry.get("discard", False)
    operations = {
        "family": ("가족", {"relation"}, {"count"}),
        "household_size": ("가구", set(), {"count"}),
        "income_bracket": ("소득", set(), {"scale", "band"}),
        "preference": ("선호", {"kind", "value"}, {"sentiment"}),
    }
    if not isinstance(field, str) or field not in operations:
        raise shop.Unavailable("unknown fact type")
    label, identifiers, amounts = operations[field]
    required = {"type"} | identifiers | (set() if clear else amounts)
    if not required <= set(entry) or set(entry) - required - {"discard"}:
        raise shop.Unavailable("unexpected fact fields")
    parts = ["삭제", label] if clear else [label]
    if field == "family":
        relation = next((local for local, normalized in shop.RELATIONS.items() if normalized == entry["relation"]), "")
        parts.append(relation)
    if field == "preference":
        if not isinstance(entry["kind"], str) or not isinstance(entry["value"], str):
            raise shop.Unavailable("invalid preference")
        parts.extend((entry["kind"], entry["value"]))
        if not clear:
            sentiment = entry["sentiment"]
            if not isinstance(sentiment, str):
                raise shop.Unavailable("invalid preference sentiment")
            parts.append({"likes": "좋아함", "avoids": "피함"}.get(sentiment, ""))
    if not clear and field in ("household_size", "family"):
        parts.append(str(shop.whole(entry["count"], 0, 30)))
    if not clear and field == "income_bracket":
        if entry["scale"] not in ("decile", "quintile"):
            raise shop.Unavailable("income scale was not specified")
        parts.extend((entry["scale"], str(shop.whole(entry["band"], 1, 10))))
    result = shop.fact_change(parts)
    if result is None:
        raise shop.Unavailable("unsupported structured self-report")
    return result


def ingest(db, document, now):
    if not isinstance(document, dict) or set(document) != {"profile_id", "facts"}:
        raise shop.Unavailable("expected profile_id and facts only")
    owner = resolve(db, document["profile_id"])
    entries = document["facts"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= 30:
        raise shop.Unavailable("expected 1 to 30 facts")
    changes = [convert(entry) for entry in entries]
    with shop.atomic(db):
        changed = sum(shop.record_fact(db, owner, change, now, "operator_recorded_self_report")
                      for change in changes)
    return {"recorded": changed, "profile_id": document["profile_id"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-root", required=True, type=Path)
    parser.add_argument("--address", required=True, help="registered shop address")
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list")
    listing.add_argument("--limit", type=int, default=100)
    listing.add_argument("--after", default="")
    single = commands.add_parser("profile")
    single.add_argument("id")
    fact_commands = commands.add_parser("facts").add_subparsers(dest="fact_command", required=True)
    history = fact_commands.add_parser("history")
    history.add_argument("id")
    fact_commands.add_parser("ingest", help="Read structured customer-declared facts from stdin")
    args = parser.parse_args()
    address = shop.address(args.address)
    if not address:
        parser.error("invalid registered wallet address")
    db = shop.open_db(args.agent_root.resolve(strict=True) / shop.DB, address)
    try:
        ensure_profiles(db)
        if args.command == "list":
            out = profile_rows(db, shop.whole(args.limit, 1, 1000), args.after)
        elif args.command == "profile":
            out = profile(db, args.id, time.time())
        elif args.fact_command == "history":
            out = facts(db, args.id, history=True)
        else:
            out = ingest(db, json.loads(sys.stdin.read(16_385)), time.time())
        print(json.dumps(out, ensure_ascii=False, indent=2))
    except (shop.Unavailable, ValueError, TypeError, KeyError) as error:
        parser.exit(2, str(error) + "\n")
    finally:
        db.close()


if __name__ == "__main__":
    main()

