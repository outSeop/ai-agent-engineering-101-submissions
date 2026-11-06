"""Inspectable Patch 3.4 contracts; currency is never a percentile score."""
import math

VERSION = 'round3-book-saved-v1'
SELLER_WEIGHTS = {'book':.5,'revenue':.3,'stars':.2}
BUYER_WEIGHTS = {'saved':.5,'forum':.3,'deals':.1,'posts':.1}
SAVED_CONTRACT = ('Saved uses normalized realized surplus per list price, divided by deals+100. '
                  'At a usable settlement its contribution is 1-paid/list; expensive goods get no extra weight. '
                  'Unusable food and broken goods can lower it; a covered full refund neutralizes that loss. '
                  'Final Saved is the market value, not an average of quoted discounts. '
                  'Keep checkout validity and settlement likelihood; do not skip issued orders merely to chase a rate.')
BOOK_CONTRACT = ('Book = cash balance - starting capital - bankruptcy injections + unsold inventory acquisition cost. '
                 'Buying inventory at its paid cost is initially Book-neutral, not a profit or a score boost. '
                 'Sale spread, holding costs, food spoilage and warranty refunds change Book. '
                 'Stock credit persists at round end, but is not a cash buyback. '
                 'ALL weights are percentiles, not weights on raw currency and stars.')

def saved_at_price(list_price,price):
    if type(list_price) not in (int,float) or not math.isfinite(list_price) or list_price<=0:
        raise ValueError('positive finite list price required')
    if type(price) not in (int,float) or not math.isfinite(price) or price<0:
        raise ValueError('nonnegative finite price required')
    return round(1-price/list_price,6)

def buyer_candidate(list_price,cap):
    return {'metric':'saved','version':VERSION,'saved_if_usable_at_cap':saved_at_price(list_price,cap),
            'assumption':'cap is an authorization ceiling, NOT a seller quote or predicted price; '
                         'conditional saving only if a valid usable deal settles at that price',
            'virtual_zero_deals':100}

def book_metrics(inventory,now):
    stock=sum(max(0,int(u.get('cost') or 0)) for u in inventory.get('units',[])
              if u.get('grade')!='expired' and (u.get('expires_at') is None or u['expires_at']>now))
    balance=int(inventory.get('balance') or 0);start=int(inventory.get('start',5_000_000));injected=int(inventory.get('injected') or 0)
    cash=balance-start-injected
    return {'version':VERSION,'at':now,'cash_balance':balance,'starting_capital':start,
            'bankruptcy_injections':injected,'cash_earnings':cash,'stock_cost':stock,'book':cash+stock,
            'source':'inventory balance/start/injected and live unit acquisition costs'}

def terminal_credit(unit,ends_at):
    cost=max(0,int(unit.get('cost') or 0))
    if unit.get('grade')=='expired':return 0
    if unit.get('kind')=='food':
        expiry=unit.get('expires_at')
        return cost if type(expiry) in (int,float) and expiry>ends_at else 0
    return cost if unit.get('kind')=='goods' else 0

def continuation(product,cost,model_value,horizon_hours,hours_to_end):
    """Goods retain Book credit; no invented survival odds for newly drawn food."""
    value=max(0.,min(cost,float(model_value))) if type(model_value) in (int,float) and math.isfinite(model_value) else 0.
    future_hours=max(0.,hours_to_end-horizon_hours)
    floor=max(0.,cost-cost*.01*future_hours/24) if product.get('kind')=='goods' else 0.
    if horizon_hours>=hours_to_end:value=cost if product.get('kind')=='goods' else value
    return {'value':max(value,floor),'book_retention_floor':round(floor,4),
            'model_value':value,'future_holding_hours':future_hours,
            'contract':'Goods retain acquisition-cost Book credit less future carrying cost; '
                       'food continuation is an uncertain model hypothesis capped at cost, not guaranteed credit. '
                       'No resale or cash buyback occurs at the planning horizon.'}
