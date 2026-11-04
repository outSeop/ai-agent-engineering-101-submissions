"""First-hand sales evidence and explicit inventory-depth alternatives."""
from collections import Counter
import math
from procurement_cost import ceiling as acquisition_ceiling

from inventory_observation import timestamp, evidence
from newsvendor_tool import poisson_pmf, recommend_quantity
from capital_policy import MAX_UNIT_COST, operating_policy

PROVEN_STOCK = 20  # safety ceiling, never a desired inventory target
NEW_STOCK = 2
MAINTENANCE_CATEGORY_LIMIT = 24
MIN_POSITIVE_SALES = 2
SUPPLY_CYCLE_SECONDS = 20*60
SUPPLY_JITTER_BUFFER_SECONDS = 120
PURCHASE_LEAD_SECONDS = 60


def sales_evidence(sku, history, now):
    costs = {e['unit']: e['cost'] for e in history if e.get('event') == 'receipt_signed'
             and e.get('unit') and type(e.get('cost')) in (int, float) and e['cost'] > 0}
    settled = {e['ledger']: e for e in history if e.get('event') == 'settled' and e.get('sku') == sku
               and e.get('ledger') is not None and (timestamp(e.get('at')) or 0) >= now-12*3600
               and (timestamp(e.get('at')) or math.inf) <= now}
    positive = [e for e in settled.values() if e.get('unit') in costs and e.get('price', 0) > costs[e['unit']]]
    recent = [e for e in positive if timestamp(e['at']) >= now-3600]
    spread = sum(e['price']-costs[e['unit']] for e in settled.values() if e.get('unit') in costs)
    proven = len(positive) >= MIN_POSITIVE_SALES and spread > 0
    return {'confirmed_positive_spread_sales_12h': len(positive), 'confirmed_positive_spread_sales_1h': len(recent),
            'spread_before_holding_refunds_12h': spread, 'proven': proven,
            'settled_sales_12h':len(settled), 'maintenance_eligible':proven, 'positive_sales_threshold_12h':MIN_POSITIVE_SALES,
            'stock_limit': PROVEN_STOCK if proven else NEW_STOCK,
            'caution': 'Shop settlements are selected observations; positive acquisition spread excludes holding and refunds.'}


def protection_hours(inventory, now):
    window = inventory.get('restock') or {}
    opens = window.get('opens_at')
    if type(opens) not in (int,float) or not math.isfinite(opens):
        seconds = SUPPLY_CYCLE_SECONDS
        source = 'nominal cycle; no window timestamp'
    elif window.get('open'):
        seconds = max(0., opens+SUPPLY_CYCLE_SECONDS-now)
        source = 'nominal next opening after the currently open window'
    else:
        seconds = max(0., opens-now)
        source = 'published next opening'
    hours = min(max(60.,seconds+SUPPLY_JITTER_BUFFER_SECONDS+PURCHASE_LEAD_SECONDS)/3600,
                operating_policy(now)['hours_to_end'])
    return {'hours':hours,
            'source':source, 'timing_buffer_seconds':SUPPLY_JITTER_BUFFER_SECONDS+PURCHASE_LEAD_SECONDS,
            'caution':'Future open-window timing and procurement delay are planning assumptions, not guarantees.'}


def _quantile(mean, level):
    cumulative = 0.
    for n, probability in enumerate(poisson_pmf(mean,cap=PROVEN_STOCK)):
        cumulative += probability
        if cumulative >= level:
            return n
    return PROVEN_STOCK


def demand_forecast(sku, product, inventory, history, now):
    windows = {}
    for hours in (1,3,12):
        observed = evidence(sku,history,now,float(hours))
        raw_rate = observed['confirmed_settlements']/hours
        exposure = observed['in_stock_exposure_hours']
        matched = observed['settlements_during_observed_stock']
        # Pair numerator and denominator. All sales / a short exposed interval
        # would exaggerate demand. Gaps and out-of-stock time are not zero demand.
        conditional = (matched+raw_rate*.5)/(exposure+.5) if exposure >= .25 else None
        windows[str(hours)] = {'settlements':observed['confirmed_settlements'],
                              'in_stock_exposure_hours':exposure, 'covered_settlements':matched,
                              'observed_stockouts':observed['observed_no_stock_visits'],
                              'rate_per_hour':max(raw_rate,conditional or 0.),
                              'rate_source':'paired exposure with shrinkage' if conditional is not None and conditional>raw_rate else 'full-window observed sales lower bound'}
    if windows['1']['settlements'] >= 2:
        rate = .65*windows['1']['rate_per_hour']+.35*windows['3']['rate_per_hour']
        source = '65% recent 1h + 35% recent 3h'
    elif windows['3']['settlements']:
        rate = windows['3']['rate_per_hour']
        source = 'recent 3h; sparse 1h evidence'
    else:
        rate = windows['12']['rate_per_hour']
        source = 'recent 12h fallback; short-window absence is not proof of zero demand'
    protection = protection_hours(inventory,now)
    mean = rate*protection['hours']
    operating = operating_policy(now)
    terminal_capacity = (max(0,math.floor(rate*max(0.,operating['hours_to_end']-2)))
                         if operating['phase'] != 'growth' else None)
    scenarios = []
    for name,factor,level in (('low',.8,.90),('base',1.,.95),('high',1.25,.975)):
        target = _quantile(mean*factor,level)
        if terminal_capacity is not None: target = min(target,terminal_capacity)
        scenarios.append({'scenario':name,'forecast_mean':round(mean*factor,4),'service_level':level,
                          'target_stock':target,'safety_ceiling_binding':target==PROVEN_STOCK})
    price = product.get('list_price') or 1
    cost = max(1,round(price*(.50 if product.get('kind')=='food' else .59)))
    sale = max(1,round(price*(.80 if product.get('kind')=='food' else .92)))
    holding = cost*.01*protection['hours']/24 if product.get('kind')=='goods' else 0.
    diagnostic = recommend_quantity(poisson_pmf(mean),sale,cost,holding_per_leftover=holding,max_qty=PROVEN_STOCK)
    return {'sales_rate_per_hour':round(rate,4),'rate_source':source,'windows':windows,
            'operating_phase':operating['phase'],'terminal_sale_capacity_estimate':terminal_capacity,
            'protection_period':protection,'demand_mean_until_next_replenishment':round(mean,4),
            'scenarios':scenarios,'maximum_target':max(s['target_stock'] for s in scenarios),
            'newsvendor_zero_continuation_diagnostic':diagnostic,
            'assumption':'Poisson and service levels are unvalidated planning hypotheses. '
            'Targets cover demand until the next procurement opportunity, not a fixed unit count. '
            'The newsvendor diagnostic assumes zero continuation value, a pessimistic reference; '
            'remaining inventory is not actually discarded at this short horizon. '
            'Exposure correction describes this shop only, not total market demand.'}


def replenishment_candidates(catalog, inventory, history, now, blocked=(), trialed=(), pending=None):
    if not operating_policy(now)['allow_replenishment']: return []
    units = [u for u in inventory.get('units', []) if u.get('grade') in ('A', 'B', 'C')
             and (u.get('expires_at') is None or u['expires_at'] > now)]
    stocks = Counter(u['sku'] for u in units)
    pending = pending or {}
    categories = Counter(u.get('category') for u in units)
    sold_skus = {e.get('sku') for e in history if e.get('event') == 'settled' and e.get('sku')}
    rows = []
    for sku in sold_skus:
        p = catalog.get(sku)
        if sku in blocked or not isinstance(p, dict) or p.get('kind') not in ('food', 'goods'):
            continue
        signal = sales_evidence(sku, history, now)
        price = p.get('list_price')
        reserved = pending.get(sku, 0)
        projected = stocks[sku] + reserved
        second_trial = (operating_policy(now)['allow_new_skus'] and not projected and sku not in trialed
                        and signal['settled_sales_12h'] == 1
                        and signal['confirmed_positive_spread_sales_12h'] == 1
                        and len({e.get('ledger') for e in history if e.get('event') == 'settled'
                                 and e.get('sku') == sku and e.get('ledger') is not None}) == 1)
        if ((not signal['proven'] and not second_trial) or projected >= PROVEN_STOCK or type(price) is not int
                or price <= 0 or acquisition_ceiling(p) > MAX_UNIT_COST):
            continue
        if p['kind'] == 'food' and (p.get('shelf_hours') or 0) < 48:
            continue
        reserved_category = sum(qty for key,qty in pending.items()
                                if catalog.get(key,{}).get('category') == p.get('category'))
        room = max(0, MAINTENANCE_CATEGORY_LIMIT-categories[p.get('category')]-reserved_category)
        forecast = demand_forecast(sku,p,inventory,history,now)
        options = []
        if second_trial and room:
            options = [{'target_stock':1, 'qty':1, 'forecast_target':None,
                        'scenario':'second_trial', 'service_level':None,
                        'cost_ceiling':acquisition_ceiling(p)}]
        for scenario in forecast['scenarios']:
            if second_trial: break
            target = scenario['target_stock']
            qty = min(max(0, target-projected),room)
            if qty > 0 and not any(o['qty']==qty for o in options):
                options.append({'target_stock': projected+qty, 'qty': qty,
                                'forecast_target':target,'scenario':scenario['scenario'],
                                'service_level':scenario['service_level'],
                                'cost_ceiling': acquisition_ceiling(p)*qty})
        if not options:
            continue
        rows.append({'sku': sku, 'name': p.get('name', sku), 'kind': p['kind'], 'category': p.get('category'),
                     'currently_stocked': stocks[sku], 'pending_stock':reserved,
                     'second_trial':second_trial, 'evidence': signal, 'target_options': options,
                     'cost_ceiling_per_unit': acquisition_ceiling(p), 'forecast':forecast,
                     'budget_scope':'replenishment: shared window and cash/risk limits; NOT rolling novel-exploration budget',
                     'assumption':('One additional unit after exactly one positive-spread settlement; not proven maintenance.'
                                   if second_trial else 'Each target/quantity is forecast-derived; the model approves a candidate or holds.')})
    rows.sort(key=lambda r: (-(r['target_options'][-1]['qty']/max(1,r['currently_stocked'])),
                             -r['evidence']['confirmed_positive_spread_sales_1h'],
                             -r['evidence']['spread_before_holding_refunds_12h'], r['sku']))
    proven = [r for r in rows if not r['second_trial']]
    trials = [r for r in rows if r['second_trial']]
    trial_rows = trials[:2]
    return proven[:12-len(trial_rows)] + trial_rows


def policy_view(sku, product, inventory, history, now):
    signal = sales_evidence(sku,history,now)
    if signal['maintenance_eligible']:
        forecast = demand_forecast(sku,product,inventory,history,now)
        return {**signal,'stock_limit':forecast['maximum_target'],'forecast':forecast}
    return signal
