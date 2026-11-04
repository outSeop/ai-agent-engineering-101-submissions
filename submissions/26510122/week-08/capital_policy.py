"""Working-capital policy for cash-based, percentile-ranked Round 3 scoring."""
from datetime import datetime

ROUND_END = datetime.fromisoformat('2026-11-17T23:59:00+09:00').timestamp()
MIN_CASH = 600_000
MAX_COST = 12_000_000
MAX_UNITS = 180
MAX_UNIT_COST = 500_000
GROWTH_WINDOW_BUDGET = 2_400_000
GROWTH_EXPLORATION_BUDGET = 12_000_000
RANKING = {'profit':.5,'revenue':.3,'stars':.2}


def operating_policy(now):
    hours = max(0.,(ROUND_END-now)/3600)
    if hours <= 2:
        phase,share,target,window,rolling,new = 'sell_only',0.,0.,0,0,False
    elif hours <= 24:
        phase,share,target,window,rolling,new = 'final_day',.25,.20,300_000,0,False
    elif hours <= 72:
        phase,share,target,window,rolling,new = 'harvest',.50,.40,600_000,0,False
    else:
        phase,share,target,window,rolling,new = ('growth',.75,.65,
            GROWTH_WINDOW_BUDGET,GROWTH_EXPLORATION_BUDGET,True)
    return {'phase':phase,'hours_to_end':round(hours,4),'ends_at':ROUND_END,
            'inventory_capital_share':share,'target_capital_share':target,
            'window_budget':window,'rolling_exploration_budget':rolling,
            'allow_new_skus':new,'allow_replenishment':hours>2,
            'score_weights':RANKING,'score_unit':'each component is a market percentile, not a raw weighted sum',
            'profit_definition':'cash balance minus starting capital minus bankruptcy injections; unsold stock has no credited terminal value'}


def target_inventory_cost(inventory, now):
    stock = sum(max(0,int(u.get('cost') or 0)) for u in inventory.get('units',[])
                if u.get('grade') in ('A','B','C') and (u.get('expires_at') is None or u['expires_at']>now))
    equity_at_cost = max(0,int(inventory.get('balance') or 0))+stock
    return min(MAX_COST,int(equity_at_cost*operating_policy(now)['target_capital_share']))
