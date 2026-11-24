"""Round 4 sales dispatcher. Authored by OpenAI Codex GPT-6.2 Sol."""
import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from time import monotonic
from urllib.parse import urlsplit

import httpx

SHOP = "outseop-r4"
MARKET = "https://market.ourolabs.ai"
RPC = "https://rpc-testnet.maroo.io"
DB = Path("state/r4-benefits/benefits.sqlite3")
WEEK = 7 * 86400
WAIT = 120
WARRANTY = 48 * 3600
VISIT_GAP = 30 * 60
RELATIONS = {"배우자": "partner", "자녀": "child", "부모": "parent", "형제자매": "sibling",
             "조부모": "grandparent", "손자녀": "grandchild", "기타가족": "other_family"}
INCOME_SCALES = {"분위10": ("decile", 10), "분위5": ("quintile", 5),
                 "decile": ("decile", 10), "quintile": ("quintile", 5)}
CATEGORY_LABELS = {"식품": "food", "생활용품": "household", "주방용품": "kitchen",
                   "문구": "stationery", "의류": "clothing", "가전": "appliances"}
GRADES = {"A": 100, "B": 90, "C": 80}
CODE = re.compile(r"[A-Za-z0-9_-]{43}\Z")
SKU = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
HASH = re.compile(r"0x[0-9a-fA-F]{64}\Z")
ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}\Z")
SCHEMA = """
CREATE TABLE IF NOT EXISTS identity (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1), shop TEXT NOT NULL, wallet TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS account (
    key TEXT PRIMARY KEY, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS customer_profile (
    owner TEXT PRIMARY KEY REFERENCES account(key), profile_id TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS visit (
    id INTEGER PRIMARY KEY, owner TEXT NOT NULL REFERENCES customer_profile(owner),
    started REAL NOT NULL, last_seen REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS visit_latest ON visit(owner,id DESC);
CREATE TABLE IF NOT EXISTS visit_session_transport (
    visit_id INTEGER NOT NULL REFERENCES visit(id), transport_hash TEXT NOT NULL,
    PRIMARY KEY(visit_id,transport_hash)
);
CREATE TABLE IF NOT EXISTS profile_fact (
    id INTEGER PRIMARY KEY, owner TEXT NOT NULL REFERENCES customer_profile(owner),
    field TEXT NOT NULL, fact_key TEXT NOT NULL, value TEXT, source TEXT NOT NULL,
    confidence TEXT NOT NULL CHECK(confidence='self_reported'), at REAL NOT NULL,
    discarded INTEGER NOT NULL CHECK(discarded IN (0,1))
);
CREATE INDEX IF NOT EXISTS profile_fact_latest ON profile_fact(owner,field,fact_key,id DESC);
CREATE TABLE IF NOT EXISTS ticket (
    key TEXT PRIMARY KEY, sku TEXT NOT NULL, owner TEXT REFERENCES account(key),
    created REAL NOT NULL, expires REAL NOT NULL, discount INTEGER NOT NULL,
    ready REAL,
    status TEXT NOT NULL CHECK(status IN ('waiting','held','used','released'))
);
CREATE INDEX IF NOT EXISTS queue_lookup ON ticket(sku,status,expires,created);
CREATE TABLE IF NOT EXISTS sale (
    id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES account(key),
    unit TEXT NOT NULL, sku TEXT NOT NULL, base INTEGER NOT NULL CHECK(base>0),
    cost INTEGER NOT NULL CHECK(cost>=0), price INTEGER NOT NULL CHECK(price>0),
    discount INTEGER NOT NULL CHECK(discount>=0), spent INTEGER NOT NULL CHECK(spent>=0),
    ticket TEXT REFERENCES ticket(key), shop_url TEXT NOT NULL, wallet TEXT NOT NULL, created REAL NOT NULL,
    digest TEXT UNIQUE NOT NULL, jwt TEXT NOT NULL, expected_wei TEXT NOT NULL,
    fee_wei TEXT NOT NULL, gas_cap_wei TEXT NOT NULL, fee_wallet TEXT NOT NULL, grade TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('issued','cancel_requested','paid','missing','settled','refunded')),
    market_order TEXT UNIQUE, payment TEXT UNIQUE, fee_payment TEXT UNIQUE, payer TEXT, settled REAL, broken REAL,
    CHECK(price=base-discount-spent)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_unit ON sale(unit)
    WHERE status IN ('issued','cancel_requested','paid','missing');
CREATE TABLE IF NOT EXISTS sale_category (
    sale_id TEXT PRIMARY KEY REFERENCES sale(id), category TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sale_buyer (
    sale_id TEXT PRIMARY KEY REFERENCES sale(id), market_buyer TEXT NOT NULL, verified_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS lot (
    sale_id TEXT PRIMARY KEY REFERENCES sale(id), owner TEXT NOT NULL REFERENCES account(key),
    amount INTEGER NOT NULL CHECK(amount>0), expires REAL NOT NULL, revoked REAL
);
CREATE TABLE IF NOT EXISTS allocation (
    id INTEGER PRIMARY KEY, sale_id TEXT REFERENCES sale(id), lot_id TEXT NOT NULL REFERENCES lot(sale_id),
    amount INTEGER NOT NULL CHECK(amount>0),
    status TEXT NOT NULL CHECK(status IN ('held','spent','offset','released')),
    CHECK(sale_id IS NOT lot_id)
);
CREATE INDEX IF NOT EXISTS allocation_lot ON allocation(lot_id,status);
CREATE INDEX IF NOT EXISTS allocation_sale ON allocation(sale_id,status);
CREATE TABLE IF NOT EXISTS refund (
    sale_id TEXT PRIMARY KEY REFERENCES sale(id), incoming TEXT NOT NULL UNIQUE,
    payer TEXT NOT NULL, wei TEXT NOT NULL, marker TEXT NOT NULL UNIQUE,
    transfer_wei TEXT NOT NULL, fee_wei TEXT NOT NULL, gas_wei TEXT NOT NULL, fee_payment TEXT,
    reason TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN (
        'requested','sending','pending_unknown','refunded')),
    outgoing TEXT UNIQUE, requested REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS event (
    id INTEGER PRIMARY KEY, at REAL NOT NULL, kind TEXT NOT NULL, reference TEXT NOT NULL,
    details TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS removal (
    unit TEXT PRIMARY KEY, seq INTEGER NOT NULL, reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cursor (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1), seq INTEGER NOT NULL, hash TEXT NOT NULL
);
"""


class Unavailable(Exception):
    """An authoritative input was absent or invalid."""


def key_of(code):
    return hashlib.sha256(code.encode("ascii")).hexdigest() if CODE.fullmatch(code or "") else None


def tx_hash(value):
    return value.lower() if isinstance(value, str) and HASH.fullmatch(value) else None


def address(value):
    return value.lower() if isinstance(value, str) and ADDRESS.fullmatch(value) else None


def whole(value, minimum=0, maximum=10**12):
    if type(value) is not int or not minimum <= value <= maximum:
        raise Unavailable("invalid amount")
    return value


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 10**11:
        raise Unavailable("invalid time")
    return value


def hex_int(value):
    if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-fA-F]{1,64}", value):
        raise Unavailable("invalid chain integer")
    return int(value, 16)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def audit(db, now, kind, ref, **details):
    db.execute("INSERT INTO event(at,kind,reference,details) VALUES(?,?,?,?)",
               (now, kind, ref, canonical(details).decode()))


def one(db, sql, *params):
    return db.execute(sql, params).fetchone()


def open_db(db_path, wallet):
    db_path = Path(db_path)
    db_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if db_path.parent.is_symlink() or db_path.is_symlink():
        raise Unavailable("unexpected ledger path")
    fd = os.open(db_path, os.O_CREAT | os.O_APPEND | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    os.close(fd)
    db = sqlite3.connect(db_path, timeout=5, isolation_level=None)
    try:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(SCHEMA)
        with atomic(db):
            db.execute("INSERT OR IGNORE INTO identity VALUES(1,?,?)", (SHOP, wallet))
            identity = one(db, "SELECT shop,wallet FROM identity WHERE singleton=1")
            if tuple(identity) != (SHOP, wallet):
                raise Unavailable("ledger belongs to another shop wallet")
    except BaseException:
        db.close()
        raise
    return db


@contextmanager
def atomic(db):
    db.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        db.rollback()
        raise
    else:
        db.commit()


class Market:
    def __init__(self, kit):
        if kit.name != SHOP or kit.market.rstrip("/") != MARKET:
            raise Unavailable("wrong market or shop")
        self.kit = kit
        self.deadline = monotonic() + 40
        self.wallet = address(kit.address("shop"))
        self.shop_url = (kit.shop_url or "").rstrip("/")
        parts = urlsplit(self.shop_url)
        if not self.wallet or parts.scheme != "https" or not parts.hostname or parts.username:
            raise Unavailable("invalid public shop identity")

    def timeout(self):
        remaining = self.deadline - monotonic()
        if remaining <= 0:
            raise Unavailable("authoritative lookup exceeded its deadline")
        return min(remaining, 4)

    def get(self, path, *, params=None, auth=False):
        headers = {"authorization": "Bearer " + self.kit.token("shop")} if auth else None
        response = httpx.get(MARKET + path, headers=headers, params=params, timeout=self.timeout(), trust_env=False)
        response.raise_for_status()
        return response.json()

    def rpc(self, method, *params):
        response = httpx.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                              timeout=self.timeout(), trust_env=False)
        response.raise_for_status()
        data = response.json()
        if data.get("error") or "result" not in data:
            raise Unavailable("chain did not answer")
        return data["result"]

    def chain(self):
        facts = self.get("/api/chain")
        if (facts.get("rpc") != RPC or facts.get("chain_id") != 450815
                or not address(facts.get("market_address"))):
            raise Unavailable("unexpected chain facts")
        return (whole(facts.get("credit_wei"), 1, 10**18), whole(facts.get("market_fee_bps"), 0, 9999),
                whole(facts.get("network_fee_credits")), address(facts["market_address"]))

    def inventory(self):
        payload = self.get("/api/inventory", auth=True)
        if payload.get("round") != 4 or address(payload.get("wallet")) != self.wallet:
            raise Unavailable("wrong inventory shop")
        units = payload.get("units")
        if not isinstance(units, list):
            raise Unavailable("missing inventory")
        return units

    def transaction(self, hash_, sender, recipient, wei, marker, *, include_cost=False):
        hash_ = tx_hash(hash_)
        if not hash_:
            return None
        tx = self.rpc("eth_getTransactionByHash", hash_)
        receipt = self.rpc("eth_getTransactionReceipt", hash_)
        if not tx or not receipt:
            return None
        payer = address(tx.get("from"))
        block = tx_hash(tx.get("blockHash"))
        if (not payer or (sender is not None and payer != sender)
                or address(tx.get("to")) != recipient or tx.get("input", "").lower() != marker
                or tx_hash(tx.get("hash")) != hash_ or tx_hash(receipt.get("transactionHash")) != hash_
                or not block or tx_hash(receipt.get("blockHash")) != block
                or receipt.get("blockNumber") != tx.get("blockNumber")
                or hex_int(tx.get("value")) != wei or hex_int(receipt.get("status")) != 1):
            return None
        if hex_int(self.rpc("eth_blockNumber")) < hex_int(tx.get("blockNumber")) + 2:
            return None
        if include_cost:
            gas = hex_int(receipt.get("gasUsed")) * hex_int(receipt.get("effectiveGasPrice"))
            return payer, gas
        return payer


def ensure_profile(db, owner):
    db.execute("INSERT OR IGNORE INTO customer_profile VALUES(?,?)", (owner, "r4p-" + secrets.token_hex(16)))


def record_visit(db, owner, now, observation=None):
    ensure_profile(db, owner)
    previous = one(db, "SELECT id,last_seen FROM visit WHERE owner=? ORDER BY id DESC LIMIT 1", owner)
    if previous and now < previous["last_seen"] + VISIT_GAP:
        visit_id = previous["id"]
    else:
        visit_id = db.execute("INSERT INTO visit(owner,started,last_seen) VALUES(?,?,?)", (owner, now, now)).lastrowid
    # A task ID suppresses repeated delivery within this session. It can be
    # reused by a later authenticated contact without linking the two sessions.
    if isinstance(observation, str) and 1 <= len(observation) <= 128:
        cursor = db.execute("INSERT OR IGNORE INTO visit_session_transport VALUES(?,?)", (visit_id, digest(observation)))
        if cursor.rowcount == 0:
            return
    db.execute("UPDATE visit SET last_seen=max(last_seen,?) WHERE id=?", (now, visit_id))


def category_key(value):
    if not isinstance(value, str):
        return None
    value = CATEGORY_LABELS.get(value, value)
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,31}", value):
        return value.lower()
    return None


def fact_change(parts):
    # Store compact structured self-reports. Never keep names, free text or codes.
    clear = bool(parts and parts[0] == "삭제")
    if clear:
        parts = parts[1:]
    if not parts:
        return None
    kind, *values = parts
    if kind == "가족" and len(values) == (1 if clear else 2):
        relation = RELATIONS.get(values[0])
        if relation and clear:
            return "family", relation, None
        if relation and re.fullmatch(r"0|[1-9]|[12][0-9]|30", values[1]):
            return "family", relation, {"relation": relation, "count": int(values[1])}
    if kind == "가구" and len(values) == (0 if clear else 1):
        if clear:
            return "household_size", "household_size", None
        if re.fullmatch(r"[1-9]|[12][0-9]|30", values[0]):
            return "household_size", "household_size", {"count": int(values[0])}
    if kind == "소득" and len(values) == (0 if clear else 2):
        if clear:
            return "income_bracket", "income_bracket", None
        scale = INCOME_SCALES.get(values[0])
        if scale and re.fullmatch(r"[1-9]|10", values[1]) and 1 <= int(values[1]) <= scale[1]:
            return "income_bracket", "income_bracket", {"scale": scale[0], "band": int(values[1])}
    if kind == "선호" and len(values) == (2 if clear else 3):
        namespace = values[0]
        identifier = None
        if namespace == "sku" and re.fullmatch(r"[FG][A-Fa-f0-9]{8}", values[1]):
            identifier = values[1]
        if namespace == "category":
            candidate = category_key(values[1])
            if candidate in CATEGORY_LABELS.values():
                identifier = candidate
        if identifier:
            key = f"{namespace}:{identifier}"
            if clear:
                return "preference", key, None
            sentiment = {"좋아함": "likes", "피함": "avoids"}.get(values[2])
            if sentiment:
                return "preference", key, {"kind": namespace, "value": identifier, "sentiment": sentiment}
    return None


def record_fact(db, owner, change, now, source):
    field, key, value = change
    serialized = canonical(value).decode() if value is not None else None
    previous = one(db, """SELECT value,discarded FROM profile_fact WHERE owner=? AND field=? AND fact_key=?
                          ORDER BY id DESC LIMIT 1""", owner, field, key)
    discarded = value is None
    if previous and previous["value"] == serialized and previous["discarded"] == discarded:
        return False
    db.execute("""INSERT INTO profile_fact(owner,field,fact_key,value,source,confidence,at,discarded)
                  VALUES(?,?,?,?,?,'self_reported',?,?)""",
               (owner, field, key, serialized, source, now, int(discarded)))
    return True


def remaining_lots(db, owner, now):
    return db.execute("""
        SELECT l.sale_id, l.amount - coalesce(sum(a.amount),0) AS available
        FROM lot l LEFT JOIN allocation a ON a.lot_id=l.sale_id AND a.status!='released'
        WHERE l.owner=? AND l.expires>? AND l.revoked IS NULL
        GROUP BY l.sale_id HAVING available>0 ORDER BY l.expires,l.sale_id
    """, (owner, now)).fetchall()


def debt_amount(db, owner):
    return one(db, """
        SELECT coalesce(sum(a.amount),0) FROM lot l
        JOIN allocation a ON a.lot_id=l.sale_id AND a.status IN ('held','spent')
        WHERE l.owner=? AND l.revoked IS NOT NULL
    """, owner)[0]


def balance(db, owner, now):
    return sum(row["available"] for row in remaining_lots(db, owner, now))


def reallocate_debt(db, owner, now):
    debt = debt_amount(db, owner)
    offsets = db.execute("""
        SELECT a.* FROM allocation a JOIN lot l ON l.sale_id=a.lot_id
        WHERE l.owner=? AND a.status='offset' AND l.revoked IS NULL ORDER BY a.id DESC
    """, (owner,)).fetchall()
    delta = debt - sum(row["amount"] for row in offsets)
    for offset in offsets:
        if delta >= 0:
            break
        released = min(-delta, offset["amount"])
        db.execute("UPDATE allocation SET status='released' WHERE id=?", (offset["id"],))
        if released < offset["amount"]:
            db.execute("INSERT INTO allocation(lot_id,amount,status) VALUES(?,?,'offset')",
                       (offset["lot_id"], offset["amount"] - released))
        audit(db, now, "offset_released", offset["lot_id"], amount=released)
        delta += released
    for lot in remaining_lots(db, owner, now):
        if delta <= 0:
            break
        amount = min(delta, lot["available"])
        db.execute("INSERT INTO allocation(lot_id,amount,status) VALUES(?,?,'offset')",
                   (lot["sale_id"], amount))
        audit(db, now, "debt_offset", lot["sale_id"], amount=amount)
        delta -= amount
    return max(0, delta)


def reserve(db, sale_id, owner, amount, now):
    whole(amount)
    for lot in remaining_lots(db, owner, now):
        if amount == 0:
            break
        portion = min(amount, lot["available"])
        db.execute("INSERT INTO allocation(sale_id,lot_id,amount,status) VALUES(?,?,?,'held')",
                   (sale_id, lot["sale_id"], portion))
        amount -= portion
    if amount:
        raise Unavailable("insufficient unreserved mileage")


def finalize_sale(db, sale, data, settled, payer, now):
    db.execute("""
        UPDATE sale SET status='settled', market_order=?, payment=?, fee_payment=?, payer=?, settled=? WHERE id=?
    """, (data["order"], data["tx_hash"].lower(), tx_hash(data.get("fee_tx_hash")), payer, settled, sale["id"]))
    buyer = data.get("buyer")
    if isinstance(buyer, str) and 1 <= len(buyer) <= 80 and not CODE.fullmatch(buyer):
        db.execute("INSERT INTO sale_buyer VALUES(?,?,?)", (sale["id"], buyer, settled))
    db.execute("UPDATE allocation SET status='spent' WHERE sale_id=? AND status='held'", (sale["id"],))
    if sale["ticket"]:
        db.execute("UPDATE ticket SET status='used' WHERE key=?", (sale["ticket"],))
    earned = sale["base"] // 100
    if earned:
        db.execute("INSERT INTO lot VALUES(?,?,?,?,NULL)", (sale["id"], sale["owner"], earned, settled + WEEK))
        reallocate_debt(db, sale["owner"], now)
    audit(db, now, "settled_and_earned", sale["id"], order=data["order"], earned=earned)


def verify_settlement(market, sale, data, settled):
    order = data.get("order")
    payment = tx_hash(data.get("tx_hash"))
    if (not isinstance(order, str) or not order or not payment
            or data.get("shop") != sale["shop_url"] or data.get("unit") != sale["unit"]
            or data.get("item") != sale["sku"] or type(data.get("amount")) is not int
            or data["amount"] != sale["price"] or data.get("claim") != sale["grade"]
            or settled < sale["created"]):
        raise Unavailable("ledger entry does not match checkout")
    marker = "0x" + sale["digest"]
    payer = market.transaction(payment, None, sale["wallet"], int(sale["expected_wei"]), marker)
    if not payer:
        return None
    if int(sale["fee_wei"]) and not market.transaction(data.get("fee_tx_hash"), payer,
                                                       sale["fee_wallet"], int(sale["fee_wei"]), marker):
        return None
    return payer


def ledger_hash(row):
    prev = row.get("prev")
    if not isinstance(prev, str) or not re.fullmatch(r"[a-f0-9]{64}", prev):
        raise Unavailable("invalid ledger chain link")
    expected = hashlib.sha256(canonical({k: row[k] for k in ("seq", "ts", "kind", "round", "data", "prev")})).hexdigest()
    if row.get("hash") != expected:
        raise Unavailable("market ledger hash mismatch")
    return expected


def cursor_start(db, market):
    if one(db, "SELECT seq FROM cursor WHERE singleton=1"):
        return
    tail = market.get("/api/ledger", params={"after": -1})
    if not isinstance(tail, list):
        raise Unavailable("invalid ledger")
    head = whole(tail[-1]["seq"], 1) if tail else 0
    hashed = ledger_hash(tail[-1]) if tail else "0" * 64
    with atomic(db):
        db.execute("INSERT OR IGNORE INTO cursor VALUES(1,?,?)", (head, hashed))


def retire_unpaid_removed(db, unit, now):
    sale = one(db, "SELECT * FROM sale WHERE unit=? AND status IN ('issued','cancel_requested')", unit)
    if not sale:
        return
    db.execute("UPDATE sale SET status='missing' WHERE id=?", (sale["id"],))
    db.execute("UPDATE allocation SET status='released' WHERE sale_id=? AND status='held'", (sale["id"],))
    if sale["ticket"]:
        db.execute("UPDATE ticket SET status='waiting',ready=NULL WHERE key=? AND status='held'", (sale["ticket"],))
    reallocate_debt(db, sale["owner"], now)
    audit(db, now, "withdrawn_after_unit_removal", sale["id"], unit=unit)


def reconcile(db, market, now, pages=3):
    cursor_start(db, market)
    for _ in range(pages):
        after, previous = one(db, "SELECT seq,hash FROM cursor WHERE singleton=1")
        rows = market.get("/api/ledger", params={"after": after})
        if not isinstance(rows, list):
            raise Unavailable("invalid ledger page")
        for row in rows:
            seq = whole(row["seq"], 1)
            if seq != after + 1 or row.get("prev") != previous:
                raise Unavailable("market ledger is not contiguous")
            previous = ledger_hash(row)
            after = seq
            data = row["data"]
            kind = row["kind"]
            settled = number(row["ts"])
            candidate = None
            payer = None
            if kind == "settle" and row["round"] == 4 and isinstance(data.get("checkout_hash"), str):
                hashed = data["checkout_hash"]
                if re.fullmatch(r"[A-Za-z0-9_-]{43}", hashed):
                    candidate = one(db, "SELECT * FROM sale WHERE digest=?",
                                    base64.urlsafe_b64decode(hashed + "=").hex())
                    if candidate and candidate["status"] not in ("settled", "refunded"):
                        payer = verify_settlement(market, candidate, data, settled)
                        if not payer:
                            return False
            with atomic(db):
                current = one(db, "SELECT seq FROM cursor WHERE singleton=1")[0]
                if seq <= current:
                    continue
                if seq != current + 1:
                    raise Unavailable("ledger cursor changed unexpectedly")
                if candidate and payer:
                    sale = one(db, "SELECT * FROM sale WHERE id=?", candidate["id"])
                    if sale["status"] not in ("settled", "refunded"):
                        finalize_sale(db, sale, data, settled, payer, now)
                if kind == "expire" and data.get("shop") == SHOP:
                    for unit in data.get("units", []):
                        if one(db, "SELECT id FROM sale WHERE unit=?", unit):
                            db.execute("INSERT OR IGNORE INTO removal VALUES(?,?,'expired')", (unit, seq))
                            retire_unpaid_removed(db, unit, now)
                if kind == "settle" and isinstance(data.get("unit"), str):
                    if one(db, "SELECT id FROM sale WHERE unit=? AND shop_url=?", data["unit"], data.get("shop")):
                        db.execute("INSERT OR IGNORE INTO removal VALUES(?,?,'sold')", (data["unit"], seq))
                        retire_unpaid_removed(db, data["unit"], now)
                if kind == "broken":
                    sale = one(db, "SELECT * FROM sale WHERE market_order=?", data.get("order"))
                    if (sale and data.get("shop") == sale["shop_url"] and sale["settled"] <= settled
                            and data.get("unit") == sale["unit"] and data.get("refunded") == 0
                            and sale["broken"] is None):
                        hours = number(data.get("hours_after_sale"))
                        # Rounded market age 48.00 is ambiguous. In that case use
                        # the earlier independently sufficient observation only.
                        observed = settled
                        if hours < 48:
                            observed = min(observed, sale["settled"] + (hours + 0.005) * 3600)
                        db.execute("UPDATE sale SET broken=? WHERE id=?", (observed, sale["id"]))
                        audit(db, now, "market_breakage", sale["id"], reported=settled, hours=hours)
                db.execute("UPDATE cursor SET seq=?,hash=? WHERE singleton=1", (seq, previous))
        if len(rows) < 500:
            return True
    return False



def parse(text):
    if not isinstance(text, str) or len(text) > 1500:
        return "help", [], {}
    parts = text.split()
    if not parts:
        return "help", [], {}
    commands = {"구매": "buy", "재고": "inventory", "잔액": "balance", "대기": "wait",
                "결제확인": "paid", "취소": "cancel", "환불": "refund", "문의": "help", "프로필": "profile"}
    command = commands.get(parts[0])
    if not command:
        return "help", [], {}
    positional, options = [], {}
    index = 1
    while index < len(parts):
        part = parts[index]
        if part in ("권리", "대기", "수수료"):
            if part in options or index + 1 == len(parts) or not (tx_hash(parts[index + 1]) if part == "수수료" else key_of(parts[index + 1])):
                return "invalid", [], {}
            options[part] = parts[index + 1]
            index += 2
        else:
            positional.append(part)
            index += 1
    if command == "profile":
        if set(options) != {"권리"} or fact_change(positional) is None:
            return "invalid", [], {}
        return command, positional, options
    shape = {
        "buy": (1, {"권리", "대기"}, set()), "inventory": (0, set(), set()),
        "balance": (0, {"권리"}, {"권리"}), "wait": (1, {"권리"}, set()),
        "paid": (1, {"권리"}, {"권리"}), "cancel": (1, {"권리"}, {"권리"}),
        "refund": (1, {"권리", "수수료"}, {"권리"}), "help": (0, set(), set()),
    }
    size, allowed, required = shape[command]
    if len(positional) != size or not required.issubset(options) or not options.keys() <= allowed:
        return "invalid_buy" if command == "buy" else "invalid", [], {}
    return command, positional, options


def respond(reply, data=None):
    out = {"reply": reply, "state": "completed"}
    if data is not None:
        out["data"] = data
    return out


HELP = (
    "재고: 재고 · 결제: 구매 <SKU> [권리 <코드>] [대기 <코드>] · "
    "진행 확인: 대기 <코드> [권리 <코드>] · 잔액: 잔액 권리 <코드> · "
    "송금 확인: 결제확인 <송금해시> 권리 <코드> · 결제 중단 신고: 취소 <SKU> 권리 <코드> · "
    "환불 요청: 환불 <송금해시> 권리 <코드> [수수료 <해시>]. "
    "프로필에 직접 남길 정보 예: 프로필 가구 4 권리 <코드>. "
    "권리코드는 가진 사람이 사용할 수 있으니 비공개로 보관해 주세요."
)
DENIED = "권리코드 또는 요청 정보를 확인할 수 없습니다."
BUSY = "시장·체인 또는 정산 기록을 확인 중입니다. 같은 권리·대기코드를 유지한 채 다시 문의해 주세요."


def usable_units(units, now, sku=None):
    result = []
    for unit in units:
        if not isinstance(unit, dict):
            raise Unavailable("invalid inventory entry")
        expires = unit.get("expires_at")
        if (sku is not None and sku != unit.get("sku")) or (expires is not None and number(expires) <= now):
            continue
        if not isinstance(unit.get("unit"), str) or not SKU.fullmatch(unit["unit"]):
            continue
        if not isinstance(unit.get("sku"), str) or not SKU.fullmatch(unit["sku"]):
            continue
        if unit.get("grade") not in GRADES or not isinstance(unit.get("cert"), dict):
            continue
        whole(unit.get("cost"))
        whole(unit.get("list_price"), 1)
        result.append(unit)
    return result


def price_terms(unit, bps, network):
    # The live inventory list price and observed grade set the undiscounted offer.
    # Fees, stock cost and the new mileage liability set the minimum shop proceeds.
    base = unit["list_price"] * GRADES[unit["grade"]] // 100
    fee = lambda price: price * bps // 10000 + network // 2
    # Exact integer lower bound by monotone search, including the fee rounding.
    lo, hi = 1, base
    minimum_proceeds = max(1, unit["cost"] + base // 100)
    if base - fee(base) < minimum_proceeds:
        return None
    while lo < hi:
        mid = (lo + hi) // 2
        if mid - fee(mid) < minimum_proceeds:
            lo = mid + 1
        else:
            hi = mid
    return base, lo


def pinned(db, unit):
    return one(db, "SELECT id FROM sale WHERE unit=? LIMIT 1", unit) is not None


def wait_for_sku(db, market, sku, owner, now, discount):
    # Issue only against an existing reservation that actually blocks this SKU.
    if owner and one(db, """
        SELECT key FROM ticket WHERE sku=? AND owner=? AND status='waiting' AND expires>?
    """, sku, owner, now):
        return respond("이 상품에 유효한 대기권이 있습니다. 기존 대기코드를 사용해 주세요.")
    count = one(db, "SELECT count(*) FROM ticket WHERE sku=? AND status='waiting' AND expires>?", sku, now)[0]
    if count >= 32:
        return respond("이 상품의 대기 접수가 가득 찼습니다.")
    code = secrets.token_urlsafe(32)
    key = key_of(code)
    expires = now + WAIT
    voucher = {"type": "wait_voucher", "shop": SHOP, "shop_url": market.shop_url, "right_id": key,
               "sku": sku, "iat": now, "exp": expires, "discount": discount,
               "discount_bps": 100, "use_limit": 1, "terms": "same SKU and quoted discount"}
    signature = market.kit.sign(voucher, "shop")
    if not isinstance(signature, str):
        raise Unavailable("voucher signer did not answer")
    db.execute("INSERT INTO ticket VALUES(?,?,?,?,?,?,NULL,'waiting')", (key, sku, owner, now, expires, discount))
    audit(db, now, "delay_ticket_issued", key, sku=sku, expires=expires)
    owner_hint = " 기존 권리코드도 함께 보내 주세요." if owner else ""
    return respond(f"앞선 문의가 처리 중입니다. 발급 후 120초 이내 대기 {code} 로 다시 확인해 주세요."
                   f"{owner_hint} 같은 상품 구매 시 대기할인 {discount:,} credits가 적용됩니다. "
                   "재고가 준비되는 시각과 확보는 아직 확정되지 않았습니다.",
                   {"wait_voucher": voucher, "sig": signature})


def checkout_response(sale, code=None):
    credentials = f" 새 권리코드 {code} 를 비공개로 저장해 주세요." if code else ""
    return respond(
        f"{sale['sku']} {sale['grade']}급, 기준가 {sale['base']:,}, 최종 상품가 {sale['price']:,} credits. "
        f"대기할인 {sale['discount']:,}, 마일리지 사용 {sale['spent']:,} credits."
        f"{credentials} 정산·인도 확인 뒤 적립됩니다. "
        f"가게 송금 {sale['expected_wei']} wei, 시장 수수료 송금 {sale['fee_wei']} wei, 실제 가스 별도. "
        "견적을 받은 뒤 지연되면 송금하기 전에 같은 권리코드로 다시 확인해 주세요. "
        "판매자 귀책 미인도와 확인된 인도 후 48시간 내 초기 문제는 원 송금 주소에 "
        f"검증된 상품 송금·시장 수수료·가스 실지출(가스 합계 {sale['gas_cap_wei']} wei 한도)을 반환합니다.",
        {"checkout_jwt": sale["jwt"], "sku": sale["sku"], "price": sale["price"],
         "unit": sale["unit"], "grade": sale["grade"], "warranty_hours": 48},
    )


def checkout(db, market, sku, account_code, ticket_code, now, observation=None):
    if not SKU.fullmatch(sku):
        return respond("구매 명령은 상품 식별자만 적어 보내 주세요. 예시는 구매 G0026722f 입니다.")
    owner = key_of(account_code)
    ticket_key = key_of(ticket_code)
    # Keep authoritative market reads outside SQLite's write transaction.
    units = usable_units(market.inventory(), now, sku)
    credit_wei, bps, network, fee_wallet = market.chain()
    terms_by_unit = {u["unit"]: terms for u in units if (terms := price_terms(u, bps, network))}
    with atomic(db):
        if owner and not one(db, "SELECT key FROM account WHERE key=?", owner):
            return respond(DENIED)
        if owner:
            existing = one(db, """
                SELECT * FROM sale WHERE owner=? AND sku=?
                AND status IN ('issued','cancel_requested','paid')
                ORDER BY created DESC LIMIT 1
            """, owner, sku)
            if existing:
                if existing["status"] == "issued" and any(u["unit"] == existing["unit"]
                                                            and u["grade"] == existing["grade"] for u in units):
                    return checkout_response(existing)
                return respond("이전 결제가 확인 중입니다. 송금해시가 있으면 결제확인을 이용해 주세요.")
        ticket = None
        if ticket_key:
            ticket = one(db, "SELECT * FROM ticket WHERE key=?", ticket_key)
            if (not ticket or ticket["sku"] != sku or ticket["status"] != "waiting"
                    or ticket["expires"] <= now or (ticket["owner"] and ticket["owner"] != owner)):
                return respond(DENIED)
        if not units:
            return respond("현재 판매 가능한 재고가 없습니다. 기존 대기권은 기록된 기간까지 유지됩니다.")
        eligible = [unit for unit in units if unit["unit"] in terms_by_unit]
        if not eligible:
            return respond("현재 등급에서 원가와 수수료를 충당하는 판매가를 제시할 수 없습니다.")
        available = [unit for unit in eligible if not pinned(db, unit["unit"])]
        proposed = terms_by_unit[eligible[0]["unit"]][0] // 100
        if not available:
            if ticket:
                return respond("현재 재고의 앞선 결제를 확인 중입니다. 대기코드를 유지해 주세요.")
            return wait_for_sku(db, market, sku, owner, now, proposed)
        front = one(db, """
            SELECT key FROM ticket WHERE sku=? AND status='waiting' AND expires>?
            ORDER BY created,rowid LIMIT 1
        """, sku, now)
        if front and front["key"] != ticket_key:
            return wait_for_sku(db, market, sku, owner, now, proposed)
        offers = [(u, terms_by_unit[u["unit"]]) for u in available]
        if ticket:
            offers = [(u, terms) for u, terms in offers if terms[0] // 100 == ticket["discount"]]
            if not offers:
                return respond("서명된 대기할인과 현재 상품의 등급·기준가가 달라 같은 조건의 재고를 기다리는 중입니다.")
        unit, (base, floor) = offers[0]
        discount = base // 100 if ticket else 0
        if base - discount < floor:
            return respond("원가와 수수료 때문에 현재 재고에는 이 대기할인을 적용할 수 없습니다.")
        new_code = None
        if not owner:
            new_code = secrets.token_urlsafe(32)
            owner = key_of(new_code)
            db.execute("INSERT INTO account VALUES(?,?)", (owner, now))
            record_visit(db, owner, now, observation)
        reallocate_debt(db, owner, now)
        spent = min(balance(db, owner, now), base - discount - floor)
        price = base - discount - spent
        sale_id = "r4-" + secrets.token_hex(16)
        payload = {"id": sale_id, "shop": SHOP, "shop_url": market.shop_url, "item": sku, "price": price,
                   "task": sale_id, "currency": "credits", "iat": int(now), "unit": unit["unit"],
                   "cert": unit["cert"], "claim": unit["grade"], "warranty_hours": 48}
        jwt = market.kit.sign_jwt(payload, "shop")
        if not isinstance(jwt, str) or jwt.count(".") != 2:
            raise Unavailable("signer did not return a checkout")
        fee = price * bps // 10000
        db.execute("""
            INSERT INTO sale(id,owner,unit,sku,base,cost,price,discount,spent,ticket,shop_url,wallet,created,
                             digest,jwt,expected_wei,fee_wei,gas_cap_wei,fee_wallet,grade,status)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'issued')
        """, (sale_id, owner, unit["unit"], sku, base, unit["cost"], price, discount, spent, ticket_key,
              market.shop_url, market.wallet, now, digest(jwt), jwt,
              str((price - fee - network // 2) * credit_wei), str(2 * fee * credit_wei),
              str(network * credit_wei), fee_wallet, unit["grade"]))
        category = category_key(unit.get("category"))
        if category:
            db.execute("INSERT INTO sale_category VALUES(?,?)", (sale_id, category))
        reserve(db, sale_id, owner, spent, now)
        if ticket:
            db.execute("UPDATE ticket SET status='held', owner=? WHERE key=?", (owner, ticket_key))
        audit(db, now, "checkout_issued", sale_id, unit=unit["unit"], spent=spent, discount=discount)
        return checkout_response(one(db, "SELECT * FROM sale WHERE id=?", sale_id), new_code)


def match_payment(db, market, owner, incoming):
    if not incoming or not owner:
        return None, None
    tx = market.rpc("eth_getTransactionByHash", incoming)
    marker = tx_hash(tx.get("input")) if isinstance(tx, dict) else None
    if not marker:
        return None, None
    sale = one(db, "SELECT * FROM sale WHERE digest=? AND owner=?", marker[2:], owner)
    if not sale or (sale["payment"] and sale["payment"] != incoming):
        return None, None
    payer = market.transaction(incoming, sale["payer"], sale["wallet"], int(sale["expected_wei"]), marker)
    return (sale, payer) if payer else (None, None)


def no_delivery(db, market, sale):
    # An on-chain payment alone cannot prove non-delivery. Only a complete
    # ledger check plus irreversible removal of the unit makes this safe.
    if not one(db, "SELECT unit FROM removal WHERE unit=?", sale["unit"]):
        return False
    if any(u.get("unit") == sale["unit"] for u in market.inventory()):
        return False
    return not one(db, "SELECT market_order FROM sale WHERE id=? AND market_order IS NOT NULL", sale["id"])


def refund_cost(market, sale, incoming, payer, fee_payment):
    marker = "0x" + sale["digest"]
    transfer_wei = int(sale["expected_wei"])
    verified = market.transaction(incoming, payer, sale["wallet"], transfer_wei, marker, include_cost=True)
    if not verified:
        raise Unavailable("invalid original payment")
    _, gas_wei = verified
    fee_wei = 0
    if fee_payment:
        fee_payment = tx_hash(fee_payment)
        fee_wei = int(sale["fee_wei"])
        fee = market.transaction(fee_payment, payer, sale["fee_wallet"], fee_wei, marker, include_cost=True)
        if not fee_wei or not fee:
            raise Unavailable("invalid market fee payment")
        gas_wei += fee[1]
    return transfer_wei, fee_wei, min(gas_wei, int(sale["gas_cap_wei"]))


def payment_request(db, market, command, owner, incoming, now, fee_payment=None):
    sale, payer = match_payment(db, market, owner, incoming)
    if not sale:
        return respond(DENIED)
    absent = command == "refund" and sale["status"] not in ("settled", "refunded") and no_delivery(db, market, sale)
    costs = None
    if command == "refund" and (absent or sale["status"] == "settled"):
        fee_payment = sale["fee_payment"] or fee_payment
        costs = refund_cost(market, sale, incoming, payer, fee_payment)
    with atomic(db):
        sale = one(db, "SELECT * FROM sale WHERE id=?", sale["id"])
        if sale["payment"] and (sale["payment"] != incoming or sale["payer"] != payer):
            return respond(DENIED)
        if sale["status"] in ("issued", "cancel_requested", "missing"):
            db.execute("UPDATE sale SET status='paid', payment=?, payer=? WHERE id=?", (incoming, payer, sale["id"]))
            audit(db, now, "transfer_seen", sale["id"], payment=incoming)
        if command == "paid":
            if sale["status"] == "refunded":
                return respond("환불 확인이 완료되었습니다.")
            if sale["status"] == "settled":
                return respond("시장 정산과 인도가 확인되었습니다. 잔액 권리 <코드> 로 확인할 수 있습니다.")
            return respond("송금은 확인됐습니다. 시장 정산과 인도를 확인하는 중입니다.")
        pending = one(db, "SELECT status,outgoing FROM refund WHERE sale_id=?", sale["id"])
        if pending:
            return refund_reply(pending)
        if sale["status"] == "settled":
            if sale["broken"] is None or not 0 <= sale["broken"] - sale["settled"] <= WARRANTY:
                return respond("시장 기록에서 인도 후 48시간 내 초기 문제를 확인하지 못했습니다.")
            reason = "early_market_breakage"
        elif absent:
            reason = "paid_no_delivery"
        else:
            return respond("송금은 확인됐습니다. 같은 결제가 아직 인도될 수 있어 정산 또는 인도 불가 확인을 기다립니다.")
        if not costs or (sale["fee_payment"] and sale["fee_payment"] != fee_payment):
            return respond(BUSY)
        transfer, fee, gas = costs
        marker = "0x" + secrets.token_hex(32)
        db.execute("""
            INSERT INTO refund(sale_id,incoming,payer,wei,marker,reason,transfer_wei,fee_wei,gas_wei,
                               fee_payment,status,requested)
            VALUES(?,?,?,?,?,?,?,?,?,?,'requested',?)
        """, (sale["id"], incoming, payer, str(transfer + fee + gas), marker, reason,
              str(transfer), str(fee), str(gas), fee_payment, now))
        audit(db, now, "refund_requested", sale["id"], reason=reason, incoming=incoming)
        return respond(f"환불 검토를 접수했습니다. 검증된 비용: 상품 송금 {transfer} wei, 시장 수수료 {fee} wei, "
                       f"가스 {gas} wei. 승인·확인 뒤 원 송금 주소로 반환합니다.")


def refund_reply(record):
    if record["status"] == "refunded":
        return respond("원 송금 주소로 환불이 확인되었습니다. 환불 송금해시 " + record["outgoing"])
    return respond("환불이 검토 또는 송금 확인 중입니다. 같은 송금을 반복하지 않습니다.")


def dispatch(db, market, text, now, observation=None):
    command, args, options = parse(text)
    if command == "help":
        return respond(HELP)
    if command == "invalid":
        return respond(DENIED)
    if command == "invalid_buy":
        return respond("구매 명령은 품목 이후에 설명을 붙이지 않고 구매 <SKU> [권리 <코드>] [대기 <코드>] 형식으로 보내 주세요.")
    owner = key_of(options.get("권리"))
    if command == "inventory":
        rows = usable_units(market.inventory(), now)
        return respond("판매 문의 가능한 SKU: " + (", ".join(dict.fromkeys(r["sku"] for r in rows)) or "없음"))
    if owner and not one(db, "SELECT key FROM account WHERE key=?", owner):
        return respond(DENIED)
    if owner:
        with atomic(db):
            record_visit(db, owner, now, observation)
            if command == "profile":
                record_fact(db, owner, fact_change(args), now, "customer_a2a_self_report")
                return respond("공유하신 항목을 기록했습니다. 같은 항목을 다시 보내면 정정됩니다.")
    if command == "wait":
        ticket = one(db, "SELECT * FROM ticket WHERE key=?", key_of(args[0]))
        if not ticket or (ticket["owner"] and ticket["owner"] != owner) or ticket["status"] != "waiting":
            return respond(DENIED)
        return checkout(db, market, ticket["sku"], options.get("권리"), args[0], now, observation) if reconcile(db, market, now) else respond(BUSY)
    if command in ("paid", "refund") and not tx_hash(args[0]):
        return respond(DENIED)
    if not reconcile(db, market, now):
        return respond(BUSY)
    if command == "buy":
        return checkout(db, market, args[0], options.get("권리"), options.get("대기"), now, observation)
    if command == "balance":
        with atomic(db):
            debt = reallocate_debt(db, owner, now)
            return respond(f"사용 가능한 마일리지 {balance(db, owner, now):,} credits. "
                           f"다음 적립에서 상계할 금액 {debt:,} credits.")
    if command == "cancel":
        with atomic(db):
            sale = one(db, """
                SELECT * FROM sale WHERE owner=? AND sku=? AND status IN ('issued','cancel_requested')
                ORDER BY created DESC LIMIT 1
            """, owner, args[0])
            if not sale:
                return respond(DENIED)
            if sale["status"] == "issued":
                db.execute("UPDATE sale SET status='cancel_requested' WHERE id=?", (sale["id"],))
                audit(db, now, "checkout_cancel_requested", sale["id"])
        return respond("결제 중단 의사를 기록했습니다. 발급된 결제권을 시장에서 회수할 수 없으니 송금하지 마세요. "
                       "재고와 혜택 예약은 이미 시작된 결제까지 확인한 뒤 처리합니다.")
    return payment_request(db, market, command, owner, tx_hash(args[0]), now, options.get("수수료"))


def process_queue(db, market, now):
    if not one(db, "SELECT key FROM ticket WHERE status='waiting' AND expires>?", now):
        return 0
    units = usable_units(market.inventory(), now)
    _, bps, network, _ = market.chain()
    ready = 0
    with atomic(db):
        supply = {}
        for unit in units:
            terms = price_terms(unit, bps, network)
            if terms and not pinned(db, unit["unit"]):
                base, floor = terms
                discount = base // 100
                if base - discount >= floor:
                    sku_supply = supply.setdefault(unit["sku"], [])
                    sku_supply.append(discount)
        queue = db.execute("""
            SELECT * FROM ticket WHERE status='waiting' AND expires>? ORDER BY created,rowid
        """, (now,)).fetchall()
        blocked = set()
        for ticket in queue:
            stock = supply.get(ticket["sku"], [])
            is_ready = ticket["sku"] not in blocked and ticket["discount"] in stock
            if is_ready:
                stock.remove(ticket["discount"])
                ready += 1
                if ticket["ready"] is None:
                    audit(db, now, "queue_ready", ticket["key"], sku=ticket["sku"])
            else:
                blocked.add(ticket["sku"])
            db.execute("UPDATE ticket SET ready=? WHERE key=?",
                       ((ticket["ready"] or now) if is_ready else None, ticket["key"]))
    return ready


def run(args, kit):
    # A2A data, claimed name and task history are deliberately ignored. Even an
    # internal model tool call can only enter this same public text interface.
    text = args.get("text")
    if parse(text)[0] == "help":
        return respond(HELP)
    db = None
    try:
        market = Market(kit)
        db = open_db(DB, market.wallet)
        return dispatch(db, market, text, time.time(), args.get("task_id"))
    except (Unavailable, httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError, sqlite3.Error, OSError):
        # Returning a reply prevents the official kit from forwarding bearer codes
        # to the reasoning model as deferred conversation text.
        return respond(BUSY)
    finally:
        if db is not None:
            db.close()

