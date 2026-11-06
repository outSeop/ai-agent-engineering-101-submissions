"""Prepare model approvals before supply windows; kit hook only watches/executes.

The worker never calls supply or reserves funds. The hook returns the ordinary
kit buy protocol, using its existing authenticated supply/rate-limit handling.
"""
import argparse
import json
import os
from pathlib import Path
import time

from harness import decide_json
from market_memory import events,record
from replenishment_plan import save,product_signature
import inventory_portfolio as portfolio

POLL_SECONDS=2
PREPARE_POLL_SECONDS=10
WATCH_SECONDS=210  # below the kit's 300-second hook timeout


def snapshot(runtime,now=None):
    now=time.time() if now is None else now
    path=runtime/'.market/inventory.json'
    try:
        with path.open() as source:
            inventory=json.load(source);mtime=os.fstat(source.fileno()).st_mtime
        catalog=json.loads((runtime/'.market/catalog.json').read_text())
        return inventory,catalog,now,-2<=now-mtime<=30
    except (OSError,ValueError):return {},{},now,False


def prepare_once(runtime,*,model=decide_json,now=None,rng=None):
    inventory,catalog,at,fresh=snapshot(runtime,now)
    if not fresh:return 'inventory_stale'
    if not portfolio.preparation_window(inventory,at):return 'outside_preparation_window'
    def refresh():
        inv,cat,t,valid=snapshot(runtime,now)
        return inv,t,valid and cat==catalog
    try:
        portfolio.run(inventory,catalog,events(),at,model=model,refresh=refresh,rng=rng,prepare_only=True)
    except BlockingIOError:return 'preparation_busy'
    ready=portfolio.read_ready()
    return ready.get('status','not_ready')


def execute_once(runtime,*,now=None):
    inventory,catalog,at,fresh=snapshot(runtime,now)
    if not fresh:return None
    if not portfolio.window_open(inventory,at):
        window=inventory.get('restock') or {}
        # Stop promptly in the safety margin instead of waiting out the hook.
        if window.get('open') and type(window.get('closes_at')) in (int,float) and at>=window['closes_at']-portfolio.CLOSING_MARGIN_SECONDS:
            return {'buy':[]}
        return None
    ready=portfolio.read_ready()
    if ready.get('window')==portfolio.window_key(inventory['restock']) and ready.get('status') in ('claimed','invalidated'):
        return {'buy':[]}
    if ready.get('window')!=portfolio.window_key(inventory['restock']) or ready.get('status')!='ready':return None
    def refresh():
        inv,cat,t,valid=snapshot(runtime,now)
        signatures_match=all(sku in cat and product_signature(cat[sku])==product_signature(product)
                             and cat[sku].get('category')==product.get('category') for sku,product in catalog.items())
        return inv,t,valid and signatures_match
    try:
        return portfolio.execute_prepared(inventory,catalog,events(),at,refresh=refresh)
    except BlockingIOError:return None


def watch(runtime,*,timeout=WATCH_SECONDS,clock=time.monotonic,sleep=time.sleep,execute=None):
    deadline=clock()+timeout;execute=execute or execute_once
    while True:
        result=execute(runtime)
        if result is not None:return result
        if clock()>=deadline:return {'buy':[]}
        sleep(min(POLL_SECONDS,max(0,deadline-clock())))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',type=Path)
    parser.add_argument('--state',type=Path)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--loop',action='store_true')
    args=parser.parse_args()
    runtime=(args.runtime or (args.state.parent if args.state else Path.cwd())).resolve()
    os.chdir(runtime)
    if args.execute:
        print(json.dumps(watch(runtime)),flush=True);return
    while True:
        try:status=prepare_once(runtime)
        except Exception as error:
            status='error';record('portfolio_preparation_error',error=type(error).__name__)
        save(Path('state/procurement-scheduler-status.json'),{'at':time.time(),'pid':os.getpid(),'status':status})
        if not args.loop:break
        time.sleep(PREPARE_POLL_SECONDS)


if __name__=='__main__':main()
