"""A2A shop: calculation-tool evidence, compact memory, model-owned decisions."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
from pathlib import Path
import re
import time

import uvicorn
from cryptography.hazmat.primitives import serialization
from starlette.applications import Starlette

from a2a.helpers import get_message_text, new_data_part, new_task_from_user_message, new_text_part
from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill

from harness import MODEL, decide_json, trace
from market_memory import compact_context, record, sync_settlements
from newsvendor_tool import quote_candidates
from inventory_observation import requested_skus
from context_compaction import MAX_TURNS


NAME = "outseop-26510122"
MARKET_DIR = Path(os.environ.get("MARKET_DIR", ".market"))
RESERVE = {"lamp": 100, "chair": 180, "bookshelf": 260}  # pre-Round-3 compatibility
HOLD_SECONDS = 600


def canon(body: dict) -> bytes:
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sign(receipt: dict) -> dict:
    key = serialization.load_pem_private_key(Path("shop_key.pem").read_bytes(), password=None)
    body = {k: receipt[k] for k in ("shop", "item", "price", "task")}
    return dict(receipt, sig_seller=base64.b64encode(key.sign(canon(body))).decode())


def read_inventory() -> dict:
    try:
        return json.loads((MARKET_DIR / "inventory.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def find_units(text: str, taken: set[str], inventory: dict) -> list[dict]:
    """Only currently available units; exact SKU requests win over broad categories."""
    want = text.lower()
    if inventory.get("round", 0) < 3:
        item = next((name for name in RESERVE if re.search(rf"\b{name}\b", want)), None)
        if item is None:
            return []
        reserve = RESERVE[item]
        return [{"sku": item, "name": item, "category": "pre-round-3",
                 "list_price": round(reserve * 1.3), "cost": reserve, "grade": "A",
                 "kind": "goods", "unit": item, "expires_at": None, "supplied_at": 0}]
    units = inventory.get("units", [])
    def fits(u: dict) -> bool:
        terms = (u.get("sku", "").lower(), u.get("name", "").lower(),
                 (u.get("category") or "").split(">")[-1].lower())
        return any(term and term in want for term in terms)

    matches = [u for u in units if u.get("grade") in ("A", "B", "C")
               and u.get("unit") not in taken and fits(u)]
    named = [u for u in matches if u["sku"].lower() in want]
    if named:
        matches = named
    matches.sort(key=lambda u: (u.get("expires_at") or float("inf"), u.get("supplied_at") or 0))
    return matches[:12]


def decision_schema(actions: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": actions},
            "price": {"type": ["integer", "null"]},
            "unit_id": {"type": ["string", "null"]},
            "reason": {"type": "string"},
        },
        "required": ["action", "price", "unit_id", "reason"],
        "additionalProperties": False,
    }


class Seller(AgentExecutor):
    def __init__(self) -> None:
        self.open: dict[str, dict] = {}
        self.holds: dict[str, float] = {}  # signed receipts awaiting checkout/settlement

    def available(self, text: str) -> list[dict]:
        inventory = read_inventory()
        stock = {u.get("unit") for u in inventory.get("units", [])}
        now = time.monotonic()
        self.holds = {unit: until for unit, until in self.holds.items()
                      if until > now and (not stock or unit in stock)}
        taken = {d["unit"]["unit"] for d in self.open.values()} | set(self.holds)
        return find_units(text, taken, inventory)

    async def choose(self, prompt: dict, actions: list[str], fallback: dict) -> dict:
        try:
            answer = await asyncio.to_thread(decide_json, "seller", prompt, decision_schema(actions))
        except Exception as error:
            trace("model_fallback", phase=prompt["phase"], error=type(error).__name__,
                  reason=str(error)[-400:])
            answer = dict(fallback, reason=f"model unavailable: {type(error).__name__}")
        record("model_choice", task_id=prompt["task_id"], phase=prompt["phase"],
               action=answer["action"], price=answer.get("price"),
               unit=answer.get("unit_id"), reason=answer.get("reason"),
               fallback=answer["reason"].startswith("model unavailable:"))
        return answer

    async def execute(self, context, event_queue) -> None:
        task = context.current_task
        if task is None:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)
        up = TaskUpdater(event_queue=event_queue, task_id=task.id, context_id=task.context_id)
        def say(message):
            record('seller_message',task_id=task.id,text=message)
            return up.new_agent_message(parts=[new_text_part(message)])
        message = get_message_text(context.message) or ""
        record('buyer_message',task_id=task.id,text=message)
        deal = self.open.get(task.id)

        if deal is None:
            try:
                catalog = json.loads((MARKET_DIR / 'catalog.json').read_text(encoding='utf-8'))
                if not isinstance(catalog, dict):
                    catalog = {}
            except (OSError, ValueError):
                catalog = {}
            requested = requested_skus(message, catalog)
            record('request_seen', task_id=task.id, requested_skus=requested)
            try:
                imported = sync_settlements()
                if imported:
                    trace("settlements_imported", count=imported)
            except OSError as error:
                trace("settlement_sync_error", error=str(error))
            choices = self.available(message)
            if not choices:
                record("no_stock", task_id=task.id, request=message[:160], requested_skus=requested)
                await up.reject(say("Sorry, no matching unit is in stock."))
                return
            tools = [quote_candidates(u) for u in choices]
            keys=list(dict.fromkeys((u['sku'],u['grade']) for u in choices))
            per_key=min(3600,12000//len(keys)-64)
            memories={f'{sku}:{grade}':compact_context(sku,grade,max_bytes=per_key) for sku,grade in keys}
            for tool in tools:
                tool['memory_key']=f"{tool['sku']}:{tool['grade']}"
            prompt = {
                "phase": "opening", "task_id": task.id, "buyer_message": message[:500],
                "objective": "Choose one available physical unit and an opening price. "
                             "Use the calculation-tool candidates and market memory as evidence; "
                             "you may choose another positive price when you explain why. "
                             "A signed receipt is not a settled sale.",
                "unit_options": tools, "memory_by_sku_grade": memories,
            }
            middle = tools[0]["candidates"][len(tools[0]["candidates"]) // 2]["price"]
            answer = await self.choose(prompt, ["ask", "reject"],
                                       {"action": "ask", "price": middle, "unit_id": choices[0]["unit"]})
            if answer["action"] == "reject":
                record("rejected", task_id=task.id, reason=answer["reason"])
                await up.reject(say("No suitable offer for this request."))
                return
            unit = next((u for u in choices if u["unit"] == answer.get("unit_id")), choices[0])
            current = read_inventory()
            if current.get("round", 0) >= 3:
                current_unit = next((u for u in current.get("units", [])
                                     if u.get("unit") == unit["unit"] and u.get("grade") != "expired"), None)
                already_taken = ({d["unit"]["unit"] for d in self.open.values()}
                                 | set(self.holds))
                if (current_unit is None or unit["unit"] in already_taken
                        or any(current_unit.get(k) != unit.get(k)
                               for k in ("grade", "cost", "expires_at"))):
                    record("stale_inventory", task_id=task.id, unit=unit["unit"])
                    await up.reject(say("That unit is no longer available. Please try again."))
                    return
                unit = current_unit
            proposed = answer.get("price")
            maximum = max(1, 2 * int(unit["list_price"]))
            ask = min(maximum, max(1, int(proposed))) if type(proposed) is int else middle
            if ask != proposed or unit["unit"] != answer.get("unit_id"):
                trace("decision_guard", phase="opening", proposed_price=proposed,
                      effective_price=ask, proposed_unit=answer.get("unit_id"),
                      effective_unit=unit["unit"])
            self.open[task.id] = deal = {
                "unit": unit, "ask": ask, "history": [], "opened_at": time.time(),
            }
            record("opening", task_id=task.id, sku=unit["sku"], unit=unit["unit"],
                   category=unit.get("category"), grade=unit["grade"], kind=unit.get("kind"),
                   cost=unit["cost"], list_price=unit["list_price"], ask=ask,
                   expires_at=unit.get("expires_at"))
            trace("seller_open", task_id=task.id, sku=unit["sku"], unit=unit["unit"],
                  grade=unit["grade"], cost=unit["cost"], ask=ask)
            await up.requires_input(say(f"{unit['name']}: asking {ask}. Send your offer as a number."))
            return

        offered = re.fullmatch(r"\s*(\d+)\s*", message)
        if not offered:
            await up.requires_input(say(f"Please send one whole-number offer. Current ask: {deal['ask']}"))
            return
        offer = int(offered.group(1))
        unit = deal["unit"]
        current = read_inventory()
        if current.get("round", 0) >= 3:
            fresh = next((u for u in current.get("units", [])
                          if u.get("unit") == unit["unit"] and u.get("grade") != "expired"), None)
            if fresh is None:
                record("stale_inventory", task_id=task.id, unit=unit["unit"])
                await up.reject(say("That unit is no longer available."))
                del self.open[task.id]
                return
            unit = deal["unit"] = fresh
        record("offer", task_id=task.id, sku=unit["sku"], unit=unit["unit"], price=offer,
               grade=unit['grade'],cost=unit['cost'],expires_at=unit.get('expires_at'))
        deal["history"].append({"buyer_offer": offer, "seller_ask": deal["ask"]})
        memory = compact_context(unit["sku"], unit["grade"])
        prompt = {
            "phase": "follow_up", "task_id": task.id,
            "unit": quote_candidates(unit), "current_ask": deal["ask"],
            "buyer_offer": offer, "history": deal["history"][-MAX_TURNS:], "memory": memory,
            "objective": "Accept, counter or reject. Consider purchase cost, grade, "
                         "food expiry and goods storage, but do not treat purchase cost "
                         "as an absolute floor for food already near expiry. "
                         "A receipt counts only if checkout later settles.",
        }
        fallback_action = "accept" if offer >= int(unit["cost"]) else "counter"
        answer = await self.choose(prompt, ["accept", "counter", "reject"],
                                   {"action": fallback_action, "price": deal["ask"],
                                    "unit_id": unit["unit"]})
        current = read_inventory()
        if current.get("round", 0) >= 3:
            fresh = next((u for u in current.get("units", [])
                          if u.get("unit") == unit["unit"] and u.get("grade") != "expired"), None)
            if (fresh is None or any(fresh.get(k) != unit.get(k)
                                     for k in ("grade", "cost", "expires_at"))):
                record("stale_inventory", task_id=task.id, unit=unit["unit"])
                await up.reject(say("That unit changed during negotiation. Please try again."))
                del self.open[task.id]
                return
        action = answer["action"]
        if action == "accept" and offer > 0:
            receipt = sign({"shop": NAME, "item": unit["sku"], "price": offer,
                            "task": task.id, "unit": unit["unit"]})
            await up.add_artifact(parts=[new_data_part(receipt)], name="receipt")
            record("receipt_signed", task_id=task.id, sku=unit["sku"], unit=unit["unit"],
                   grade=unit["grade"], price=offer,cost=unit['cost'],expires_at=unit.get('expires_at'))
            self.holds[unit["unit"]] = time.monotonic() + HOLD_SECONDS
            await up.complete(say(f"Deal: {unit['name']} at {offer}."))
            trace("seller_receipt", task_id=task.id, unit=unit["unit"], price=offer,
                  status="pending settlement")
            del self.open[task.id]
            return
        if action == "reject":
            record("rejected", task_id=task.id, sku=unit["sku"], unit=unit["unit"],
                   price=offer, reason=answer["reason"])
            await up.reject(say("No deal."))
            del self.open[task.id]
            return
        proposed = answer.get("price")
        maximum = max(1, 2 * int(unit["list_price"]))
        ask = min(maximum, max(1, int(proposed))) if type(proposed) is int else deal["ask"]
        if ask != proposed:
            trace("decision_guard", phase="follow_up", proposed_price=proposed, effective_price=ask)
        deal["ask"] = ask
        record("counter", task_id=task.id, sku=unit["sku"], unit=unit["unit"],
               buyer_offer=offer, ask=ask)
        trace("seller_counter", task_id=task.id, sku=unit["sku"], offer=offer, ask=ask)
        await up.requires_input(say(f"Counteroffer: {ask}."))

    async def cancel(self, context, event_queue) -> None:
        task = context.current_task
        if task is None:
            return
        deal = self.open.pop(task.id, None)
        record("cancelled", task_id=task.id, sku=deal["unit"]["sku"] if deal else None)
        await TaskUpdater(event_queue=event_queue, task_id=task.id, context_id=task.context_id).cancel()


def build(port: int) -> Starlette:
    url = f"http://127.0.0.1:{port}/"
    card = AgentCard(
        name=NAME,
        description=f"An inventory-backed shop using {MODEL} for price negotiation.",
        version="1.0.0",
        default_input_modes=["text/plain"],
        default_output_modes=["application/json", "text/plain"],
        capabilities=AgentCapabilities(streaming=False),
        supported_interfaces=[AgentInterface(protocol_binding="JSONRPC", url=url, protocol_version="1.0")],
        skills=[AgentSkill(id="negotiate", name="Negotiate a stocked purchase",
                           description="Ask for a stocked product by SKU or name, then offer a whole-number price.",
                           tags=["shopping", "negotiation", "signed-receipt"],
                           examples=["I want to buy G00001", "52000"])],
    )
    handler = DefaultRequestHandler(agent_executor=Seller(), task_store=InMemoryTaskStore(), agent_card=card)
    return Starlette(routes=create_agent_card_routes(card) + create_jsonrpc_routes(handler, "/"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9301)
    args = parser.parse_args()
    uvicorn.run(build(args.port), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
