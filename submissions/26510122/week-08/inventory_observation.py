"""First-hand inventory evidence, with explicit gaps and censored demand.

Visits are a selected sample, not all buyer requests. A catalog category is not a
demand count. Missing snapshots never imply zero demand or continuous exposure.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import math
from pathlib import Path
import re

from market_memory import record

MAX_SNAPSHOT_GAP = 120.0
MAX_SNAPSHOT_AGE = 30.0


def timestamp(value) -> float | None:
    if type(value) in (int, float):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
        except ValueError:
            pass
    return None


def requested_skus(text: str, catalog: dict) -> list[str]:
    """Attribute only exact SKU tokens or an unambiguous full product name."""
    text = text.casefold()
    exact = [sku for sku in catalog if sku.casefold() in text and
             re.search(r'(?<![\w-])' + re.escape(sku.casefold()) + r'(?![\w-])', text)]
    if exact:
        return exact[:10]
    names = [sku for sku, product in catalog.items() if isinstance(product, dict)
             and isinstance(product.get('name'), str) and len(product['name']) >= 6
             and product['name'].casefold() in text]
    return names if len(names) == 1 else []


def snapshot(inventory: dict, source: Path, history: list[dict], now: float) -> bool:
    try:
        source_time = source.stat().st_mtime
    except OSError:
        return False
    if not 0 <= now - source_time <= MAX_SNAPSHOT_AGE:
        return False
    previous = next((e for e in reversed(history) if e['event'] == 'inventory_snapshot'), {})
    if previous.get('source_time') == source_time:
        return False
    stock = defaultdict(lambda: {'qty': 0, 'grades': {}})
    for u in inventory.get('units', []):
        if not u.get('sku') or u.get('grade') not in ('A', 'B', 'C'):
            continue
        if u.get('expires_at') is not None and u['expires_at'] <= now:
            continue
        row = stock[u['sku']]
        row['qty'] += 1
        row['grades'][u['grade']] = row['grades'].get(u['grade'], 0) + 1
    record('inventory_snapshot', source_time=source_time, round=inventory.get('round'), stock=dict(stock))
    return True


def evidence(sku: str, history: list[dict], now: float, hours: float = 12.) -> dict:
    start = now - hours * 3600
    visits, settled, no_stock = {}, set(), {}
    snapshots = {}
    unattributed = set()
    for row in history:
        at = timestamp(row.get('at'))
        if row['event'] == 'inventory_snapshot' and row.get('round') == 3:
            t = timestamp(row.get('source_time'))
            if t is not None and start - MAX_SNAPSHOT_GAP <= t <= now:
                snapshots[t] = row.get('stock', {})
        if at is None or not start <= at <= now:
            continue
        task = row.get('task_id')
        if row['event'] == 'request_seen' and task and sku in row.get('requested_skus', []):
            visits.setdefault(task, at)
        elif row['event'] == 'opening' and task and row.get('sku') == sku:
            visits.setdefault(task, at)
        elif row['event'] == 'no_stock' and task:
            if sku in row.get('requested_skus', []):
                no_stock.setdefault(task, at); visits.setdefault(task, at)
            elif not row.get('requested_skus'):
                unattributed.add(task)
        elif row['event'] == 'settled' and row.get('sku') == sku and row.get('ledger') is not None:
            settled.add(row['ledger'])
    coverage, exposure, stocked_intervals = 0., 0., []
    times = sorted(snapshots)
    for a, b in zip(times, times[1:]):
        if b - a > MAX_SNAPSHOT_GAP:
            continue
        duration = max(0., min(now, b) - max(start, a))
        coverage += duration
        if snapshots[a].get(sku, {}).get('qty', 0) > 0:
            exposure += duration
            stocked_intervals.append((max(start, a), min(now, b)))
    in_stock_visits = 0
    for at in visits.values():
        if any(a <= at < b for a, b in stocked_intervals):
            in_stock_visits += 1
    return {'window_hours': hours, 'observed_visits': len(visits),
            'observed_no_stock_visits': len(no_stock), 'confirmed_settlements': len(settled),
            'recent_stockout_times': sorted(no_stock.values())[-10:],
            'snapshot_coverage_hours': round(coverage / 3600, 4),
            'in_stock_exposure_hours': round(exposure / 3600, 4),
            'visits_during_observed_stock': in_stock_visits,
            'observed_visit_rate_while_stocked': round(in_stock_visits / (exposure / 3600), 3) if exposure >= 300 else None,
            'unattributed_no_stock_visits': len(unattributed),
            'total_demand': None, 'demand_is_censored': True,
            'caution': 'Selected shop visits only; stock snapshots do not prove listing visibility. '
                       'Unobserved requests and time gaps are unknown, not zero. '
                       'Public demand.json is a category catalog, not demand frequency.'}
