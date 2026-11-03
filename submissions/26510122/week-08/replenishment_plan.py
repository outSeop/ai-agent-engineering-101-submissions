"""Bounded model-approved replenishment plans; execution never invents a target.

Quantity/spend budgets are reserved BEFORE returning a buy intent. If supply is
refused, that reservation is not silently restored. A new model approval is
needed once the plan expires or its authorized budget is exhausted.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import uuid

MAX_VALID_SECONDS = 600
MIN_BALANCE = 1_000_000
MAX_SKU_STOCK = 4
MAX_CATEGORY_STOCK = 6


def product_signature(product: dict) -> str:
    fields = {k: product.get(k) for k in ('kind', 'list_price', 'shelf_hours')}
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()


def save(path: Path, plan: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(plan, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def load(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def create(*, sku: str, product: dict, candidate: dict, approval: dict,
           observation: dict, now: float) -> dict:
    ttl, budget = approval.get('valid_for_seconds'), approval.get('max_total_qty')
    if type(ttl) is not int or not 60 <= ttl <= MAX_VALID_SECONDS:
        raise ValueError('approval must give a validity between 60 and 600 seconds')
    if type(budget) is not int or not candidate['qty'] <= budget <= 20:
        raise ValueError('approval must cover initial quantity with total budget <=20')
    if not candidate['qty'] <= candidate['target_stock'] <= MAX_SKU_STOCK:
        raise ValueError('target must fit the per-SKU portfolio limit')
    if observation['observed_visits'] < 5:
        budget = min(budget, 2)
    return {'version': 1, 'policy_version': 3, 'id': uuid.uuid4().hex, 'sku': sku, 'approved_at': now,
            'expires_at': now + ttl, 'target_stock': candidate['target_stock'],
            'max_initial_qty': candidate['qty'], 'max_total_qty': budget, 'emitted_qty': 0,
            'product_signature': product_signature(product),
            'cost_ceiling_per_unit': math.ceil(product['list_price'] * .75),
            'observed_no_stock_at_approval': observation['observed_no_stock_visits'],
            'observed_visit_rate_at_approval': observation['observed_visit_rate_while_stocked'],
            'approval': approval, 'candidate': candidate}


def execute(plan: dict, *, inventory: dict, product: dict, observation: dict,
            now: float, snapshot_time: float | None = None) -> tuple[dict | None, str]:
    """Return a bounded intent, or None when another model approval is required."""
    integer_fields = ('target_stock','max_initial_qty','max_total_qty','emitted_qty','cost_ceiling_per_unit')
    if any(type(plan.get(k)) not in (int,float) or not math.isfinite(plan[k]) for k in ('approved_at','expires_at')):
        return None, 'invalid_plan_time'
    if any(not isinstance(plan.get(k),str) or not plan[k] for k in ('id','sku','product_signature')):
        return None, 'invalid_plan_identity'
    if any(type(plan.get(k)) is not int or plan[k] < 0 for k in integer_fields):
        return None, 'invalid_plan_fields'
    if not (plan['target_stock'] <= MAX_SKU_STOCK and plan['max_initial_qty'] <= plan['max_total_qty'] <= 20
            and plan['emitted_qty'] <= plan['max_total_qty'] and plan['cost_ceiling_per_unit'] > 0):
        return None, 'invalid_plan_budget'
    if plan.get('policy_version') != 3:
        return None, 'portfolio_policy_changed'
    if plan.get('version') != 1 or not plan.get('approved_at', now+1) <= now < plan.get('expires_at', 0):
        return None, 'expired_or_invalid_plan'
    if not 60 <= plan['expires_at']-plan['approved_at'] <= MAX_VALID_SECONDS:
        return None, 'invalid_plan_validity'
    if plan.get('product_signature') != product_signature(product):
        return None, 'catalog_changed'
    stockout_times = observation.get('recent_stockout_times')
    new_stockouts = (sum(t >= plan['approved_at'] for t in stockout_times) if stockout_times is not None
                     else observation['observed_no_stock_visits']-plan['observed_no_stock_at_approval'])
    if new_stockouts >= 3:
        return None, 'new_stockout_evidence'
    baseline = plan.get('observed_visit_rate_at_approval')
    current = observation['observed_visit_rate_while_stocked']
    if baseline is not None and current is not None and abs(current-baseline) > max(1., baseline*.5):
        return None, 'observed_visit_rate_changed'
    if inventory.get('round') != 3:
        return None, 'wrong_round'
    if snapshot_time is not None and snapshot_time <= plan.get('last_intent_snapshot', -1):
        return {'buy':[]}, 'awaiting_inventory_refresh'
    live = [u for u in inventory.get('units', []) if u.get('grade') in ('A','B','C')
            and (u.get('expires_at') is None or u['expires_at'] > now)]
    own = [u for u in live if u.get('sku') == plan['sku']]
    known_grades = plan.get('unit_grades_at_approval',{})
    if any(u.get('unit') in known_grades and known_grades[u['unit']] != u.get('grade') for u in own):
        return None, 'grade_changed'
    if any(u.get('expires_at') is not None and u['expires_at']-now < 3600 for u in own):
        return None, 'expiry_requires_reassessment'
    plan['unit_grades_at_approval'] = {u['unit']:u.get('grade') for u in own if u.get('unit')}
    missing = max(0, plan['target_stock']-len(own))
    category = product.get('category')
    category_room = max(0, MAX_CATEGORY_STOCK - sum(u.get('category') == category for u in live)) if category else 20
    budget = max(0, plan['max_total_qty']-plan['emitted_qty'])
    if missing and not budget:
        return None, 'authorized_budget_exhausted'
    balance = inventory.get('balance')
    available = max(0, int(balance)-MIN_BALANCE) if type(balance) in (int,float) and math.isfinite(balance) else 0
    qty = min(missing, budget, plan['max_initial_qty'], category_room, 20-len(live), available//plan['cost_ceiling_per_unit'])
    qty = max(0, qty)
    plan['emitted_qty'] += qty
    if qty and snapshot_time is not None:
        plan['last_intent_snapshot'] = snapshot_time
    return ({'buy': [{'sku': plan['sku'], 'qty': qty}]} if qty else {'buy': []}), 'approved_plan'
