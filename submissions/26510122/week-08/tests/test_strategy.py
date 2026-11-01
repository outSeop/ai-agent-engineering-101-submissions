"""Behavioral checks for the first shop-side Round 3 strategy slice."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid
from collections import Counter

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import market_memory
import newsvendor_tool
import restock
import seller_r3


class NewsvendorTests(unittest.TestCase):
    def test_lecture_discrete_example_selects_thirteen(self) -> None:
        probabilities = [0.0] * 4 + [
            0.01, 0.02, 0.04, 0.08, 0.09, 0.11, 0.16,
            0.20, 0.11, 0.10, 0.04, 0.02, 0.01, 0.01,
        ]
        result = newsvendor_tool.recommend_quantity(probabilities, 100, 45, salvage=40)
        self.assertEqual(result["quantity"], 13)
        self.assertAlmostEqual(result["critical_ratio"], 55 / 60, places=5)

    def test_quote_shows_grade_and_expiry_without_cost_floor(self) -> None:
        unit = {"sku": "food-1", "unit": "u1", "kind": "food", "grade": "C",
                "cost": 450, "list_price": 1000, "expires_at": 3600}
        quote = newsvendor_tool.quote_candidates(unit, now=0)
        self.assertEqual([x["price"] for x in quote["candidates"]], [540, 600, 660])
        self.assertEqual(quote["hours_left"], 1.0)


class MemoryTests(unittest.TestCase):
    def test_receipt_does_not_count_until_kit_settles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            event_log, kit_log, cursor = root / "events.jsonl", root / "kit.log", root / "cursor.json"
            market_memory.record("opening", path=event_log, task_id="t1", sku="food-1",
                                 unit="u1", grade="B", ask=100, list_price=120)
            market_memory.record("offer", path=event_log, task_id="t1", price=90)
            market_memory.record("counter", path=event_log, task_id="t1", ask=95)
            market_memory.record("receipt_signed", path=event_log, task_id="t1", sku="food-1",
                                 unit="u1", grade="B", price=95)
            pending = market_memory.compact_context("food-1", "B", path=event_log)
            self.assertEqual(pending["outcomes"], {"RECEIPT_PENDING": 1})
            self.assertEqual(pending["recent_same_grade"][0]["counters"], [95])
            kit_log.write_text("12:00 [acp] settled Food at 95, ledger #123, unit u1 grade B\n")
            self.assertEqual(market_memory.sync_settlements(kit_log, event_log=event_log,
                                                            cursor_path=cursor), 1)
            self.assertEqual(market_memory.sync_settlements(kit_log, event_log=event_log,
                                                            cursor_path=cursor), 0)
            settled = market_memory.compact_context("food-1", "B", path=event_log)
            self.assertEqual(settled["outcomes"], {"SETTLED": 1})
            self.assertEqual(settled["recent_same_grade"][0]["settled_price"], 95)


class IntegrationTests(unittest.TestCase):
    def test_a2a_model_choice_is_emitted_and_unit_is_held_after_receipt(self) -> None:
        async def exchange() -> None:
            app = seller_r3.build(9999)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://testserver") as client:
                async def send(message: str, task_id: str | None = None) -> dict:
                    body = {"role": "ROLE_USER", "messageId": str(uuid.uuid4()),
                            "parts": [{"text": message}]}
                    if task_id:
                        body["taskId"] = task_id
                    response = await client.post("/", json={"jsonrpc": "2.0", "id": "1",
                                                     "method": "SendMessage", "params": {"message": body}},
                                                 headers={"A2A-Version": "1.0"})
                    response.raise_for_status()
                    result = response.json()
                    self.assertNotIn("error", result)
                    return result["result"].get("task", result["result"])

                first = await send("I want to buy A1")
                self.assertIn("asking 120", first["status"]["message"]["parts"][0]["text"])
                second = await send("110", first["id"])
                self.assertEqual(second["status"]["state"], "TASK_STATE_COMPLETED")
                third = await send("I want to buy A1")
                self.assertEqual(third["status"]["state"], "TASK_STATE_REJECTED")

        with tempfile.TemporaryDirectory() as directory:
            previous = Path.cwd()
            os.chdir(directory)
            try:
                key = Ed25519PrivateKey.generate()
                Path("shop_key.pem").write_bytes(key.private_bytes(
                    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption()))
                market = Path(".market")
                market.mkdir()
                (market / "inventory.json").write_text(json.dumps({"round": 3, "units": [{
                    "unit": "u1", "sku": "A1", "name": "Example Food", "category": "food>example",
                    "kind": "food", "grade": "A", "cost": 70, "list_price": 100,
                    "supplied_at": 1, "expires_at": time.time() + 36000,
                }]}))
                answers = [
                    {"action": "ask", "price": 120, "unit_id": "u1", "reason": "test quote"},
                    {"action": "accept", "price": None, "unit_id": "u1", "reason": "test acceptance"},
                ]
                with patch.object(seller_r3, "decide_json", side_effect=answers):
                    import asyncio
                    asyncio.run(exchange())
                summary = market_memory.compact_context("A1", "A")
                self.assertEqual(summary["outcomes"], {"RECEIPT_PENDING": 1})
                self.assertEqual(summary["recent_same_grade"][0]["opening_ask"], 120)
            finally:
                os.chdir(previous)

    def test_restock_hook_uses_model_scenario_and_quantity_tool(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            previous = Path.cwd()
            os.chdir(directory)
            try:
                market = Path(".market")
                market.mkdir()
                (market / "inventory.json").write_text(json.dumps(
                    {"round": 3, "balance": 5_000_000, "units": []}))
                (market / "catalog.json").write_text(json.dumps({
                    "food-1": {"kind": "food", "list_price": 1000,
                               "shelf_hours": 72, "name": "Example Food"}}))
                choice = {"action": "buy", "sku": "food-1", "expected_sale_price": 800,
                          "demand_mean": 1.2, "reason": "small exploratory lot"}
                with patch.object(restock, "decide_json", return_value=choice), \
                     patch.object(restock, "fetch_market_sales", return_value=Counter({"food-1": 3})):
                    result = restock.run(market)
                self.assertEqual(result, {"buy": [{"sku": "food-1", "qty": 1}]})
                self.assertEqual(restock.run(market), {"buy": []})  # cooldown
                self.assertEqual(market_memory.events()[-1]["calculation"]["quantity"], 1)
            finally:
                os.chdir(previous)

    def test_seller_does_not_offer_taken_or_expired_units(self) -> None:
        inventory = {"round": 3, "units": [
            {"unit": "u1", "sku": "A1", "name": "Kimchi", "category": "food>kimchi", "grade": "A"},
            {"unit": "u2", "sku": "A1", "name": "Kimchi", "category": "food>kimchi", "grade": "expired"},
            {"unit": "u3", "sku": "A1", "name": "Kimchi", "category": "food>kimchi", "grade": "B"},
        ]}
        result = seller_r3.find_units("I want A1", {"u1"}, inventory)
        self.assertEqual([u["unit"] for u in result], ["u3"])

    def test_public_settlements_enter_candidates_as_labeled_sales(self) -> None:
        catalog = {"a": {"kind": "food", "list_price": 100, "shelf_hours": 72},
                   "b": {"kind": "food", "list_price": 100, "shelf_hours": 72}}
        candidates = restock.choose_candidates(catalog, {"units": []}, [], Counter({"b": 4}))
        self.assertEqual(candidates[0]["sku"], "b")
        self.assertEqual(candidates[0]["recent_public_settlements"], 4)

    def test_public_ledger_reader_ignores_orders_and_old_rounds(self) -> None:
        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return [
                    {"round": 3, "kind": "settle", "data": {"item": "a"}},
                    {"round": 3, "kind": "order", "data": {"item": "b"}},
                    {"round": 2, "kind": "result", "data": {"item": "c"}},
                ]

        with patch.object(restock.httpx, "get", return_value=Response()):
            self.assertEqual(restock.fetch_market_sales(), Counter({"a": 1}))


if __name__ == "__main__":
    unittest.main()
