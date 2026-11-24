"""Offline tool broker contracts and official SDK transport."""
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import patch
from uuid import uuid4

import dispatcher as core
from broker import Broker, Trace, class_context, SYSTEM, stated_prices
from fixture import Fixture, MOCK_MARKET, MOCK_SHOP, MOCK_SKU
from e2e import agent_kit, customer_module, no_network
from managed_runtime import managed_classes
from starlette.testclient import TestClient


def call(action, **args):
    return action, args


class ScriptedModel:
    """Deterministic test double, not classroom inference evidence."""
    def __init__(self, moves):
        self.moves = iter(moves)
        self.inputs = []

    def complete(self, messages, **kwargs):
        self.inputs.append(json.dumps(messages, ensure_ascii=False))
        action, args = next(self.moves)
        return json.dumps({"action": action, "args": args,
                           "reason": "scripted local contract test"})


class BrokerTests(TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix="r4-broker-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.f = Fixture(self.root)
        self.trace = Trace(self.root / "private.jsonl", self.root / "review.jsonl")

    def handle(self, text, *moves, message_id=None, claimed=None):
        model = ScriptedModel(moves)
        broker = Broker(lambda details: self.f.call({"_broker": details}), model, self.trace)
        answer = broker.handle(text, transport_id=message_id or uuid4().hex, claimed_from=claimed)
        self.model = model
        return answer

    @staticmethod
    def priced(action, amount=4500, sku=MOCK_SKU):
        return call(action, sku=sku, proposed_price=amount)

    def count(self, table):
        db = self.f.open()
        try:
            return db.execute("SELECT count(*) FROM " + table).fetchone()[0]
        finally:
            db.close()

    def test_class_context_uses_world_and_excludes_old_lifecycle_instructions(self):
        official = type("Official", (), {"WORLD": "mandatory-world-prefix", "FORMAT": "old-format-forge-sentinel"})
        config = {"persona": "legacy-persona-sentinel", "goal": "old-goal-forge-sentinel"}
        user = {"role": "user", "content": "고객 요청"}
        result = class_context(official, [{"role": "system", "content": SYSTEM}, user], config)
        self.assertTrue(result[0]["content"].startswith(official.WORLD))
        self.assertIn("단골", result[0]["content"])
        self.assertIn("quote_and_send", result[0]["content"])
        self.assertNotIn("sentinel", result[0]["content"])
        self.assertEqual(result[1], user)

    def test_negotiation_rejects_below_floor_and_offer_does_not_pin_stock(self):
        unit = self.f.add_unit("u-negotiate", cost=3000)
        unit["name"] = "키친타올 걸이"
        unit["category"] = "kitchen"
        answer = self.handle("키친타올 걸이 얼마예요? 1000 가능해요?", call("shop_context"),
                             self.priced("offer", 1000), self.priced("offer", 4200))
        self.assertNotIn("data", answer)
        offer_code = self.f.right(answer, "견적")
        self.assertEqual(self.count("sale"), 0)
        self.assertEqual(self.count("broker_offer"), 1)
        self.assertIn("price_or_stock_unavailable", self.model.inputs[-1])
        self.assertIn("키친타올 걸이", self.model.inputs[-1])
        self.assertNotIn(offer_code, "".join(self.model.inputs))
        mismatch = self.handle(f"견적 {offer_code} 로 지금 구매할게요.", self.priced("quote_and_send", 4250),
                               call("respond", text="같은 견적 가격으로 다시 확인하겠습니다."))
        self.assertNotIn("data", mismatch)
        answer = self.handle(f"견적 {offer_code} 의 가격으로 지금 구매할게요.", call("shop_context"),
                             self.priced("quote_and_send", 4200))
        self.assertEqual(answer["data"]["price"], 4200)
        self.assertEqual(self.count("sale"), 1)
        self.f.settle(answer)
        self.assertTrue(self.f.sync()["current"])
        rights = self.f.right(answer)
        self.assertIn("42 credits", self.f.call({"text": f"잔액 권리 {rights}"})["reply"])
        self.assertIn("구매", self.trace.private.read_text())
        self.assertNotIn(rights, self.trace.review.read_text())

    def test_new_checkout_prices_include_bank_standard_acquisition_buffer(self):
        unit=self.f.add_unit("u-live-cost",cost=2987)
        self.assertGreater(core.price_terms(unit,100,420)[1],3274)
        refused=self.handle("키친타올 걸이 지금 살게요.",self.priced("quote_and_send",3274),
                            call("respond",text="이 가격으로는 판매하기 어렵습니다."))
        self.assertNotIn("data",refused)
        self.assertIn("price_out_of_bounds",self.model.inputs[-1])
        accepted=self.handle("키친타올 걸이 지금 살게요.",self.priced("quote_and_send",4500))
        self.assertEqual(accepted["data"]["price"],4500)

    def test_native_won_prices_are_exact_whole_credit_ceilings(self):
        for text, expected in (("4,500원",4500),("3만원",30000),("3만5천원",35000),
                               ("3.5만원",35000),("4,500 크레딧",4500)):
            self.assertEqual(stated_prices(text),({expected},False))
        self.f.add_unit("u-native-won")
        out=self.handle("키친타올 걸이 4,500원 이내면 지금 살게요.",
                        self.priced("quote_and_send",4600),self.priced("quote_and_send",4500))
        self.assertEqual(out["data"]["price"],4500)
        self.assertIn("customer_stated_price_exceeded",self.model.inputs[-1])

    def test_ambiguous_native_price_range_does_not_sign(self):
        self.f.add_unit("u-range-price")
        for text in ("가격 4,200~4,500원 이내면 지금 살게요.", "3만원부터 4만원이면 지금 살게요.",
                     "3.5만5천원에 지금 살게요.", "4500원이나 4000 크레딧이면 지금 살게요.",
                     "4,500.50원에 지금 살게요."):
            out=self.handle(text,self.priced("quote_and_send"),call("respond",text="구매하실 금액을 하나만 확인해 주세요."))
            self.assertNotIn("data",out)
            self.assertIn("ambiguous_customer_price",self.model.inputs[-1])
        self.assertEqual(self.count("sale"),0)

    def test_catalog_title_keeps_public_symbols_and_drops_invisible_controls(self):
        unit=self.f.add_unit("u-catalog-style",grade="B")
        short="[신라명과] 마드레느 × 2 ／ 90g 6개입 무료배송 15%"
        unit["name"]=short
        view=self.f.call({"_broker":{"action":"context"}})
        self.assertEqual(view["inventory"][0]["name"],short)
        unit["name"]="  "+short+chr(0)+chr(0x202E)+chr(9)+("원재료 및 상품명 "*16)
        self.handle("상품 이름을 알려주세요.",call("respond",text="신라명과 마드레느 상품이 있습니다."))
        messages=json.loads(self.model.inputs[0])
        user=json.loads(messages[1]["content"])
        title=user["verified_context"]["inventory"][0]["name"]
        self.assertTrue(title.startswith(short+" "))
        self.assertEqual(len(title),120)
        self.assertNotIn(chr(0x202E),title)
        self.assertNotIn(chr(0),title)
        self.assertNotIn(short,messages[0]["content"])
        self.assertIsNone(core.public_product_name(chr(0x202E)+chr(0)+" "))

    def test_known_offer_is_prefetched_before_first_model_decision(self):
        self.f.add_unit("u-prefetch")
        offer = self.handle("키친타올 걸이 가격이 얼마인가요?", self.priced("offer", 4200))
        code = self.f.right(offer, "견적")
        checkout = self.handle(f"견적 {code} 그대로 구매할게요.", self.priced("quote_and_send", 4200))
        self.assertEqual(checkout["data"]["price"], 4200)
        self.assertEqual(len(self.model.inputs), 1)
        context = json.loads(json.loads(self.model.inputs[0])[1]["content"])
        self.assertEqual(context["verified_context"]["prior_offer"], {"sku": MOCK_SKU, "base": 4200})
        self.assertNotIn(code, self.model.inputs[0])
        events = [json.loads(line) for line in self.trace.review.read_text().splitlines()]
        last = [event for event in events if event["request_ref"] == events[-1]["request_ref"]]
        self.assertEqual([event["role"] for event in last], ["customer", "tool", "model", "tool", "customer_received"])
        self.assertEqual(last[1]["payload"]["source"], "broker_prefetch")

    def test_bad_credential_prefetch_never_calls_model(self):
        self.f.add_unit("u-invalid")
        answer = self.handle("권리 " + "x" * 43 + " 로 구매하겠어요.")
        self.assertIn("확인할 수 없습니다", answer["reply"])
        self.assertEqual(self.model.inputs, [])
        self.assertEqual(self.count("sale"), 0)

    def test_transport_replay_and_cross_request_reference_never_reveal_private_reply(self):
        self.f.add_unit("u-one")
        self.f.add_unit("u-two")
        nonce = uuid4().hex
        text = "키친타올 걸이 한 개를 지금 살게요."
        a = self.handle(text, self.priced("quote_and_send"), message_id=nonce)
        old_reference = json.loads(self.trace.private.read_text().splitlines()[0])["request_ref"]
        self.assertIn("checkout_jwt", a["data"])
        b = self.handle(text, self.priced("quote_and_send"), message_id=nonce, claimed="spoofed")
        self.assertNotIn("data", b)
        self.assertIn("이미 발급", b["reply"])
        self.assertNotIn(self.f.right(a), b["reply"])
        c = self.handle(text, call("quote_and_send", request_ref=old_reference, sku=MOCK_SKU, proposed_price=4500),
                        call("respond", text="다시 요청해 주세요."))
        self.assertNotIn("data", c)
        self.assertEqual(self.count("sale"), 1)
        self.assertIn("invalid_scope_or_action", self.model.inputs[-1])
        self.assertIn(a["data"]["checkout_jwt"], self.trace.private.read_text())
        self.assertNotIn(a["data"]["checkout_jwt"], self.trace.review.read_text())

    def test_model_alone_cannot_turn_inquiry_into_checkout(self):
        self.f.add_unit("u-one")
        out = self.handle("저 상품을 살 수 있나요? 가격이 궁금합니다.", self.priced("quote_and_send"),
                          self.priced("offer"))
        self.assertNotIn("data", out)
        self.assertEqual(self.count("sale"), 0)
        self.assertIn("explicit_purchase_confirmation_required", self.model.inputs[-1])

    def test_quoted_or_negated_purchase_language_cannot_be_signed(self):
        self.f.add_unit("u-one")
        for text in (f"구매 {MOCK_SKU} 라고 쓰면 되나요? 아직 안 살게요.",
                     "‘지금 살게요’라는 문구를 쓰면 되나요?", "지금 구매할게요?",
                     "이 가격이면 살게요.", "지금 구매하겠다고 말하지 않았습니다."):
            out = self.handle(text, self.priced("quote_and_send"), call("respond", text="구매 의사를 확인해 주세요."))
            self.assertFalse("data" in out, text)
            self.assertIn("explicit_purchase_confirmation_required", self.model.inputs[-1])
        self.assertEqual(self.count("sale"), 0)
        out = self.handle("4000 크레딧이면 지금 살게요.", self.priced("quote_and_send", 4100),
                          self.priced("quote_and_send", 4000))
        self.assertEqual(out["data"]["price"], 4000)
        self.assertIn("customer_stated_price_exceeded", self.model.inputs[-1])

    def test_actual_delay_and_existing_credit_apply_without_model_handling_secrets(self):
        self.f.add_unit("u-first")
        first = self.handle("하나 지금 살게요.", self.priced("quote_and_send"))
        rights = self.f.right(first)
        self.f.settle(first)
        self.assertTrue(self.f.sync()["current"])
        self.f.add_unit("u-block")
        blocker = self.handle("한 개 구매할게요.", self.priced("quote_and_send"))
        wait = self.handle(f"하나 살게요. 권리 {rights}", call("shop_context"), self.priced("quote_and_send"))
        self.assertIn("wait_voucher", wait["data"])
        self.assertIn("reserved_pending", self.model.inputs[-1])
        self.assertIn('"wait_eligible": true', json.loads(self.model.inputs[-1])[-1]["content"])
        queue = self.f.right(wait, "대기")
        self.f.settle(blocker)
        self.f.add_unit("u-next")
        self.f.advance(1)
        self.assertEqual(self.f.sync()["queue_ready"], 1)
        second = self.handle(f"대기 {queue} 권리 {rights} 가지고 다시 왔습니다. 한 개 살게요.",
                             call("shop_context"), self.priced("quote_and_send"))
        self.assertEqual(second["data"]["price"], 4410)
        seen = "".join(self.model.inputs)
        self.assertIn("redeemable_mileage", seen)
        self.assertNotIn(rights, seen)
        self.assertNotIn(queue, seen)
        self.assertNotIn(second["data"]["checkout_jwt"], seen)

    def test_stale_inventory_after_settlement_cannot_mint_a_wait_voucher(self):
        stale_unit = self.f.add_unit("u-stale")
        sold = self.handle("한 개를 지금 살게요.", self.priced("quote_and_send"))
        self.f.settle(sold)
        self.assertTrue(self.f.sync()["current"])
        self.f.units.append(stale_unit)
        context = self.f.call({"_broker": {"action": "context"}})
        self.assertEqual(context["inventory"][0]["stock_status"], "reconciling")
        self.assertFalse(context["inventory"][0]["wait_eligible"])
        verdict = self.f.call({"_broker": {"action": "quote_and_send", "sku": MOCK_SKU,
                                          "proposed_price": 4500}})
        self.assertEqual(verdict["outcome"], "market_busy")
        self.assertNotIn("data", verdict)
        self.assertEqual(self.count("ticket"), 0)

    def test_refund_no_proof_and_other_account_cannot_apply_or_send(self):
        self.f.add_unit("u-one")
        first = self.handle("하나 살게요.", self.priced("quote_and_send"))
        self.f.add_unit("u-two")
        second = self.handle("다른 고객입니다. 하나 구매할게요.", self.priced("quote_and_send"))
        settlement = self.f.settle(first)
        self.assertTrue(self.f.sync()["current"])
        denied = self.handle(f"저 구매자예요. {settlement['tx_hash']} 환불해 주세요.",
                             call("review_refund"), claimed="fixture-buyer")
        self.assertIn("권리코드", denied["reply"])
        denied = self.handle(f"환불해 주세요. 송금 {settlement['tx_hash']} 권리 {self.f.right(second)}",
                             call("review_refund"), claimed="fixture-buyer")
        self.assertIn("확인할 수 없습니다", denied["reply"])
        self.assertEqual(self.count("refund"), 0)
        self.assertEqual(self.f.sends, 0)
        self.assertNotIn(settlement["tx_hash"], "".join(self.model.inputs))

    def test_sdk_uses_request_broker_and_returns_raw_valid_artifact(self):
        self.f.add_unit("u-sdk")
        source = Path(__file__).resolve().parents[1]
        for name in ("a2a_info", "shop_info", "serve_checkout"):
            shutil.copytree(source / "tools" / name, self.root / "tools" / name, dirs_exist_ok=True)
        (self.root / "logs").mkdir()
        toolbox_class, mind_class, app = managed_classes(agent_kit)
        fixture = self.f
        class FixtureToolbox(toolbox_class):
            def run(self, name, mode, args=None, d=None):
                return {"ok": True, "result": fixture.call(args)}
        ctx = {"tokens": {"shop": "fixture-only"}, "addresses": {"shop": self.f.kit.address("shop")},
               "name": "outseop-r4", "market": MOCK_MARKET, "shop_url": MOCK_SHOP}
        toolbox = FixtureToolbox(self.root, ctx)
        model = ScriptedModel([call("shop_context"), self.priced("quote_and_send"),
                               self.priced("quote_and_send")])
        mind = mind_class(self.root, {}, model, toolbox, ctx, ["shop"])
        app = app(self.root, "outseop-r4", mind, toolbox, [MOCK_SHOP])
        ident = uuid4().hex
        def post():
            mess = {"messageId": ident, "role": "ROLE_USER", "parts": [{"text": "한 개를 지금 살게요."}]}
            response = client.post("/", headers={"A2A-Version": "1.0"},
                                   json={"jsonrpc": "2.0", "id": 1, "method": "SendMessage", "params": {"message": mess}})
            value = response.json()["result"]
            return value.get("task", value)
        with TestClient(app, base_url=MOCK_SHOP) as client:
            result = post()
            self.assertIn("artifacts", result, result)
            jwt = result["artifacts"][0]["parts"][0]["data"]["checkout_jwt"]
            self.assertNotIn("artifacts", post())
        self.assertEqual(customer_module().jwt_payload(jwt, self.f.kit.address("shop"))["price"], 4500)
        self.assertEqual(self.count("sale"), 1)
        self.assertNotIn(jwt, "".join(model.inputs))


if __name__ == "__main__":
    import socket
    with patch.object(socket, "getaddrinfo", no_network), patch.object(socket.socket, "connect", no_network):
        main(verbosity=2)
