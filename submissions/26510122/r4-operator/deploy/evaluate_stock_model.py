"""Actual classroom-model stock choices; all supply/wallet execution is synthetic."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--operator',type=Path,required=True);parser.add_argument('--session',type=Path,required=True);parser.add_argument('--output',default='actual-stock-model-v2')
    args=parser.parse_args();op=args.operator.resolve();session=args.session.resolve();os.umask(0o077)
    os.environ['R4_OPERATOR_DIR']=str(op);os.environ['R4_CUSTOMER_CAPTURE']=str(op/'validation/captures/customer.py')
    sys.path.insert(0,str(op/'kit'));import agent_kit as official
    w=session/'agent-work/codex-r4';sys.path.insert(0,str(w))
    from stock_runtime import StockCoordinator
    from test_procurement import StockFixture
    import procurement as stock
    from fixture import COIN,MOCK_SKU
    credentials=json.loads((session/'model-session.json').read_text());cfg=json.loads((op.parent/'round-4/agent.json').read_text())
    output=session/args.output;output.mkdir(exist_ok=False)
    hashes={n:hashlib.sha256((w/n).read_bytes()).hexdigest() for n in ['dispatcher.py','procurement.py','stock_runtime.py','managed_runtime.py']}
    (output/'source-hashes.json').write_text(json.dumps(hashes,indent=2))
    results=[]
    for case in ['coldstart_breadth','cash_protected','proven_replenishment']:
        root=output/case;root.mkdir();f=StockFixture(root)
        f.catalog=[{'sku':MOCK_SKU,'list_price':35000,'name':'주방 정리함','category':'주방용품>수납','kind':'goods','shelf_hours':None},
                   {'sku':'G00000001','list_price':120000,'name':'사무용 의자','category':'가구>의자','kind':'goods','shelf_hours':None},
                   {'sku':'G00000002','list_price':240000,'name':'공기 청정기','category':'가전>청정기','kind':'goods','shelf_hours':None},
                   {'sku':'G00000003','list_price':100,'name':'저가 수건','category':'생활>수건','kind':'goods','shelf_hours':None}]
        f.arrive_on_confirm=True
        # A plausible grade-A cost scenario; every actual quote is still checked.
        def quote_cost(q):
            q['quote']='q-'+hashlib.sha256((q['units'][0]['sku']+str(len(f.calls))).encode()).hexdigest()[:16]
            q['pay']['data']='0x'+hashlib.sha256(q['quote'].encode()).hexdigest()
            for i,u in enumerate(q['units']):
                u['cost']=int(u['list_price']*.60)
                u['unit']='u-'+hashlib.sha256((q['quote']+str(i)).encode()).hexdigest()[:12]
            q['goods']=sum(u['cost'] for u in q['units']);q['total']=q['goods']+q['storage']+q['forum_fees'];q['pay']['wei']=str(q['total']*COIN)
        f.quote_override=quote_cost
        original_payments=f.payments
        def buyer_payments(*a,**kw):
            payment,fee=original_payments(*a,**kw)
            if fee:f.txs[fee]['to']=f.bank.address
            return payment,fee
        f.payments=buyer_payments
        if case=='cash_protected':f.cash=590000
        if case=='proven_replenishment':
            # These are explicit fake settled orders, not imported R3 sales.
            for index in range(2):
                f.add_unit('u-prior-'+str(index),price=35000,cost=15000)
                out=f.call({'text':'구매 '+MOCK_SKU});f.settle(out);assert f.sync()['current']
                f.advance(300)
            f.start=f.now+90;f.end=f.start+180
        model_calls=[];actions=[]
        class ActualModel(official.Model):
            def complete(self,messages):
                wire=[dict(messages[0],content=official.WORLD+'\n\n'+messages[0]['content']),*messages[1:]]
                started=time.monotonic();raw=super().complete(wire,max_tokens=550,timeout=42)
                try:choice=json.loads(raw)
                except ValueError:choice={'invalid_output':True}
                model_calls.append({'seconds':round(time.monotonic()-started,3),'input':wire,
                    'choice':{k:choice[k] for k in ['action','lines','reason'] if k in choice}})
                return raw
        model=ActualModel(cfg,'https://market.ourolabs.ai',{'tokens':{'shop':credentials['token']}})
        def mock_pay(to,wei,data):
            tx=f.pay(to,wei,data);f.cash-=wei//COIN;return tx
        def execute(action):
            if action['action']=='context':action=dict(action,line_cap=3)
            result=f.action(action,pay=mock_pay);actions.append({'action':action,'result':result});return result
        coordinator=StockCoordinator(execute,model,now=lambda:f.now)
        error=None;checks={}
        try:
            coordinator.tick()
            with f.open_proc() as db:
                plans=[dict(x) for x in db.execute('SELECT status,choices,decision FROM stock_plan')]
            checks['no_payment_before_window']=f.sends==0
            if case=='cash_protected':
                checks['no_model_or_payment_when_no_headroom']=not model_calls and f.sends==0
            else:
                checks['actual_class_model_chose_valid_plan']=bool(model_calls) and plans[0]['status'] in ('ready','hold')
                view=json.loads(plans[0]['choices'])
                checks['fee_negative_cheap_sku_not_offered']=all(c['sku']!='G00000003' for c in view['choices'])
                if case=='proven_replenishment':checks['two_confirmed_positive_sales_recognized']=any(c['sku']==MOCK_SKU and c['tier']=='proven' for c in view['choices'])
                if plans[0]['status']=='ready':
                    decision=json.loads(plans[0]['decision']);n=len(decision['lines'])
                    f.advance(f.start-f.now+1)
                    for _ in range(3*n+3):coordinator.tick();f.advance(12)
                    with f.open_proc() as db:
                        intents=[dict(x) for x in db.execute('SELECT sku,qty,state,total FROM stock_intent')]
                    checks['approved_lines_arrived']=len(intents)==n and all(x['state']=='arrived' for x in intents)
                    checks['one_wallet_send_per_approved_line']=f.sends==n
                    checks['no_quantity_expansion']=all(x['qty']==next(l['qty'] for l in decision['lines'] if l['sku']==x['sku']) for x in intents)
                    actions.append({'mock_execution_summary':{'model_approved_lines':decision['lines'],'intents':intents,'mock_wallet_sends':f.sends}})
                else:actions.append({'model_hold_is_respected':True})
            checks['no_real_keys_used']=f.kit.key is not None and f.kit.signer is None
        except Exception as exc:error=type(exc).__name__+': '+str(exc)[:200]
        row={'case':case,'checks':checks,'passed':bool(checks) and all(checks.values()) and error is None,
             'error':error,'model_calls':model_calls,'actions':actions,'real_transfers':0,
             'scope':'Actual class model; synthetic catalog and paid history, ephemeral wallets, fake wholesale and chain.'}
        (root/'review.json').write_text(json.dumps(row,ensure_ascii=False,indent=2));results.append(row)
        print(json.dumps({'case':case,'passed':row['passed'],'checks':checks,'model_calls':len(model_calls),'error':error},ensure_ascii=False),flush=True)
    (output/'summary.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
    if not all(r['passed'] for r in results):raise SystemExit(1)


if __name__=='__main__':main()
