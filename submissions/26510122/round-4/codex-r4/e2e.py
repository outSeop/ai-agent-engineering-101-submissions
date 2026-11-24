"""Actual published customer methods and official A2A ASGI app, without network I/O."""
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from starlette.testclient import TestClient

from fixture import MOCK_MARKET, MOCK_SHOP, MOCK_SKU, COIN, MARKET_WALLET, Fixture, b64url
import refund_admin


SOURCE = Path(__file__).resolve().parent
OPERATOR = Path(os.environ.get("R4_OPERATOR_DIR", SOURCE.parents[1] / "r4-operator"))
sys.path.insert(0, str(OPERATOR / "kit"))
import agent_kit
import maroo


def customer_module():
    # These ancillary customer modules are not in the published session capture.
    # The test uses the real Visit.talk, buy, short_of, order, settle and JWT helpers.
    shims = {name: ModuleType(name) for name in ("persona_mind", "persona_world", "react")}
    spec = importlib.util.spec_from_file_location("official_customer_capture", Path(os.environ.get("R4_CUSTOMER_CAPTURE", OPERATOR / "validation/captures/customer.py")))
    with patch.dict(sys.modules, shims):
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


class A2ATools:
    def __init__(self, fixture):
        self.fixture = fixture
        self.ctx = {"addresses": {"shop": fixture.kit.address("shop")}, "tokens": {"shop": "test-only"}}

    def handler(self, kind):
        assert kind == "a2a"
        return "a2a_info"

    def call(self, name, args):
        assert name == "a2a_info"
        return {"ok": True, "result": self.fixture.call(args)}


class NoDefer:
    def deliver(self, _):
        raise AssertionError("customer command fell through to the reasoning model")


class A2AMarketClient:
    def __init__(self, fixture, buyer):
        self.f = fixture
        self.buyer = buyer
        self.shop = {"name": "outseop-r4", "pubkey": fixture.kit.address("shop"), "url": MOCK_SHOP}
        app = agent_kit.agent_app(fixture.db_path.parent, self.shop["name"], NoDefer(), A2ATools(fixture), [MOCK_SHOP])
        self.a2a = TestClient(app, base_url=MOCK_SHOP)
        self.orders = {}

    def get(self, url, **kwargs):
        if url == MOCK_MARKET + "/api/agents":
            return self.f.response(url, {"agents": [dict(self.shop, card=MOCK_SHOP + "/.well-known/agent-card.json")]})
        if url == MOCK_MARKET + "/api/shops":
            return self.f.response(url, {"shops": [self.shop]})
        if url == MOCK_MARKET + "/api/stats":
            return self.f.response(url, {"round": 4})
        if url == MOCK_SHOP + "/.well-known/agent-card.json":
            return self.a2a.get(url)
        return self.f.get(url, **kwargs)

    def post(self, url, *, json, headers=None, **kwargs):
        if url == MOCK_SHOP + "/":
            assert headers == {"A2A-Version": "1.0"}
            assert len(json["params"]["message"]["parts"]) == 1
            assert set(json["params"]["message"]["parts"][0]) == {"text"}
            return self.a2a.post(url, json=json, headers=headers)
        if url == MOCK_MARKET + "/api/orders":
            order = "o-customer-" + str(len(self.orders) + 1)
            mandate = {kind: {"mandate": {"order": order, "kind": kind}} for kind in ("checkout", "payment")}
            current = {"order": order, "mandates": mandate, "chain": self.f.get(MOCK_MARKET + "/api/chain").json()}
            self.orders[order] = (current, json)
            return self.f.response(url, current)
        if url == MOCK_MARKET + "/api/settle":
            return self.settle(url, json)
        raise AssertionError("unexpected customer POST " + url)

    def settle(self, url, body):
        order_id = body["order"]
        order, bid = self.orders[order_id]
        jwt = body["checkout_jwt"]
        payload = Fixture.payload(jwt)
        assert payload["item"] == bid["sku"] and payload["price"] == bid["budget"]
        assert payload["shop"] == self.shop["name"] and payload["shop_url"] == MOCK_SHOP
        assert payload["currency"] == "credits" and payload["warranty_hours"] == 48
        unit = next(u for u in self.f.units if u["unit"] == payload["unit"])
        assert unit["cert"] == payload["cert"] and unit["grade"] == payload["claim"]
        for kind in ("checkout", "payment"):
            signed = body[kind + "_mandate"]
            mandate = signed["mandate"]
            assert maroo.verify_bytes(self.buyer.address, base64.b64decode(signed["sig"]), agent_kit.mk.canon(mandate))
            assert mandate["checkout_hash"] == b64url(hashlib.sha256(jwt.encode()).digest())
            assert mandate["order"] == order_id
            assert mandate["open_mandate"] == hashlib.sha256(agent_kit.mk.canon(order["mandates"][kind]["mandate"])).hexdigest()
        pm = body["payment_mandate"]["mandate"]
        expected = {"currency": "credits", "amount": payload["price"], "payee": MOCK_SHOP}
        assert all(pm[k] == v for k, v in expected.items())
        marker = "0x" + hashlib.sha256(jwt.encode()).hexdigest()
        for txhash, recipient, amount in ((pm["tx_hash"], self.f.kit.address("shop"), payload["price"] - payload["price"]//100 - 210),
                                          (pm["fee_tx_hash"], MARKET_WALLET, 2 * (payload["price"]//100))):
            tx = self.f.txs[txhash]
            assert tx["from"] == self.buyer.address and tx["to"] == recipient
            assert tx["input"] == marker and int(tx["value"], 16) == amount * COIN
        settlement = self.f.settle(jwt, buyer=self.buyer.address, order=order_id, payment=pm["tx_hash"], fee=pm["fee_tx_hash"])
        return self.f.response(url, {"settled": True, "mandate_receipt": dict(settlement, ledger=len(self.f.entries))})


def no_network(*_args, **_kwargs):
    raise AssertionError("an external socket is forbidden during tests")


def e2e(root):
    customer = customer_module()
    f = Fixture(root)
    root.mkdir(parents=True, exist_ok=True)
    buyer = maroo.Wallet.generate()
    client = A2AMarketClient(f, buyer)
    visitor = object.__new__(customer.Visit)
    visitor.c, visitor.key, visitor.d, visitor.base = client, buyer, root, MOCK_MARKET
    visitor.me = {"name": "buyer-not-authenticated-by-name", "token": "fake-customer"}
    visitor.mind = SimpleNamespace(event=lambda *_a, **_k: None, fact=lambda *_a, **_k: None)
    visitor.tasks, visitor.done, visitor.life = {}, {"heard": 0, "bought": []}, None
    f.add_unit("u-initial")
    def fake_pay(key, to, wei, marker):
        assert key is buyer
        return f.transfer(key.address, to, wei, "0x" + marker.hex())
    with patch.object(maroo, "pay", fake_pay), patch.object(maroo, "balance", lambda _address: 99_000 * COIN), \
         patch.object(socket, "getaddrinfo", no_network), patch.object(socket.socket, "connect", no_network):
        first = visitor.talk({"agent": "outseop-r4", "text": f"구매 {MOCK_SKU}"})
        assert "data" in first, first
        first_right = f.right({"reply": first["agent_says"]})
        assert "checkout_jwt" in first["data"][0], first
        assert visitor.buy({"agent": "outseop-r4"})["paid"] == 4500
        settlement_a = f.entries[-1]["data"]
        assert f.sync() == {"current": True, "queue_ready": 0}
        assert "45 credits" in visitor.talk({"agent": "outseop-r4", "text": f"잔액 권리 {first_right}",
                                             "new_conversation": True})["agent_says"]
        f.add_unit("u-blocker")
        blocker = f.call({"text": f"구매 {MOCK_SKU}"})
        wait = visitor.talk({"agent": "outseop-r4", "text": f"구매 {MOCK_SKU} 권리 {first_right}"})
        wait_right = f.right({"reply": wait["agent_says"]}, "대기")
        assert wait["data"][0]["wait_voucher"]["discount"] == 45
        assert f.sync()["queue_ready"] == 0
        f.settle(blocker)
        f.add_unit("u-followup")
        f.advance(1)
        assert f.sync()["queue_ready"] == 1
        second = visitor.talk({"agent": "outseop-r4", "text": f"대기 {wait_right} 권리 {first_right}",
                               "new_conversation": True})
        assert second["data"][0]["price"] == 4410, second
        assert visitor.buy({"agent": "outseop-r4"})["paid"] == 4410
        settlement_b = f.entries[-1]["data"]
        assert f.sync()["current"]
        f.advance(3600)
        f.breakage(settlement_a)
        claim = visitor.talk({"agent": "outseop-r4", "text": f"환불 {settlement_a['tx_hash']} 권리 {first_right}"})
        assert "검토를 접수" in claim["agent_says"], claim
        with f.patches():
            db = f.open()
            try:
                record = refund_admin.list_requests(db)[0]
                result = refund_admin.send(db, f.market(), record["sale_id"], f.pay, f.now)
                assert result["status"] == "refunded"
                sent = f.txs[result["outgoing"]]
                assert sent["to"] == buyer.address.lower()
                assert int(sent["value"], 16) == (4500 + 45 - 210) * COIN + 4_400_000
                assert "0 credits" in f.run({"text": f"잔액 권리 {first_right}"}, f.kit)["reply"]
                assert db.execute("SELECT count(*) FROM lot").fetchone()[0] == 3
                assert db.execute("SELECT amount FROM allocation WHERE status='offset'").fetchone()[0] == 45
                assert db.execute("PRAGMA foreign_key_check").fetchall() == []
            finally:
                db.close()
        again = visitor.talk({"agent": "outseop-r4", "text": f"환불 {settlement_a['tx_hash']} 권리 {first_right}"})
        assert "환불이 확인" in again["agent_says"] and f.sends == 1
        assert settlement_b["tx_hash"] != settlement_a["tx_hash"]
        assert len(visitor.done["bought"]) == 2
    return {"first_price": 4500, "next_with_wait_and_mileage": 4410, "verified_mock_refunds": f.sends,
            "customer_method": "captured Visit.talk and Visit.buy", "a2a": "official ASGI 1.0", "live": False}


if __name__ == "__main__":
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(prefix="r4-customer-e2e-") as temp:
        print(json.dumps(e2e(Path(temp)), ensure_ascii=False))

