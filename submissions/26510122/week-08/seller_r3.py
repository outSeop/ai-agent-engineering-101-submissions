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
from google.protobuf.json_format import MessageToDict

from a2a.helpers import get_message_text, new_data_part, new_task_from_user_message, new_text_part
from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill

from harness import decide_json, trace
from market_memory import compact_context, events, record, sync_settlements
from newsvendor_tool import quote_candidates
from inventory_observation import requested_skus
from context_compaction import MAX_TURNS
import buyer_identity
import counterparty_memory
from newsvendor_tool import GRADE_ANCHORS
from seller_state import SellerState, SQLiteTaskStore, ResumingContextBuilder
import seller_requirements


NAME = "outseop-26510122"
SELLER_DESCRIPTION = (
    "Brief quotes help save tokens. Negotiable prices; counteroffers welcome. "
    "Clear prices and checkout certificates. Stocked products. "
    "Numeric offers; signed receipts on agreement."
)
MARKET_DIR = Path(os.environ.get("MARKET_DIR", ".market"))
RESERVE = {"lamp": 100, "chair": 180, "bookshelf": 260}  # pre-Round-3 compatibility
HOLD_SECONDS = 600
NEGOTIATION_IDLE_SECONDS = 300
NEGOTIATION_MAX_SECONDS = 900


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
    def __init__(self, state=None) -> None:
        self.state = state or SellerState()
        history = events()
        self.state.import_receipt_holds(history, HOLD_SECONDS)
        self.open: dict[str, dict] = self.state.restore_deals()
        self.holds: dict[str, float] = {}  # signed receipts awaiting checkout/settlement
        self.identity_messages: dict[str,float] = {}
        self.task_locks = {}

    def expire_negotiations(self, now=None):
        now=time.monotonic() if now is None else now
        for task_id,deal in list(self.open.items()):
            last=deal.get('last_activity',now)
            opened=deal.get('opened_monotonic',last)
            if now-last>=NEGOTIATION_IDLE_SECONDS or now-opened>=NEGOTIATION_MAX_SECONDS:
                del self.open[task_id]
                self.state.close_deal(task_id)
                record('negotiation_expired',task_id=task_id,sku=deal['unit']['sku'],unit=deal['unit']['unit'],
                       reason='negotiation reservation timed out; payment outcome unknown')

    def available(self, text: str) -> list[dict]:
        self.expire_negotiations()
        inventory = read_inventory()
        stock = {u.get("unit") for u in inventory.get("units", [])}
        now = time.monotonic()
        leases = self.state.active_leases(events())
        for unit, _, kind, until in leases:
            if kind == 'receipt':
                self.holds[unit] = now + max(0, until-time.time())
        self.holds = {unit: until for unit, until in self.holds.items()
                      if until > now and (not stock or unit in stock)}
        taken = {d["unit"]["unit"] for d in self.open.values()} | set(self.holds) | {r[0] for r in leases}
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
        key = context.current_task.id if context.current_task else context.message.message_id
        lock = self.task_locks.setdefault(key, asyncio.Lock())
        async with lock:
            await self._execute(context, event_queue)

    async def _execute(self, context, event_queue) -> None:
        task = context.current_task
        new_task = task is None
        if task is None:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)
        up = TaskUpdater(event_queue=event_queue, task_id=task.id, context_id=task.context_id)
        def say(message):
            record('seller_message',task_id=task.id,text=message)
            return up.new_agent_message(parts=[new_text_part(message)])
        message = get_message_text(context.message) or ""
        record('buyer_message',task_id=task.id,text=message)
        self.expire_negotiations()
        deal = self.open.get(task.id)
        if not new_task and deal is None:
            receipt = self.state.pending_receipt(task.id)
            if receipt is not None:
                current = read_inventory()
                unit = next((u for u in current.get('units', []) if u.get('unit') == receipt['unit']), None)
                saved = self.state.requirements_for(task.id) or seller_requirements.initial('')
                if current.get('round') == 3 and (unit is None or seller_requirements.violations(unit, saved, time.time())):
                    await up.reject(say('The saved receipt unit no longer meets the purchase conditions.'))
                    return
                await up.add_artifact(parts=[new_data_part(receipt)], name='receipt')
                await up.complete(say('Previously agreed receipt; price and unit unchanged.'))
                return
            await up.reject(say('This negotiation is no longer active. Please start a new purchase request.'))
            return
        if deal is not None:
            deal['last_activity'] = time.monotonic()
            deal['last_activity_at'] = time.time()
            deal['requirements'] = seller_requirements.update(deal.get('requirements', seller_requirements.initial('')), message)
            if not self.state.save_deal(task.id, deal, create=False):
                self.open.pop(task.id, None)
                await up.reject(say('That reservation is no longer active. Please start a new request.'))
                return

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
            requirements = seller_requirements.initial(message)
            choices = [u for u in choices if not seller_requirements.violations(u, requirements, time.time())]
            if not choices:
                record('requirements_unmet', task_id=task.id, requirements=requirements)
                await up.reject(say('No available unit meets the requested expiry, grade or warranty.'))
                return
            metadata=context.metadata or MessageToDict(context.message.metadata)
            history=events()
            proofs=counterparty_memory.load_cache().get('proofs',[])
            linked={e.get('task_id') for e in history if e['event']=='buyer_link'}
            unlinked=any(e['event']=='receipt_signed' and e.get('task_id') not in linked for e in history)
            if metadata.get('buyer_identity') or metadata.get('buyer_name') or unlinked:
                proofs=await asyncio.to_thread(counterparty_memory.refresh,NAME)
                history=events()
            identity=buyer_identity.identify(metadata,recipient=NAME,message_id=context.message.message_id,
                                             task_id=None if new_task else task.id,message=message,proofs=proofs)
            now=time.time()
            self.identity_messages={mid:at for mid,at in self.identity_messages.items() if now-at<300}
            if identity['verified']:
                if context.message.message_id in self.identity_messages:
                    identity={**identity,'status':'replayed_identity_message','verified':False}
                else:
                    if len(self.identity_messages)>=512:self.identity_messages.pop(next(iter(self.identity_messages)))
                    self.identity_messages[context.message.message_id]=now
            record('buyer_identity_observed',task_id=task.id,**identity)
            tools = [quote_candidates(u) for u in choices]
            keys=list(dict.fromkeys((u['sku'],u['grade']) for u in choices))
            per_key=min(3600,12000//len(keys)-64)
            memories={f'{sku}:{grade}':compact_context(sku,grade,max_bytes=per_key) for sku,grade in keys}
            for tool in tools:
                tool['memory_key']=f"{tool['sku']}:{tool['grade']}"
            profiles={}
            profiles_by_unit={}
            for unit,tool in zip(choices,tools):
                remaining=(unit['expires_at']-now)/3600 if unit.get('expires_at') is not None else None
                bucket='unknown' if remaining is None else 'near_expiry' if remaining<=3 else 'not_near_expiry'
                key=f"{unit['sku']}:{unit['grade']}:{bucket}"
                if key not in profiles:
                    profiles[key]=counterparty_memory.profile(identity,unit,history=history,now=now)
                profiles_by_unit[unit['unit']]=profiles[key]
                tool['buyer_evidence_key']=key
                if profiles[key]['eligible_for_price_probe']:
                    tool['buyer_price_candidates']=profiles[key]['price_candidates']
            prompt = {
                "phase": "opening", "task_id": task.id, "buyer_message": message[:500],
                'purchase_requirements': requirements,
                "objective": "Choose one available physical unit and an opening price. "
                             "Use the calculation-tool candidates and market memory as evidence; "
                             "you may choose another positive price when you explain why. "
                             "A signed receipt is not a settled sale. Buyer-specific higher quotes are optional "
                             "experiments ONLY for eligible, market-linked signed identities. Use actual calm "
                             "high-price settlements under comparable conditions, not a permanent buyer label "
                             "or an assumed private budget. Unverified/unknown buyers use ordinary evidence. "
                             "Respect failed or unresolved price probes; never reprice an already agreed receipt.",
                "unit_options": tools, "memory_by_sku_grade": memories,
                'buyer_identity':identity,'buyer_price_evidence':profiles,
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
            errors = seller_requirements.violations(unit, requirements, time.time())
            if errors:
                record('requirements_unmet', task_id=task.id, errors=errors)
                await up.reject(say('That unit no longer meets the requested conditions. Please start a new request.'))
                return
            proposed = answer.get("price")
            maximum = max(1, 2 * int(unit["list_price"]))
            ask = min(maximum, max(1, int(proposed))) if type(proposed) is int else middle
            if ask != proposed or unit["unit"] != answer.get("unit_id"):
                trace("decision_guard", phase="opening", proposed_price=proposed,
                      effective_price=ask, proposed_unit=answer.get("unit_id"),
                      effective_unit=unit["unit"])
            self.open[task.id] = deal = {
                "unit": unit, "ask": ask, "history": [], "opened_at": time.time(),
                'opened_monotonic':time.monotonic(),'last_activity':time.monotonic(),
                'buyer_identity':identity,'buyer_price_evidence':profiles_by_unit[unit['unit']],
                'last_activity_at':time.time(), 'requirements':requirements,
            }
            if not self.state.save_deal(task.id, deal):
                del self.open[task.id]
                await up.reject(say('That unit was reserved by another purchase. Please try again.'))
                return
            record("opening", task_id=task.id, sku=unit["sku"], unit=unit["unit"],
                   category=unit.get("category"), grade=unit["grade"], kind=unit.get("kind"),
                   cost=unit["cost"], list_price=unit["list_price"], ask=ask,
                   expires_at=unit.get("expires_at"))
            evidence=profiles_by_unit[unit['unit']]
            ordinary=unit['list_price']*GRADE_ANCHORS[unit['grade']]
            if evidence['eligible_for_price_probe'] and ask>ordinary*1.025:
                remaining=(unit['expires_at']-now)/3600 if unit.get('expires_at') is not None else None
                record('buyer_price_probe',task_id=task.id,buyer_name=identity['buyer_name'],sku=unit['sku'],
                       grade=unit['grade'],price=ask,baseline_anchor=ordinary,
                       expiry_bucket='unknown' if remaining is None else 'near_expiry' if remaining<=3 else 'not_near_expiry',
                       evidence_count=evidence['calm_high_paid'])
            trace("seller_open", task_id=task.id, sku=unit["sku"], unit=unit["unit"],
                  grade=unit["grade"], cost=unit["cost"], ask=ask)
            await up.requires_input(say(f"{unit['name']}: asking {ask}. Short replies save tokens; send a number."))
            return

        offer = seller_requirements.offer(message)
        unit = deal["unit"]
        current = read_inventory()
        if current.get("round", 0) >= 3:
            fresh = next((u for u in current.get("units", [])
                          if u.get("unit") == unit["unit"] and u.get("grade") != "expired"), None)
            if fresh is None:
                record("stale_inventory", task_id=task.id, unit=unit["unit"])
                await up.reject(say("That unit is no longer available."))
                del self.open[task.id]
                self.state.close_deal(task.id)
                return
            unit = deal["unit"] = fresh
        errors = seller_requirements.violations(unit, deal['requirements'], time.time())
        if errors:
            record('requirements_unmet', task_id=task.id, errors=errors)
            self.state.close_deal(task.id)
            del self.open[task.id]
            await up.reject(say('This unit cannot meet your current requirements: '+ '; '.join(errors)+'. Please start a new request.'))
            return
        if offer is None:
            self.state.save_deal(task.id, deal, create=False)
            await up.requires_input(say(f"Conditions saved. Please send one clear price offer. Current ask: {deal['ask']}"))
            return
        record("offer", task_id=task.id, sku=unit["sku"], unit=unit["unit"], price=offer,
               grade=unit['grade'],cost=unit['cost'],expires_at=unit.get('expires_at'))
        deal["history"].append({"buyer_offer": offer, "seller_ask": deal["ask"]})
        self.state.save_deal(task.id, deal, create=False)
        memory = compact_context(unit["sku"], unit["grade"])
        prompt = {
            "phase": "follow_up", "task_id": task.id,
            "unit": quote_candidates(unit), "current_ask": deal["ask"],
            "buyer_offer": offer, "history": deal["history"][-MAX_TURNS:], "memory": memory,
            'buyer_price_evidence':deal.get('buyer_price_evidence'),
            'purchase_requirements':deal['requirements'], 'buyer_message':message[:500],
            "objective": "Accept, counter or reject. Consider purchase cost, grade, "
                         "food expiry and goods storage, but do not treat purchase cost "
                         "as an absolute floor for food already near expiry. "
                         "A receipt counts only if checkout later settles. The buyer profile is a hypothesis; "
                         "a new low offer is evidence against the tested price. Do not escalate mechanically.",
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
                self.state.close_deal(task.id)
                return
            unit = fresh
        errors = seller_requirements.violations(unit, deal['requirements'], time.time())
        if errors:
            record('requirements_unmet', task_id=task.id, errors=errors)
            self.state.close_deal(task.id)
            del self.open[task.id]
            await up.reject(say('The unit no longer meets your saved purchase conditions. Please start a new request.'))
            return
        action = answer["action"]
        if action == "accept" and offer > 0:
            receipt = sign({"shop": NAME, "item": unit["sku"], "price": offer,
                            "task": task.id, "unit": unit["unit"]})
            if not self.state.commit_receipt(task.id, receipt, HOLD_SECONDS):
                self.open.pop(task.id, None)
                await up.reject(say('That unit reservation expired. Please start a new request.'))
                return
            self.holds[unit['unit']] = time.monotonic() + HOLD_SECONDS
            await up.add_artifact(parts=[new_data_part(receipt)], name="receipt")
            record("receipt_signed", task_id=task.id, sku=unit["sku"], unit=unit["unit"],
                   grade=unit["grade"], price=offer,cost=unit['cost'],expires_at=unit.get('expires_at'))
            self.holds[unit["unit"]] = time.monotonic() + HOLD_SECONDS
            await up.complete(say(f"Deal: {unit['name']} at {offer}."))
            trace("seller_receipt", task_id=task.id, unit=unit["unit"], price=offer,
                  status="pending settlement")
            del self.open[task.id]
            self.state.close_deal(task.id)
            return
        if action == "reject":
            record("rejected", task_id=task.id, sku=unit["sku"], unit=unit["unit"],
                   price=offer, reason=answer["reason"])
            await up.reject(say("No deal."))
            del self.open[task.id]
            self.state.close_deal(task.id)
            return
        proposed = answer.get("price")
        maximum = max(1, 2 * int(unit["list_price"]))
        ask = min(maximum, max(1, int(proposed))) if type(proposed) is int else deal["ask"]
        if ask != proposed:
            trace("decision_guard", phase="follow_up", proposed_price=proposed, effective_price=ask)
        deal["ask"] = ask
        if not self.state.save_deal(task.id, deal, create=False):
            self.open.pop(task.id, None)
            return
        record("counter", task_id=task.id, sku=unit["sku"], unit=unit["unit"],
               buyer_offer=offer, ask=ask)
        trace("seller_counter", task_id=task.id, sku=unit["sku"], offer=offer, ask=ask)
        await up.requires_input(say(f"Counteroffer: {ask}."))

    async def cancel(self, context, event_queue) -> None:
        task = context.current_task
        if task is None:
            return
        deal = self.open.pop(task.id, None)
        self.state.close_deal(task.id)
        record("cancelled", task_id=task.id, sku=deal["unit"]["sku"] if deal else None)
        await TaskUpdater(event_queue=event_queue, task_id=task.id, context_id=task.context_id).cancel()


def build(port: int) -> Starlette:
    url = f"http://127.0.0.1:{port}/"
    card = AgentCard(
        name=NAME,
        description=SELLER_DESCRIPTION,
        version="1.0.0",
        default_input_modes=["text/plain"],
        default_output_modes=["application/json", "text/plain"],
        capabilities=AgentCapabilities(streaming=False),
        supported_interfaces=[AgentInterface(protocol_binding="JSONRPC", url=url, protocol_version="1.0")],
        skills=[AgentSkill(id="negotiate", name="Negotiate a stocked purchase",
                           description="Ask for a stocked product by SKU or name, then send a numeric offer. "
                                       "We keep replies brief.",
                           tags=["shopping", "negotiation", "signed-receipt"],
                           examples=["I want to buy G00001", "52000"])],
    )
    state = SellerState()
    task_store = SQLiteTaskStore(state)
    handler = DefaultRequestHandler(agent_executor=Seller(state), task_store=task_store, agent_card=card,
                                    request_context_builder=ResumingContextBuilder(task_store=task_store))
    return Starlette(routes=create_agent_card_routes(card) + create_jsonrpc_routes(handler, "/"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9301)
    args = parser.parse_args()
    uvicorn.run(build(args.port), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
