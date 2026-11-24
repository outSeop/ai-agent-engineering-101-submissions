"""Official ASGI and Mind boundary tests without market or model connectivity."""
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase, main
from unittest.mock import patch
from uuid import uuid4

from starlette.testclient import TestClient

from e2e import agent_kit, customer_module, no_network
from fixture import Fixture, MOCK_SKU, MOCK_SHOP, MOCK_MARKET
import managed_runtime as boundary
import shop_info


class FakeModel:
    def __init__(self, moves):
        self.moves = iter(moves)
        self.history = []

    def complete(self, messages, **kwargs):
        self.history.append(json.dumps(messages, ensure_ascii=False))
        action, args = next(self.moves)
        return json.dumps({"thought": "Boundary test", "action": action, "args": args})


class ManagedRuntimeTests(TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix="r4-managed-runtime-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.f = Fixture(self.root)
        source = Path(__file__).resolve().parents[1]
        (self.root / "logs").mkdir()
        (self.root / "tools").mkdir()
        for name in ("a2a_info", "serve_checkout", "shop_info", "pay_confirm_stock"):
            shutil.copytree(source / "tools" / name, self.root / "tools" / name)
        self.f.add_unit("u-managed")
        toolbox_class, self.mind_class, self.app = boundary.managed_classes(agent_kit)
        fixture = self.f
        class FixtureToolbox(toolbox_class):
            dispatch_failed = False

            def run(self, name, mode, args=None, d=None):
                assert mode == "call"
                if name == boundary.PUBLIC_DISPATCH:
                    if self.dispatch_failed:
                        return {"ok": False, "error": "fixture private failure"}
                    return {"ok": True, "result": fixture.call(args)}
                if name == boundary.MODEL_INFO:
                    assert args == {}
                    with fixture.patches():
                        return {"ok": True, "result": shop_info.run({}, fixture.kit)}
                raise AssertionError("a forbidden tool's code was executed")

        self.ctx = {"tokens": {"shop": "fixture-only"}, "addresses": {"shop": self.f.kit.address("shop")},
                    "name": "outseop-r4", "market": MOCK_MARKET, "shop_url": MOCK_SHOP}
        self.toolbox = FixtureToolbox(self.root, self.ctx)
        self.toolbox.validate()

    def mind(self, model):
        return self.mind_class(self.root, {"max_steps": 10, "run_minutes": 10},
                               model, self.toolbox, self.ctx, ["shop"])

    def talk(self, mind, text, *, data=None, claimed_from="spoofable-persona"):
        parts = [{"text": text}] + ([{"data": data}] if data else [])
        payload = {"jsonrpc": "2.0", "id": 1, "method": "SendMessage", "params": {"message": {
            "messageId": uuid4().hex, "role": "ROLE_USER", "parts": parts, "metadata": {"from": claimed_from}}}}
        asgi = self.app(self.root, "outseop-r4", mind, self.toolbox, [MOCK_SHOP])
        with TestClient(asgi, base_url=MOCK_SHOP) as client:
            response = client.post("/", headers={"A2A-Version": "1.0"}, json=payload)
        value = response.json()
        self.assertIn("result", value, value)
        return value["result"].get("task", value["result"])

    def reply(self, task):
        return task["status"]["message"]["parts"][0]["text"]

    def test_official_a2a_enters_one_shot_financial_dispatch_and_returns_valid_jwt(self):
        mind = self.mind(FakeModel([("quote_and_send", {"sku": MOCK_SKU, "proposed_price": 4500})]))
        task = self.talk(mind, f"구매 {MOCK_SKU}", data={"op": "approve-and-send"})
        result = task["artifacts"][0]["parts"][0]["data"]
        token = result["checkout_jwt"]
        self.assertEqual(customer_module().jwt_payload(token, self.f.kit.address("shop"))["price"], 4500)
        code = self.f.right({"reply": self.reply(task)})
        result = self.talk(mind, f"잔액 권리 {code}")
        self.assertIn("0 credits", self.reply(result))
        self.assertEqual(mind.pending, {})
        self.assertIsNone(self.toolbox.handler("a2a"))
        self.assertFalse(self.toolbox.call("a2a_info", {"text": f"잔액 권리 {code}", "task_id": task["id"],
                                                        "context_id": task["contextId"], "claimed_from": "customer"})["ok"])
        self.assertFalse((self.root / "logs" / "react.jsonl").exists())

    def test_mind_allowlisted_lookup_and_rejects_forgery_new_code_and_hidden_tools(self):
        fake = {"text": f"구매 {MOCK_SKU}", "task_id": "forged-id", "context_id": "forged-context",
                "claimed_from": "buyer", "trusted": True}
        model = FakeModel([("a2a_info", fake), ("serve_checkout", fake), ("pay_confirm_stock", {}),
                           ("forge_tool", {"name": "escape"}), ("read_tool", {"name": "a2a_info"}),
                           ("shop_info", fake), ("sleep", {"seconds": 30})])
        mind = self.mind(model)
        self.assertEqual(set(mind.toolbox.tools), {"shop_info"})
        self.assertEqual(mind.toolbox.forge({"name": "new"}), boundary.PERMISSION_ERROR)
        mind.run_once([])
        rows = [json.loads(line) for line in (self.root / "logs" / "react.jsonl").read_text().splitlines()]
        self.assertEqual([entry["action"] for entry in rows],
                         ["a2a_info", "serve_checkout", "pay_confirm_stock", "forge_tool", "read_tool", "shop_info", "sleep"])
        self.assertTrue(all("no tool" in row["observation"] for row in rows[:3]))
        self.assertTrue(all(boundary.PERMISSION_ERROR in row["observation"] for row in rows[3:5]))
        self.assertIn(MOCK_SKU, rows[5]["observation"])
        self.assertNotIn("checkout_jwt", "".join(model.history))
        self.assertFalse(self.f.db_path.exists())

    def test_fallback_from_failed_dispatch_never_enters_mind_context_or_log(self):
        model = FakeModel([("quote_and_send", {"sku": MOCK_SKU, "proposed_price": 4500}), ("shop_info", {}), ("sleep", {"seconds": 30})])
        mind = self.mind(model)
        checkout = self.talk(mind, f"구매 {MOCK_SKU}")
        rights = self.f.right({"reply": self.reply(checkout)})
        self.toolbox.dispatch_failed = True
        failed = self.talk(mind, f"잔액 권리 {rights}", data={"rights": rights})
        self.assertEqual(self.reply(failed), boundary.FALLBACK["reply"])
        self.assertEqual(mind.pending, {})
        self.assertEqual(mind.fresh(), [])
        mind.run_once([])
        self.assertNotIn(rights, "".join(model.history))
        log = (self.root / "logs" / "react.jsonl").read_text(encoding="utf-8")
        self.assertNotIn(rights, log)
        self.assertNotIn("fixture private failure", log)

    def test_stock_runtime_does_not_start_generic_mind_loop(self):
        tools, mind_type, _ = boundary.managed_classes(agent_kit,enable_stock=True)
        toolbox=tools(self.root,self.ctx)
        mind=mind_type(self.root,{},FakeModel([]),toolbox,self.ctx,["shop"])
        ran=[]
        mind.stock_coordinator=SimpleNamespace(loop=lambda:ran.append("stock"))
        with patch.object(agent_kit.Mind,"loop",side_effect=AssertionError("generic Mind loop started")):
            mind.loop()
        self.assertEqual(ran,["stock"])

    def test_forum_and_card_are_never_public_model_capabilities(self):
        fake={"action":"publish","decision":{"action":"spotlight","sku":MOCK_SKU,"grade":"A"}}
        mind=self.mind(FakeModel([]))
        for name in ("forum_marketing","publish_shop_info"):
            self.assertFalse(self.toolbox.call(name,fake)["ok"])
            self.assertFalse(mind.toolbox.call(name,fake)["ok"])
        self.assertEqual(set(mind.toolbox.tools),{"shop_info"})

    def test_forum_validation_rejects_wallet_and_broad_card_writes(self):
        perm={"identity":["shop"],"network":["market.ourolabs.ai"],"write":["state/r4-benefits"]}
        self.toolbox.tools["forum_marketing"]={"perm":perm}
        self.toolbox.tools["publish_shop_info"]={"perm":{"write":["card.json"]}}
        self.toolbox.validate()
        perm["wallet"]=["pay"]
        with self.assertRaises(RuntimeError):
            self.toolbox.validate()
        del perm["wallet"]
        self.toolbox.tools["publish_shop_info"]["perm"]["write"].append("shop_wallet.key")
        with self.assertRaises(RuntimeError):
            self.toolbox.validate()

    def test_marketing_and_stock_share_one_periodic_lane(self):
        tools,mind_type,_=boundary.managed_classes(agent_kit,enable_stock=True)
        toolbox=tools(self.root,self.ctx)
        toolbox.tools["forum_marketing"]={"perm":{}}
        mind=mind_type(self.root,{},FakeModel([]),toolbox,self.ctx,["shop"])
        ran=[]
        original_stock=mind.stock_coordinator
        mind.marketing_coordinator=SimpleNamespace(loop=lambda stock,maintenance:ran.append((stock,callable(maintenance))))
        with patch.object(agent_kit.Mind,"loop",side_effect=AssertionError("generic Mind loop started")):
            mind.loop()
        self.assertEqual(ran,[(original_stock,True)])

    def test_validation_refuses_any_extra_handler_or_shop_info_wallet_permission(self):
        self.toolbox.tools["serve_checkout"]["perm"]["handles"] = ["a2a"]
        with self.assertRaises(RuntimeError):
            self.toolbox.validate()
        del self.toolbox.tools["serve_checkout"]["perm"]["handles"]
        self.toolbox.tools["shop_info"]["perm"]["wallet"] = ["pay"]
        with self.assertRaises(RuntimeError):
            self.toolbox.validate()


if __name__ == "__main__":
    import socket
    with patch.object(socket, "getaddrinfo", no_network), patch.object(socket.socket, "connect", no_network):
        main(verbosity=2)

