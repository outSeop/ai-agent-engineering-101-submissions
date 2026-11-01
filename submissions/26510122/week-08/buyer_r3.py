"""A2A negotiation for one selected, in-stock Round 3 SKU."""

from __future__ import annotations

import re
import time
import uuid

import httpx

from harness import decide_json, trace


def status(task: dict) -> str:
    return task.get("status", {}).get("state", "")


def status_text(task: dict) -> str:
    parts = task.get("status", {}).get("message", {}).get("parts", [])
    return " ".join(p.get("text", "") for p in parts)


def asking_price(message: str) -> int | None:
    match = re.search(r"(?:asking|counteroffer|current ask)\s*:?\s*(\d+)", message, re.I)
    return int(match.group(1)) if match else None


def card_endpoint(client: httpx.Client, shop_url: str, deadline: float) -> str:
    response = client.get(shop_url.rstrip("/") + "/.well-known/agent-card.json",
                          timeout=min(15, max(1, deadline - time.monotonic())))
    response.raise_for_status()
    card = response.json()
    for interface in card.get("supportedInterfaces", []):
        if interface.get("protocolBinding") == "JSONRPC" and str(interface.get("protocolVersion")) == "1.0":
            return interface["url"]
    raise ValueError("shop has no A2A 1.0 JSON-RPC interface")


def send(client: httpx.Client, endpoint: str, message: str, deadline: float,
         task_id: str | None = None) -> dict:
    body = {"role": "ROLE_USER", "messageId": str(uuid.uuid4()), "parts": [{"text": message}]}
    if task_id:
        body["taskId"] = task_id
    response = client.post(endpoint, json={"jsonrpc": "2.0", "id": str(uuid.uuid4()),
                                           "method": "SendMessage", "params": {"message": body}},
                           headers={"A2A-Version": "1.0"},
                           timeout=min(85, max(1, deadline - time.monotonic())))
    response.raise_for_status()
    answer = response.json()
    if "error" in answer:
        raise ValueError(f"A2A error: {str(answer['error'])[:250]}")
    return answer["result"].get("task", answer["result"])


def get_receipt(task: dict) -> dict | None:
    for artifact in task.get("artifacts", []):
        for part in artifact.get("parts", []):
            data = part.get("data")
            if isinstance(data, dict) and data.get("sig_seller"):
                if isinstance(data.get("price"), float) and data["price"].is_integer():
                    data = dict(data, price=int(data["price"]))
                return data
    return None


def followup_offer(*, message: str, last_offer: int, cap: int, sku: str,
                   list_price: int, memory: dict, deadline: float) -> int | None:
    ask = asking_price(message)
    fallback = (ask if ask is not None and ask <= cap else
                min(cap, last_offer + max(1, (cap - last_offer) // 2)))
    if fallback <= last_offer and (ask is None or ask > cap):
        return None
    if deadline - time.monotonic() < 70:
        return fallback
    prompt = {"phase": "buyer_counter", "sku": sku, "list_price": list_price,
              "seller_message": message[:350], "last_offer": last_offer,
              "maximum_authorized_price": cap, "recent_memory": memory,
              "objective": "Choose the next offer or walk away. Keep positive buyer surplus. "
                           "A high asking price is negotiable; do not reveal the private mandate limit."}
    schema = {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["offer", "walk"]},
        "price": {"type": ["integer", "null"]}, "reason": {"type": "string"},
    }, "required": ["action", "price", "reason"], "additionalProperties": False}
    try:
        choice = decide_json("buyer negotiator", prompt, schema)
        if choice["action"] == "walk":
            return None
        proposed = choice.get("price")
        if type(proposed) is int:
            guarded = min(cap, max(1, proposed))
            trace("buyer_counter_choice", sku=sku, proposed=proposed, effective=guarded,
                  reason=choice["reason"])
            return guarded if guarded > last_offer or (ask is not None and guarded == ask) else fallback
    except Exception as error:
        trace("buyer_counter_fallback", error=type(error).__name__)
    return fallback


def negotiate(shop_url: str, sku: str, name: str, order: dict, *, opening_offer: int,
              cap: int, list_price: int, memory: dict, deadline: float) -> dict:
    """Return a received receipt and final offer, or a concrete failure reason."""
    offered: list[int] = []
    with httpx.Client() as client:
        endpoint = card_endpoint(client, shop_url, deadline)
        note = "A certificate is required."
        if order.get("kind") == "goods":
            note += " A six-hour warranty is preferred."
        task = send(client, endpoint, f"I want to buy {name} ({sku}). {note}", deadline)
        for turn in range(3):
            if status(task) != "TASK_STATE_INPUT_REQUIRED":
                break
            message = status_text(task)
            ask = asking_price(message)
            if turn == 0:
                offer = min(opening_offer, ask) if ask is not None and ask <= opening_offer else opening_offer
            else:
                offer = followup_offer(message=message, last_offer=offered[-1], cap=cap,
                                       sku=sku, list_price=list_price, memory=memory, deadline=deadline)
            if offer is None or deadline - time.monotonic() < 5:
                return {"receipt": None, "reason": "walked away or order deadline reached",
                        "offers": offered, "task_id": task.get("id")}
            offer = min(cap, max(1, int(offer)))
            offered.append(offer)
            trace("buyer_offer", sku=sku, shop=shop_url, offer=offer, turn=turn)
            task = send(client, endpoint, str(offer), deadline, task.get("id"))
        receipt = get_receipt(task) if status(task) == "TASK_STATE_COMPLETED" else None
        return {"receipt": receipt, "reason": "receipt received" if receipt else
                f"no receipt; seller state {status(task)}", "offers": offered,
                "task_id": task.get("id"), "last_seller_message": status_text(task)[:250]}
