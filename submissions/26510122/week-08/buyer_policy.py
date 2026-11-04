"""Buyer-side value and checkout guards for Round 3.

The discount ratios are initial hypotheses, not published demand or breakage
rates. Settlement logs can support revisions after Round 3 opens.
"""

from __future__ import annotations

import math


FOOD_MAX_SHARE = 0.85
GOODS_MAX_SHARE = 0.75
CHECKOUT_BUFFER_SECONDS = 120


def shelf_minimum(order: dict) -> float:
    """Exact mandate horizon at checkout; no proportional private requirement."""
    required = float(order.get("use_within_hours") or 0)
    if not math.isfinite(required) or required<0: raise ValueError('invalid use_within_hours')
    return required


def quote_shelf_minimum(order: dict) -> float:
    """Request two minutes of transaction headroom, independently of shelf length."""
    return round(shelf_minimum(order)+CHECKOUT_BUFFER_SECONDS/3600,6)


def price_cap(order: dict, product: dict) -> int:
    """Protect the private mandate and a provisional positive surplus margin."""
    if not isinstance(product, dict) or type(product.get("list_price")) is not int:
        return 0
    list_price = product["list_price"]
    budget = order.get("budget")
    if type(budget) is not int or budget <= 0 or list_price <= 0:
        return 0
    kind = order.get("kind")
    if product.get("kind") != kind:
        return 0
    if kind == "food":
        shelf = product.get("shelf_hours")
        if not isinstance(shelf, (int, float)) or shelf < shelf_minimum(order):
            return 0
        ratio = FOOD_MAX_SHARE
    elif kind == "goods":
        ratio = GOODS_MAX_SHARE
    else:
        return 0
    return min(budget, math.floor(list_price * ratio))


def acceptance(order: dict, receipt: dict | None = None) -> dict:
    """The kit checks these against the seller's signed checkout before paying."""
    policy: dict = {"cert": True}
    if order.get("kind") == "food":
        policy["min_hours_left"] = shelf_minimum(order)
    else:
        policy["grades"] = ["A", "B"]
        if isinstance(receipt, dict) and isinstance(receipt.get("warranty_hours"), (int, float)) \
                and receipt["warranty_hours"] >= 6:
            policy["warranty_hours"] = 6
    return policy


def receipt_problem(receipt: dict | None, *, selected_sku: str, order: dict,
                    final_offer: int, task_id: str | None, cap: int) -> str | None:
    """Local checks before handing the receipt to the kit's signature and AP2 checks."""
    if not isinstance(receipt, dict):
        return "no receipt"
    if receipt.get("item") != selected_sku or selected_sku not in order.get("acceptable", []):
        return "receipt SKU differs from the selected acceptable SKU"
    price = receipt.get("price")
    if type(price) is not int or price <= 0 or price != final_offer or price > cap:
        return "receipt price differs from the final offer or price cap"
    if not task_id or receipt.get("task") != task_id:
        return "receipt task ID differs from the negotiation"
    if not receipt.get("sig_seller"):
        return "seller signature missing"
    return None
