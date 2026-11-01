"""Small, inspectable calculations for the Round 3 shop.

This module supplies price *candidates* and a replenishment quantity. The
seller harness chooses an action; the tool does not silently set its price.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from typing import Any


# Starting hypotheses, not values supplied by the lecture or the market.
GRADE_ANCHORS = {"A": 1.0, "B": 0.80, "C": 0.60}


def quote_candidates(unit: dict[str, Any], now: float | None = None) -> dict[str, Any]:
    """Return three grade-aware anchors and the unit economics behind them."""
    now = time.time() if now is None else now
    grade = unit.get("grade")
    if grade not in GRADE_ANCHORS:
        raise ValueError(f"unsupported grade: {grade!r}")
    cost, list_price = int(unit["cost"]), int(unit["list_price"])
    if cost <= 0 or list_price <= 0:
        raise ValueError("cost and list_price must be positive")
    anchor = list_price * GRADE_ANCHORS[grade]
    prices = sorted({max(1, round(anchor * factor)) for factor in (0.90, 1.0, 1.10)})
    expires = unit.get("expires_at")
    hours_left = max(0.0, (float(expires) - now) / 3600) if expires else None
    storage_day = round(cost * 0.01, 2) if unit.get("kind") == "goods" else 0.0
    return {
        "sku": unit["sku"], "unit": unit["unit"], "grade": grade,
        "kind": unit.get("kind"), "cost": cost, "list_price": list_price,
        "hours_left": round(hours_left, 2) if hours_left is not None else None,
        "storage_per_day": storage_day,
        "anchor_source": "unvalidated grade priors A=1.0, B=0.8, C=0.6 of list price",
        "candidates": [
            {"price": price, "margin_over_purchase_cost": price - cost,
             "below_purchase_cost": price < cost}
            for price in prices
        ],
    }


def poisson_pmf(mean: float, cap: int = 20) -> list[float]:
    """Demand 0..cap, with the final bucket including the upper tail."""
    if not math.isfinite(mean) or mean < 0 or cap < 1:
        raise ValueError("mean must be finite and nonnegative; cap must be positive")
    probs = [math.exp(-mean)]
    for n in range(1, cap):
        probs.append(probs[-1] * mean / n)
    probs.append(max(0.0, 1.0 - sum(probs)))
    return probs


def recommend_quantity(
    demand_pmf: list[float], price: int, cost: float, *,
    salvage: float = 0.0, holding_per_leftover: float = 0.0, max_qty: int = 20,
) -> dict[str, Any]:
    """Apply the discrete newsvendor rule, then report expected profit.

    The caller owns the demand forecast. A sale price does not come from this
    formula; demand_pmf must be estimated for that particular price and horizon.
    """
    if not demand_pmf or max_qty < 0 or type(price) is not int or price <= 0:
        raise ValueError("provide a demand PMF, positive integer price and max_qty >= 0")
    if any(not math.isfinite(x) or x < 0 for x in demand_pmf):
        raise ValueError("demand probabilities must be finite and nonnegative")
    if not math.isclose(sum(demand_pmf), 1.0, rel_tol=0, abs_tol=1e-6):
        raise ValueError("demand probabilities must sum to one")
    if not (0 <= salvage <= cost and holding_per_leftover >= 0):
        raise ValueError("require 0 <= salvage <= cost and nonnegative holding")
    underage = max(0.0, price - cost)
    overage = cost - salvage + holding_per_leftover
    ratio = underage / (underage + overage) if underage + overage else 0.0
    limit = min(max_qty, len(demand_pmf) - 1)
    cumulative = 0.0
    quantity = limit
    for q in range(limit + 1):
        cumulative += demand_pmf[q]
        if cumulative + 1e-12 >= ratio:
            quantity = q
            break

    def expected_profit(q: int) -> float:
        return sum(prob * (price * min(d, q) + salvage * max(q - d, 0)
                           - cost * q - holding_per_leftover * max(q - d, 0))
                   for d, prob in enumerate(demand_pmf))

    return {
        "quantity": quantity, "critical_ratio": round(ratio, 6),
        "underage_cost": round(underage, 2), "overage_cost": round(overage, 2),
        "expected_profit": round(expected_profit(quantity), 2),
        "horizon": "the horizon used to build demand_pmf",
        "price": price, "cost": cost, "salvage": salvage,
        "holding_per_leftover": holding_per_leftover,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Round 3 price candidates and newsvendor quantity")
    parser.add_argument("action", choices=("quote", "replenish"))
    args = parser.parse_args()
    payload = json.load(sys.stdin)
    result = (quote_candidates(payload["unit"])
              if args.action == "quote"
              else recommend_quantity(**payload))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
