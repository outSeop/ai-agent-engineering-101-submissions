"""Operator-only reconciliation and refunds. Authored by OpenAI Codex GPT-6.2 Sol."""
import argparse
import json
import sqlite3
from pathlib import Path
import sys
import time

import httpx

import dispatcher as shop


def list_requests(db):
    return [dict(row) for row in db.execute("""
        SELECT refund.*, sale.market_order, sale.unit FROM refund JOIN sale ON sale.id=refund.sale_id
        WHERE refund.status!='refunded' ORDER BY refund.requested
    """)]


def prepare(db, market, sale_id, now):
    if not shop.reconcile(db, market, now):
        raise shop.Unavailable("the market ledger is not current")
    record = shop.one(db, "SELECT * FROM refund WHERE sale_id=?", sale_id)
    sale = shop.one(db, "SELECT * FROM sale WHERE id=?", sale_id)
    if not record or record["status"] != "requested" or not sale:
        raise shop.Unavailable("there is no unused refund approval")
    if record["incoming"] != sale["payment"] or record["payer"] != sale["payer"]:
        raise shop.Unavailable("original transfer no longer matches")
    costs = shop.refund_cost(market, sale, record["incoming"], record["payer"], record["fee_payment"])
    if costs != tuple(int(record[key]) for key in ("transfer_wei", "fee_wei", "gas_wei")) or sum(costs) != int(record["wei"]):
        raise shop.Unavailable("original expense no longer matches")
    if record["reason"] == "early_market_breakage":
        if sale["status"] != "settled" or sale["broken"] is None or not 0 <= sale["broken"] - sale["settled"] <= shop.WARRANTY:
            raise shop.Unavailable("early issue is not verified")
    elif record["reason"] == "paid_no_delivery":
        if sale["status"] != "paid" or not shop.no_delivery(db, market, sale):
            raise shop.Unavailable("irreversible non-delivery is not verified")
    else:
        raise shop.Unavailable("unknown refund reason")
    block = shop.hex_int(market.rpc("eth_blockNumber"))
    with shop.atomic(db):
        if (shop.one(db, "SELECT name FROM sqlite_master WHERE type='table' AND name='stock_intent'")
                and shop.one(db, "SELECT id FROM stock_intent WHERE state IN ('sending','unknown','paid') LIMIT 1")):
            raise shop.Unavailable("unresolved wholesale transfer blocks a new wallet send")
        current = shop.one(db, "SELECT * FROM sale WHERE id=?", sale_id)
        if (current["status"], current["payer"], current["payment"]) != (sale["status"], sale["payer"], sale["payment"]):
            raise shop.Unavailable("original transaction changed during review")
        updated = db.execute("UPDATE refund SET status='sending' WHERE sale_id=? AND status='requested'", (sale_id,))
        if updated.rowcount != 1:
            raise shop.Unavailable("a refund attempt already exists")
        shop.audit(db, now, "refund_send_started", sale_id, start_block=block)
    return record


def reverse(db, sale, now):
    db.execute("UPDATE sale SET status='refunded' WHERE id=?", (sale["id"],))
    shop.price_policy.resolve(db,sale["id"],"refunded")
    db.execute("UPDATE lot SET revoked=? WHERE sale_id=? AND revoked IS NULL", (now, sale["id"]))
    allocations = db.execute("SELECT lot_id,amount FROM allocation WHERE sale_id=? AND status IN ('held','spent')",
                             (sale["id"],)).fetchall()
    db.execute("UPDATE allocation SET status='released' WHERE sale_id=? AND status IN ('held','spent')", (sale["id"],))
    for allocation in allocations:
        shop.audit(db, now, "mileage_charge_reversed", sale["id"], lot=allocation["lot_id"], amount=allocation["amount"])
    if sale["ticket"]:
        db.execute("UPDATE ticket SET status='released' WHERE key=? AND status='held'", (sale["ticket"],))
    shop.reallocate_debt(db, sale["owner"], now)


def confirm(db, market, sale_id, outgoing, now):
    outgoing = shop.tx_hash(outgoing)
    record = shop.one(db, "SELECT * FROM refund WHERE sale_id=?", sale_id)
    if not record or not outgoing:
        raise shop.Unavailable("unknown refund or invalid transaction hash")
    if record["status"] == "refunded" and record["outgoing"] == outgoing:
        return {"status": "refunded", "outgoing": outgoing}
    if record["status"] not in ("sending", "pending_unknown"):
        raise shop.Unavailable("refund has not been dispatched")
    if record["outgoing"] and record["outgoing"] != outgoing:
        raise shop.Unavailable("a different outgoing transaction is already recorded")
    sale = shop.one(db, "SELECT * FROM sale WHERE id=?", sale_id)
    if not market.transaction(outgoing, sale["wallet"], record["payer"], int(record["wei"]), record["marker"]):
        return {"status": "pending_unknown"}
    with shop.atomic(db):
        current = shop.one(db, "SELECT status,outgoing FROM refund WHERE sale_id=?", sale_id)
        if current["outgoing"] and current["outgoing"] != outgoing:
            raise shop.Unavailable("outgoing transaction changed during review")
        if current["status"] != "refunded":
            db.execute("UPDATE refund SET status='refunded',outgoing=? WHERE sale_id=?", (outgoing, sale_id))
            reverse(db, sale, now)
            shop.audit(db, now, "refund_confirmed", sale_id, outgoing=outgoing, incoming=record["incoming"])
    return {"status": "refunded", "outgoing": outgoing}


def send(db, market, sale_id, pay, now):
    # Calling this function is an operator approval. The durable transition
    # precedes the external call, so a lost response never permits a second send.
    record = prepare(db, market, sale_id, now)
    try:
        outgoing = shop.tx_hash(pay(record["payer"], int(record["wei"]), record["marker"]))
    except Exception:
        outgoing = None
    with shop.atomic(db):
        db.execute("UPDATE refund SET status='pending_unknown',outgoing=? WHERE sale_id=? AND status='sending'",
                   (outgoing, sale_id))
        shop.audit(db, now, "refund_send_result", sale_id, outgoing=outgoing)
    if not outgoing:
        return {"status": "pending_unknown"}
    return confirm(db, market, sale_id, outgoing, now)


def recover(db, market, sale_id, now, outgoing=None, blocks=32, start_block=None):
    record = shop.one(db, "SELECT * FROM refund WHERE sale_id=?", sale_id)
    if not record or record["status"] not in ("sending", "pending_unknown", "refunded"):
        raise shop.Unavailable("there is no dispatched refund to recover")
    if outgoing or record["outgoing"]:
        return confirm(db, market, sale_id, outgoing or record["outgoing"], now)
    audit = shop.one(db, "SELECT details FROM event WHERE kind='refund_send_started' AND reference=?", sale_id)
    start = json.loads(audit["details"])["start_block"]
    if start_block is not None:
        start = max(start, start_block)
    head = shop.hex_int(market.rpc("eth_blockNumber"))
    stop = min(head, start + blocks - 1)
    sale = shop.one(db, "SELECT wallet FROM sale WHERE id=?", sale_id)
    for block in range(start, stop + 1):
        content = market.rpc("eth_getBlockByNumber", hex(block), True)
        if not content:
            return {"status": "pending_unknown", "next_block": block}
        for tx in content["transactions"]:
            if (shop.address(tx.get("from")) == sale["wallet"] and shop.address(tx.get("to")) == record["payer"]
                    and (tx.get("input") or "").lower() == record["marker"]
                    and shop.hex_int(tx.get("value")) == int(record["wei"])):
                return confirm(db, market, sale_id, tx["hash"], now)
    return {"status": "pending_unknown", "last_block_checked": stop,
            "next_block": stop + 1, "more_confirmed_blocks": stop < head}


class OperatorKit:
    name = shop.SHOP
    market = shop.MARKET

    def __init__(self, url, wallet, token_path):
        self.shop_url = url
        self.wallet = wallet
        self.token_path = token_path

    def address(self, role):
        return self.wallet

    def token(self, role):
        return self.token_path.read_text(encoding="utf-8").strip()


def sync_once(db, market, now):
    current = shop.reconcile(db, market, now)
    return {"current": current, "queue_ready": shop.process_queue(db, market, now) if current else 0}


def worker(db, kit, every, *, after_sync=None):
    previous = None
    while True:
        try:
            result = sync_once(db, shop.Market(kit), time.time())
        except (shop.Unavailable, httpx.HTTPError, ValueError, KeyError, OSError):
            result = {"current": False, "queue_ready": 0}
        if after_sync is not None and result["current"]:
            try:
                result["first_purchase_bonus"]=after_sync(db)
            except (OSError, ValueError, sqlite3.Error):
                result["first_purchase_bonus"]={"processed":0,"deferred":True}
        if result != previous:
            print(json.dumps(result), flush=True)
            previous = result
        time.sleep(every)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-root", required=True, type=Path)
    parser.add_argument("--operator-kit", type=Path, help="Official kit directory (needed only when sending)")
    parser.add_argument("--url", required=True)
    parser.add_argument("--address", required=True)
    parser.add_argument("--token-file", required=True, type=Path)
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("sync")
    worker_parser = actions.add_parser("worker")
    worker_parser.add_argument("--every", type=int, default=10)
    actions.add_parser("refunds")
    recover_parser = actions.add_parser("recover")
    recover_parser.add_argument("id")
    recover_parser.add_argument("--outgoing")
    recover_parser.add_argument("--blocks", type=int, default=32)
    recover_parser.add_argument("--start-block", type=int)
    send_parser = actions.add_parser("approve-and-send")
    send_parser.add_argument("id")
    send_parser.add_argument("--wallet-file", type=Path, required=True)
    send_parser.add_argument("--confirm-original-hash", required=True)
    args = parser.parse_args()
    kit = OperatorKit(args.url, args.address, args.token_file)
    market = shop.Market(kit)
    db = shop.open_db(args.agent_root.resolve(strict=True) / shop.DB, market.wallet)
    try:
        now = time.time()
        if args.action == "sync":
            result = sync_once(db, market, now)
        elif args.action == "worker":
            worker(db, kit, shop.whole(args.every, 5, 3600))
            return
        elif args.action == "refunds":
            result = list_requests(db)
        elif args.action == "recover":
            result = recover(db, market, args.id, now, args.outgoing, shop.whole(args.blocks, 1, 128),
                             shop.whole(args.start_block) if args.start_block is not None else None)
        else:
            record = shop.one(db, "SELECT incoming FROM refund WHERE sale_id=?", args.id)
            if not record or record["incoming"] != shop.tx_hash(args.confirm_original_hash):
                parser.error("the original transfer hash must match the selected refund")
            if not args.operator_kit:
                parser.error("--operator-kit is required for sending")
            sys.path.insert(0, str(args.operator_kit.resolve(strict=True)))
            import maroo

            if maroo.RPC_URL != shop.RPC or maroo.CHAIN_ID != 450815:
                parser.error("official signer does not target Maroo testnet")
            # Validate the existing signer before claiming an irreversible
            # refund attempt. Never generate or alter a key file.
            wallet = maroo.Wallet.from_hex(args.wallet_file.read_text(encoding="utf-8"))
            if wallet.address.lower() != market.wallet:
                parser.error("refund signer does not match the shop")
            from eth_utils import to_checksum_address

            def pay(payer, wei, marker):
                return maroo.pay(wallet, to_checksum_address(payer), wei, bytes.fromhex(marker[2:]))

            result = send(db, market, args.id, pay, now)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except KeyboardInterrupt:
        return
    except shop.Unavailable as error:
        parser.exit(2, str(error) + "\n")
    finally:
        db.close()


if __name__ == "__main__":
    main()

