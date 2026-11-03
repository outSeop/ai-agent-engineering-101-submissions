"""First-hand sales evidence and explicit inventory-depth alternatives."""
from collections import Counter
import math

from inventory_observation import timestamp
from newsvendor_tool import poisson_pmf, recommend_quantity

PROVEN_STOCK = 6
NEW_STOCK = 2


def sales_evidence(sku, history, now):
    costs = {e['unit']: e['cost'] for e in history if e.get('event') == 'receipt_signed'
             and e.get('unit') and type(e.get('cost')) in (int, float) and e['cost'] > 0}
    settled = {e['ledger']: e for e in history if e.get('event') == 'settled' and e.get('sku') == sku
               and e.get('ledger') is not None and (timestamp(e.get('at')) or 0) >= now-12*3600
               and (timestamp(e.get('at')) or math.inf) <= now}
    positive = [e for e in settled.values() if e.get('unit') in costs and e.get('price', 0) > costs[e['unit']]]
    recent = [e for e in positive if timestamp(e['at']) >= now-3600]
    spread = sum(e['price']-costs[e['unit']] for e in settled.values() if e.get('unit') in costs)
    proven = len(positive) >= 3 and bool(recent) and spread > 0
    return {'confirmed_positive_spread_sales_12h': len(positive), 'confirmed_positive_spread_sales_1h': len(recent),
            'spread_before_holding_refunds_12h': spread, 'proven': proven,
            'stock_limit': PROVEN_STOCK if proven else NEW_STOCK,
            'caution': 'Shop settlements are selected observations; positive acquisition spread excludes holding and refunds.'}


def replenishment_candidates(catalog, inventory, history, now, blocked=()):
    units = [u for u in inventory.get('units', []) if u.get('grade') in ('A', 'B', 'C')
             and (u.get('expires_at') is None or u['expires_at'] > now)]
    stocks = Counter(u['sku'] for u in units)
    categories = Counter(u.get('category') for u in units)
    sold_skus = {e.get('sku') for e in history if e.get('event') == 'settled' and e.get('sku')}
    rows = []
    for sku in sold_skus:
        p = catalog.get(sku)
        if sku in blocked or not isinstance(p, dict) or p.get('kind') not in ('food', 'goods'):
            continue
        signal = sales_evidence(sku, history, now)
        price = p.get('list_price')
        if (not signal['proven'] or stocks[sku] >= PROVEN_STOCK or type(price) is not int
                or price <= 0 or math.ceil(price*.75) > 250_000):
            continue
        if p['kind'] == 'food' and (p.get('shelf_hours') or 0) < 48:
            continue
        room = max(0, 6-categories[p.get('category')])
        estimated_cost = round(price*(.50 if p['kind'] == 'food' else .59))
        estimated_price = max(1, round(price*(.80 if p['kind'] == 'food' else .92)))
        mean = signal['confirmed_positive_spread_sales_1h']
        calculation = recommend_quantity(poisson_pmf(mean), estimated_price, estimated_cost,
                                         holding_per_leftover=estimated_cost*.01/24 if p['kind']=='goods' else 0,
                                         max_qty=PROVEN_STOCK)
        options = []
        for target in (4, 6):
            qty = max(0, target-stocks[sku])
            if 0 < qty <= room and not any(o['qty']==qty for o in options):
                options.append({'target_stock': stocks[sku]+qty, 'qty': qty,
                                'cost_ceiling': math.ceil(price*.75)*qty})
        if not options:
            continue
        rows.append({'sku': sku, 'name': p.get('name', sku), 'kind': p['kind'], 'category': p.get('category'),
                     'currently_stocked': stocks[sku], 'evidence': signal, 'target_options': options,
                     'cost_ceiling_per_unit': math.ceil(price*.75), 'one_hour_forecast_mean': mean,
                     'newsvendor_one_hour': calculation,
                     'assumption': 'Recent positive-spread shop sales/hour are a temporary one-hour forecast. '
                     'New-lot grades and prices use documented cost mixtures and unvalidated sale anchors; '
                     '4/6 targets are bounded buffer alternatives for supply about every 20 minutes, not an automatic order.'})
    rows.sort(key=lambda r: (-r['evidence']['confirmed_positive_spread_sales_1h'],
                             -r['evidence']['spread_before_holding_refunds_12h'], r['sku']))
    return rows[:8]
