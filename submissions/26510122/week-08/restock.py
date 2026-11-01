"""Model-selected food SKU and demand scenario; newsvendor computes the lot size.

The market draws grade and actual cost only when the lot arrives. The cost used
here is the documented grade-weighted midpoint, and the forecast is labeled as
an estimate. Small caps protect the initial period with little evidence.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import random
import time

import httpx

from harness import decide_json, trace
from market_memory import events, record, sync_settlements
from newsvendor_tool import poisson_pmf, recommend_quantity


COOLDOWN = Path("state/restock-cooldown.json")
MIN_BALANCE = 1_000_000
STARTUP_MAX_BUY = 2


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def fetch_market_sales() -> Counter:
    """Recent public Round 3 settlements, not a complete demand observation."""
    response = httpx.get("https://market.ourolabs.ai/api/ledger?after=-500", timeout=5.0)
    response.raise_for_status()
    page = response.json()
    if not isinstance(page, list):
        raise ValueError("unexpected public ledger response")
    return Counter(entry.get("data", {}).get("item") for entry in page
                   if isinstance(entry, dict) and entry.get("round") == 3
                   and entry.get("kind") == "settle"
                   and isinstance(entry.get("data"), dict)
                   and isinstance(entry["data"].get("item"), str))


def choose_candidates(catalog: dict, inventory: dict, history: list[dict],
                      market_sales: Counter | None = None) -> list[dict]:
    """Expose a bounded exploratory set plus SKUs with first-hand evidence."""
    market_sales = market_sales or Counter()
    counts = Counter(e.get("sku") for e in history if e.get("event") == "opening" and e.get("sku"))
    settled = Counter(e.get("sku") for e in history if e.get("event") == "settled" and e.get("sku"))
    stocked = Counter(u.get("sku") for u in inventory.get("units", []) if u.get("grade") != "expired")
    food = {sku: data for sku, data in catalog.items()
            if isinstance(data, dict) and data.get("kind") == "food"
            and isinstance(data.get("list_price"), int) and data["list_price"] > 0
            and (data.get("shelf_hours") or 0) >= 24}
    if not food:
        return []
    public = [sku for sku, _ in market_sales.most_common(8) if sku in food]
    explored = [sku for sku, _ in counts.most_common(8) if sku in food]
    seed = int(time.time() // 3600)
    sampled = random.Random(seed).sample(sorted(food), min(16, len(food)))
    selected = list(dict.fromkeys(public + explored + sampled))[:20]
    return [{"sku": sku, "name": food[sku].get("name", sku),
             "category": food[sku].get("category"),
             "list_price": food[sku]["list_price"],
             "shelf_hours": food[sku]["shelf_hours"],
             "currently_stocked": stocked[sku], "observed_shop_requests": counts[sku],
             "confirmed_settlements": settled[sku],
             "recent_public_settlements": market_sales[sku]} for sku in selected]


def decision_schema() -> dict:
    return {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["buy", "hold"]},
        "sku": {"type": ["string", "null"]},
        "expected_sale_price": {"type": ["integer", "null"]},
        "demand_mean": {"type": ["number", "null"]},
        "reason": {"type": "string"},
    }, "required": ["action", "sku", "expected_sale_price", "demand_mean", "reason"],
        "additionalProperties": False}


def run(state: Path) -> dict:
    inventory = load_json(state / "inventory.json", {})
    if inventory.get("round", 0) < 3:
        return {"buy": []}
    live_units = [u for u in inventory.get("units", []) if u.get("grade") != "expired"]
    if len(live_units) >= 20:
        return {"buy": []}
    try:
        imported = sync_settlements()
        if imported:
            trace("settlements_imported", count=imported)
    except OSError as error:
        trace("settlement_sync_error", error=str(error))
    history = events()
    catalog = load_json(state / "catalog.json", {})
    try:
        public_sales = fetch_market_sales()
    except (httpx.HTTPError, ValueError) as error:
        trace("market_signal_unavailable", error=type(error).__name__)
        public_sales = Counter()
    candidates = choose_candidates(catalog, inventory, history, public_sales)
    if not candidates:
        return {"buy": []}
    cooldown = load_json(COOLDOWN, {})
    if time.time() - cooldown.get("at", 0) < 180:
        return {"buy": []}
    recent = [{"event": e["event"], "sku": e.get("sku"), "price": e.get("price"),
               "ask": e.get("ask"), "grade": e.get("grade")}
              for e in history[-30:] if e["event"] in {"opening", "receipt_signed", "settled", "rejected"}]
    prompt = {
        "phase": "restock", "task_id": f"restock-{int(time.time())}",
        "balance": inventory.get("balance"), "candidate_food_skus": candidates,
        "recent_first_hand_evidence": recent,
        "objective": "Choose a food SKU to replenish, or hold. Estimate a sale price and "
                     "demand mean over the conservative horizon of one quarter of its "
                     "listed shelf life, capped at 24 hours. The market has not published "
                     "demand weights. Public settlements are sales, not all demand; "
                     "a shop request is only an observed visit. With sparse evidence "
                     "choose a low estimate and a "
                     "small exploratory lot. The newsvendor tool will choose quantity.",
    }
    try:
        decision = decide_json("restocking agent", prompt, decision_schema())
        fallback = False
    except Exception as error:
        trace("restock_model_fallback", error=type(error).__name__, reason=str(error)[-400:])
        decision = {"action": "hold", "sku": None, "expected_sale_price": None,
                    "demand_mean": None, "reason": "model unavailable; avoid speculative purchase"}
        fallback = True
    COOLDOWN.parent.mkdir(parents=True, exist_ok=True)
    COOLDOWN.write_text(json.dumps({"at": time.time(), "sku": decision.get("sku")}),
                        encoding="utf-8")
    selected = next((c for c in candidates if c["sku"] == decision.get("sku")), None)
    if decision["action"] != "buy" or selected is None:
        record("restock_decision", action="hold", model_choice=decision, fallback=fallback)
        return {"buy": []}
    list_price = selected["list_price"]
    proposed_price = decision.get("expected_sale_price")
    price = (max(1, min(2 * list_price, proposed_price))
             if type(proposed_price) is int else round(list_price * 0.8))
    proposed_mean = decision.get("demand_mean")
    mean = float(proposed_mean) if type(proposed_mean) in (int, float) and math.isfinite(proposed_mean) else 0.0
    mean = max(0.0, min(mean, 1.5 if selected["observed_shop_requests"] < 5 else 10.0))
    # Food grade probabilities: A .25, B .50, C .25. Midpoint cost shares:
    # A .65, B .50, C .35, giving an expected purchase cost of .50 list price.
    expected_cost = round(list_price * 0.50)
    horizon_hours = min(24.0, selected["shelf_hours"] * 0.25)
    calculation = recommend_quantity(poisson_pmf(mean), price, expected_cost,
                                     salvage=0.0, max_qty=20)
    desired = max(0, calculation["quantity"] - selected["currently_stocked"])
    if selected["observed_shop_requests"] < 5:
        desired = min(desired, STARTUP_MAX_BUY)
    balance = max(0, int(inventory.get("balance") or 0) - MIN_BALANCE)
    affordable = int(balance // math.ceil(list_price * 0.75))
    qty = min(desired, affordable, 20 - len(live_units))
    record("restock_decision", action="buy" if qty else "hold", sku=selected["sku"],
           expected_sale_price=price, expected_cost=expected_cost,
           horizon_hours=round(horizon_hours, 2), forecast_mean=mean,
           calculation=calculation, qty=qty, model_choice=decision, fallback=fallback)
    trace("newsvendor_calculation", sku=selected["sku"], quantity=calculation["quantity"],
          buy_now=qty, critical_ratio=calculation["critical_ratio"],
          forecast_mean=mean, horizon_hours=round(horizon_hours, 2))
    return {"buy": [{"sku": selected["sku"], "qty": qty}]} if qty else {"buy": []}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.state)
    print(json.dumps(result, ensure_ascii=False))   # kit reads the last JSON line


if __name__ == "__main__":
    main()
