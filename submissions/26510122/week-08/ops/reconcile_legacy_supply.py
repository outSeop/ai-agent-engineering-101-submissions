"""Dry-run or apply uniquely proven historical failures; retain all raw logs."""
import argparse
import fcntl
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from market_memory import events,record
from procurement_legacy import discover
from replenishment_plan import save
from supply_reconciliation import pending_quantity,resolve_responses


def main():
    p=argparse.ArgumentParser();p.add_argument('--runtime',type=Path,required=True)
    p.add_argument('--console',type=Path,required=True);p.add_argument('--apply',action='store_true');a=p.parse_args()
    state_path=a.runtime/'state/inventory-portfolio.json';log=a.runtime/'logs/shop-events.jsonl'
    with state_path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        state=json.loads(state_path.read_text());history=events(log)
        before=sum(pending_quantity(i)*i['cost_ceiling'] for i in state['intents'])
        evidence=discover(state['intents'],history,a.console.read_text(errors='replace'))
        known={e.get('request_id') for e in history if e.get('event')=='procurement_supply_result'}
        changes=resolve_responses(state['intents'],history+evidence)
        after=sum(pending_quantity(i)*i['cost_ceiling'] for i in state['intents'])
        if a.apply:
            for e in evidence:
                if e['request_id'] not in known:record(path=log,**e)
            save(state_path,state)
            for c in changes:record('portfolio_intent_reconciled',path=log,**c)
        print(json.dumps({'applied':a.apply,'matched_evidence':len(evidence),
            'released_cost_ceiling':before-after,'pending_cost_ceiling':after,
            'released_units':sum(c['released_units'] for c in changes)},ensure_ascii=False))


if __name__=='__main__':main()
