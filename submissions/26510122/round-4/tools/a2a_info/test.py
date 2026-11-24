"""Network-free contract fixture. Authored by OpenAI Codex GPT-6.2 Sol."""
from base64 import b64encode, urlsafe_b64encode, urlsafe_b64decode
import hashlib
import json
from pathlib import Path
import re
import socket
from unittest.mock import patch

import httpx
from eth_account import Account
from eth_account.messages import encode_defunct


MOCK_MARKET = "https://market.ourolabs.ai"
MOCK_RPC = "https://rpc-testnet.maroo.io"
MOCK_SHOP = "https://outseop-r4.example.invalid"
COIN = 10**15
MOCK_SKU = "G0026722f"
BUYER = "0x" + "2" * 40
MARKET_WALLET = "0x" + "3" * 40


def b64url(value):
    return urlsafe_b64encode(value).rstrip(b"=").decode()


class FakeKit:
    name = "outseop-r4"
    market = MOCK_MARKET
    shop_url = MOCK_SHOP

    def __init__(self, signer=None):
        self.signer = signer
        self.key = Account.create() if signer is None else None

    def token(self, role):
        assert role == "shop"
        return "fixture-test-only"

    def address(self, role):
        assert role == "shop"
        return self.signer.address(role) if self.signer else self.key.address

    def sign(self, obj, role):
        if self.signer:
            return self.signer.sign(obj, role)
        raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        return b64encode(self.key.sign_message(encode_defunct(primitive=raw)).signature).decode()

    def sign_jwt(self, payload, role):
        if self.signer:
            return self.signer.sign_jwt(payload, role)
        header = b64url(b'{"alg":"EIP191","typ":"JWT"}')
        body = b64url(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
        prefix = f"{header}.{body}"
        signature = self.key.sign_message(encode_defunct(text=prefix)).signature
        return f"{prefix}.{b64url(signature)}"


class Fixture:
    def __init__(self, root, run=None, signer=None):
        if run is None:
            from dispatcher import run
        self.run = run
        self.src = run.__globals__
        self.db_path = Path(root) / "fixture.sqlite3"
        self.kit = FakeKit(signer)
        self.now = 1795560000.0
        self.units = []
        self.entries = []
        self.txs = {}
        self.receipts = {}
        self.head = 47
        self.counter = 0
        self.sends = 0
        self.fail_inventory = False
        self.fail_ledger = False

    def advance(self, seconds):
        self.now += seconds

    def add_unit(self, unit_id=None, *, sku=MOCK_SKU, price=4500, cost=1200, grade="A"):
        unit_id = unit_id or f"u-fixture-{len(self.units) + len(self.entries)}"
        unit = {"unit": unit_id, "sku": sku, "list_price": price, "cost": cost, "grade": grade,
                "expires_at": None, "cert": {"cert": {"unit": unit_id, "sku": sku, "grade": grade}, "sig": "fixture"}}
        self.units.append(unit)
        return unit

    def entry(self, kind, data, *, at=None):
        value = {"seq": len(self.entries) + 1, "kind": kind, "ts": self.now if at is None else at,
                 "round": 4, "data": data, "prev": self.entries[-1]["hash"] if self.entries else "0" * 64}
        value["hash"] = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                                   ensure_ascii=False).encode()).hexdigest()
        self.entries.append(value)
        return value

    def get(self, url, *, params=None, headers=None, **_):
        assert url.startswith(MOCK_MARKET + "/"), url
        path = url.removeprefix(MOCK_MARKET)
        if path == "/api/ledger":
            after = params["after"]
            rows = self.entries[after:] if after >= 0 else self.entries[after:]
            return self.response(url, rows[:500], code=503 if self.fail_ledger else 200)
        if path == "/api/inventory":
            assert headers == {"authorization": "Bearer fixture-test-only"}
            return self.response(url, {"round": 4, "wallet": self.kit.address("shop"), "units": self.units},
                                 code=503 if self.fail_inventory else 200)
        if path == "/api/chain":
            return self.response(url, {"rpc": MOCK_RPC, "chain_id": 450815, "credit_wei": COIN, "market_address": MARKET_WALLET,
                                       "market_fee_bps": 100, "network_fee_credits": 420, "from_round": 4, "customers_on_chain": True})
        raise AssertionError("unexpected market GET " + url)

    def post(self, url, *, json, **_):
        assert url == MOCK_RPC, url
        method, params = json["method"], json["params"]
        if method == "eth_getTransactionByHash":
            data = self.txs.get(params[0])
        elif method == "eth_getTransactionReceipt":
            data = self.receipts.get(params[0])
        elif method == "eth_blockNumber":
            data = hex(self.head)
        elif method == "eth_getBlockByNumber":
            data = {"transactions": [tx for tx in self.txs.values() if tx.get("blockNumber") == params[0]]}
        else:
            raise AssertionError("unexpected RPC method " + method)
        return self.response(url, {"jsonrpc": "2.0", "id": 1, "result": data})

    @staticmethod
    def response(url, data, code=200):
        return httpx.Response(code, json=data, request=httpx.Request("GET", url))

    def payments(self, jwt, *, buyer=BUYER):
        payload = self.payload(jwt)
        marker = "0x" + hashlib.sha256(jwt.encode()).hexdigest()
        price = payload["price"]
        market_fee = price // 100
        incoming = self.transfer(buyer, self.kit.address("shop"), (price - market_fee - 210) * COIN, marker)
        fee = self.transfer(buyer, MARKET_WALLET, 2 * market_fee * COIN, marker) if market_fee else None
        return incoming, fee

    def settle(self, checkout, *, buyer=BUYER, order=None, payment=None, fee=None, at=None):
        jwt = checkout["data"]["checkout_jwt"] if isinstance(checkout, dict) else checkout
        if payment is None:
            payment, fee = self.payments(jwt, buyer=buyer)
        payload = self.payload(jwt)
        self.units[:] = [unit for unit in self.units if unit["unit"] != payload["unit"]]
        settlement = self.entry("settle", {"order": order or f"o-{len(self.entries)+1}", "shop": payload["shop_url"],
                                           "buyer": "fixture-buyer", "unit": payload["unit"], "item": payload["item"],
                                           "amount": payload["price"], "claim": payload["claim"], "grade": payload["claim"],
                                           "checkout_hash": b64url(hashlib.sha256(jwt.encode()).digest()),
                                           "warranty_hours": 48, "tx_hash": payment, "fee_tx_hash": fee}, at=at)
        return settlement["data"]

    def breakage(self, settlement, hours=1):
        return self.entry("broken", {"order": settlement["order"], "shop": settlement["shop"],
                                     "unit": settlement["unit"], "hours_after_sale": hours, "refunded": 0})

    def expire(self, unit):
        self.units[:] = [u for u in self.units if u["unit"] != unit["unit"]]
        self.entry("expire", {"shop": self.kit.name, "units": [unit["unit"]]})

    def transfer(self, sender, to, wei, marker, *, status=1, block=42, gas=22000):
        self.counter += 1
        tx_hash = f"0x{self.counter:064x}"
        block_hash = f"0x{block:064x}"
        self.txs[tx_hash] = {"hash": tx_hash, "from": sender, "to": to, "input": marker, "value": hex(wei),
                             "blockHash": block_hash, "blockNumber": hex(block)}
        self.receipts[tx_hash] = {"transactionHash": tx_hash, "blockHash": block_hash, "blockNumber": hex(block),
                                  "status": hex(status), "gasUsed": hex(gas), "effectiveGasPrice": hex(100)}
        return tx_hash

    def pay(self, to, wei, marker):
        self.sends += 1
        self.head += 3
        return self.transfer(self.kit.address("shop"), to, wei, marker, block=self.head - 2)

    def patches(self):
        from contextlib import ExitStack
        stack = ExitStack()
        stack.enter_context(patch.object(httpx, "get", self.get))
        stack.enter_context(patch.object(httpx, "post", self.post))
        stack.enter_context(patch.dict(self.src, {"DB": self.db_path,
                                                 "time": type("FixtureClock", (), {"time": lambda _: self.now})()}))
        return stack

    def call(self, args):
        with self.patches():
            return self.run(args, self.kit)

    def sync(self):
        with self.patches():
            db = self.open()
            try:
                market = self.market()
                current = self.src["reconcile"](db, market, self.now)
                return {"current": current, "queue_ready": self.src["process_queue"](db, market, self.now) if current else 0}
            finally:
                db.close()

    def open(self):
        return self.src["open_db"](self.db_path, self.kit.address("shop").lower())

    def market(self):
        return self.src["Market"](self.kit)

    @staticmethod
    def payload(jwt):
        return json.loads(urlsafe_b64decode(jwt.split(".")[1] + "==="))

    @staticmethod
    def right(response, word="권리코드"):
        return re.search(rf"{word} ([A-Za-z0-9_-]{{43}})", response["reply"])[1]



def test(run, kit):
    from base64 import b64decode, urlsafe_b64decode
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path
    from tempfile import mkdtemp
    from eth_account import Account
    from eth_account.messages import encode_defunct

    base = Path("state/r4-benefits/tests")
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    f = Fixture(Path(mkdtemp(dir=base)), run, kit)
    assert "결제" in f.call({"op": "refund", "approve": True})["reply"]
    assert "없습니다" in f.call({"text": "구매 " + MOCK_SKU})["reply"]
    f.add_unit("u-first", grade="B", price=5000)
    with f.patches(), ThreadPoolExecutor(max_workers=8) as threads:
        replies = list(threads.map(lambda _: run({"text": "구매 " + MOCK_SKU}, f.kit), range(8)))
    checkouts = [r for r in replies if "checkout_jwt" in r.get("data", {})]
    assert len(checkouts) == 1, replies
    first, = checkouts
    first_owner = f.right(first)
    jwt = first["data"]["checkout_jwt"]
    assert Fixture.payload(jwt)["claim"] == "B"
    assert Fixture.payload(jwt)["price"] == 4500
    header, body, sig = jwt.split(".")
    assert Account.recover_message(encode_defunct(text=header + "." + body),
                                   signature=urlsafe_b64decode(sig + "===")).lower() == f.kit.address("shop").lower()
    tickets = [r for r in replies if "wait_voucher" in r.get("data", {})]
    assert len(tickets) == 7
    first_ticket = tickets[0]["data"]
    voucher = first_ticket["wait_voucher"]
    assert voucher["type"] == "wait_voucher" and voucher["discount"] == 45 and voucher["use_limit"] == 1
    assert voucher["exp"] - voucher["iat"] == 120
    assert Account.recover_message(encode_defunct(primitive=run.__globals__["canonical"](voucher)),
                                   signature=b64decode(first_ticket["sig"])).lower() == f.kit.address("shop").lower()
    assert "0 credits" in f.call({"text": "잔액 권리 " + first_owner})["reply"]
    f.advance(120)
    assert "확인할 수 없습니다" in f.call({"text": "대기 " + f.right(tickets[0], "대기")})["reply"]
    assert "중단" in f.call({"text": f"취소 {MOCK_SKU} 권리 {first_owner}"})["reply"]
    db = f.open()
    try:
        assert db.execute("SELECT status FROM sale").fetchone()[0] == "cancel_requested"
    finally:
        db.close()
    f.advance(601)
    assert "wait_voucher" in f.call({"text": "구매 " + MOCK_SKU})["data"]
    settled = f.settle(first)
    assert f.sync()["current"]
    assert f.sync()["current"]
    assert "45 credits" in f.call({"text": "잔액 권리 " + first_owner, "task_id": "new"})["reply"]
    assert "확인할 수 없습니다" in f.call({"text": "잔액 권리 " + "a"*43, "claimed_from": "fixture-buyer",
                                           "data": {"tx": settled["tx_hash"]}})["reply"]
    assert "확인할 수 없습니다" in f.call({"text": "환불 " + settled["tx_hash"], "claimed_from": "fixture-buyer"})["reply"]
    f.advance(121)
    f.add_unit("u-next")
    next_checkout = f.call({"text": f"구매 {MOCK_SKU} 권리 {first_owner}"})
    assert next_checkout["data"]["price"] == 4455
    assert f.call({"text": f"구매 {MOCK_SKU} 권리 {first_owner}"}) == next_checkout
    db = f.open()
    try:
        assert db.execute("SELECT count(*) FROM lot").fetchone()[0] == 1
        held = db.execute("SELECT amount FROM allocation WHERE status='held'").fetchone()
        assert held[0] == 45
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        db.close()
    return {"authorship": "OpenAI Codex GPT-6.2 Sol",
            "asserted": "single concurrent checkout; signed voucher/JWT; deadline; pinned cancellation; settlement; bearer authentication; next-sale mileage"}

