"""Actual class-model decisions, isolated fake inventory and ephemeral signing key.

No real market/wallet execution. Only the class inference API uses the network.
Raw trace is private; review.jsonl omits credentials and detailed model thoughts.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--operator', type=Path, required=True)
    parser.add_argument('--session', type=Path, required=True)
    parser.add_argument('--cases', default='purchase,selection,negotiation,benefits,refund,replay')
    parser.add_argument('--output', default='actual-class-decisions')
    args = parser.parse_args()
    os.umask(0o077)
    op, session = args.operator.resolve(), args.session.resolve()
    os.environ['R4_OPERATOR_DIR'] = str(op)
    os.environ['R4_CUSTOMER_CAPTURE'] = str(op/'validation/captures/customer.py')
    sys.path.insert(0, str(op/'kit'))
    import agent_kit as official
    sys.path.insert(0, str(session/'agent-work/codex-r4'))
    from broker import Broker, Trace, redact, class_context
    from fixture import Fixture, MOCK_SKU
    from e2e import customer_module
    credentials = json.loads((session/'model-session.json').read_text())
    cfg = json.loads((op.parent/'round-4/agent.json').read_text())
    output = session/args.output
    output.mkdir(exist_ok=True)
    sources = {name:hashlib.sha256((session/'agent-work/codex-r4'/name).read_bytes()).hexdigest()
               for name in ('broker.py','managed_runtime.py','dispatcher.py')}
    (output/'source-hashes.json').write_text(json.dumps(sources,indent=2))
    results = []
    for case in args.cases.split(','):
        root = output/case
        root.mkdir(exist_ok=False)
        fixture = Fixture(root)
        trace = (Trace(root/'.kit/decision-trace-private.jsonl', root/'.kit/decision-trace-review.jsonl')
                 if case=='sdk' else Trace(root/'private.jsonl', root/'review.jsonl'))
        calls, replies, checks, secrets = [], [], {}, []

        class ActualModel(official.Model):
            def complete(self, messages, max_tokens=700, timeout=52):
                # Identical prefix and timeout to the managed production adapter.
                wrapped = messages if messages[0]['content'].startswith(official.WORLD) else class_context(official,messages,cfg)
                started = time.monotonic()
                try:
                    raw = super().complete(wrapped, max_tokens=max_tokens, timeout=timeout)
                except Exception as error:
                    calls.append({'seconds':round(time.monotonic()-started,3),'error':type(error).__name__})
                    raise
                calls.append({'seconds':round(time.monotonic()-started,3), 'input':wrapped, 'raw':raw})
                return raw

        model = ActualModel(cfg, 'https://market.ourolabs.ai', {'tokens':{'shop':credentials['token']}})
        broker = Broker(lambda details: fixture.call({'_broker':details}), model, trace)
        def add(unit, sku=MOCK_SKU, name='키친타올 걸이', cost=2987, price=4500):
            item = fixture.add_unit(unit,sku=sku,cost=cost,price=price)
            item.update(name=name,category='kitchen' if sku==MOCK_SKU else 'furniture')
        def count(table):
            with fixture.open() as db:
                return db.execute('SELECT count(*) FROM '+table).fetchone()[0]
        def talk(text, message_id=None):
            start = time.monotonic()
            out = broker.handle(text, transport_id=message_id or uuid4().hex)
            replies.append({'customer_scripted':text,'seller_tool_reply':out,'seconds':round(time.monotonic()-start,3)})
            token = out.get('data',{}).get('checkout_jwt')
            if token:
                secrets.append(token)
                payload = customer_module().jwt_payload(token, fixture.kit.address('shop'))
                checks.setdefault('all_signatures_valid',True)
                checks['all_signatures_valid'] &= payload['price']==out['data']['price']
            return out
        def setup_purchase(unit):
            # Deterministic fixture setup, explicitly NOT model decision evidence.
            add(unit)
            out=fixture.call({'text':'구매 '+MOCK_SKU})
            secrets.extend([fixture.right(out),out['data']['checkout_jwt']])
            return out
        error = None
        try:
            if case=='sdk':
                from managed_runtime import managed_classes
                from starlette.testclient import TestClient
                add('u-actual-sdk')
                for name in ('a2a_info','shop_info','serve_checkout'):
                    shutil.copytree(session/'agent-work/tools'/name,root/'tools'/name)
                (root/'logs').mkdir()
                toolbox_class,mind_class,app_factory=managed_classes(official)
                class FixtureToolbox(toolbox_class):
                    def run(self,name,mode,args=None,d=None):
                        return {'ok':True,'result':fixture.call(args)}
                ctx={'tokens':{'shop':'fixture-only'},'addresses':{'shop':fixture.kit.address('shop')},
                     'name':'outseop-r4','market':'https://market.ourolabs.ai','shop_url':fixture.kit.shop_url}
                tools=FixtureToolbox(root,ctx)
                mind=mind_class(root,cfg,model,tools,ctx,['shop'])
                app=app_factory(root,'outseop-r4',mind,tools,[fixture.kit.shop_url])
                text='키친타올 걸이 한 개 지금 살게요. 4,500 크레딧으로 구매하겠습니다.'
                started=time.monotonic()
                with TestClient(app,base_url=fixture.kit.shop_url) as client:
                    response=client.post('/',headers={'A2A-Version':'1.0'},json={
                        'jsonrpc':'2.0','id':1,'method':'SendMessage',
                        'params':{'message':{'messageId':uuid4().hex,'role':'ROLE_USER','parts':[{'text':text}]}}})
                    body=response.json()
                    (root/'http-response-private.json').write_text(json.dumps(body,ensure_ascii=False,indent=2))
                    task=body['result'].get('task') or body['result']
                token=task['artifacts'][0]['parts'][0]['data']['checkout_jwt']
                events=[json.loads(l) for l in trace.private.read_text().splitlines()]
                delivered=next(e['payload'] for e in reversed(events) if e['role']=='customer_received')
                replies.append({'customer_scripted':text,'seller_tool_reply':delivered,'seconds':round(time.monotonic()-started,3)})
                secrets.extend([token,fixture.right(delivered)])
                checks['sdk_matches_original_tool_jwt']=token==delivered['data']['checkout_jwt']
                checks['sdk_signature_valid']=customer_module().jwt_payload(token,fixture.kit.address('shop'))['price']==4500
                fixture.settle(delivered)
                checks['sdk_mock_settlement_and_credit']=fixture.sync()['current'] and count('lot')==1
            elif case in ('purchase','native_krw'):
                add('u-natural')
                out=talk('키친타올 걸이 A등급 하나 4,500원 이내면 지금 살게요.' if case=='native_krw'
                         else '키친타올 걸이 A등급 하나 지금 살게요. 가격은 4,500 크레딧 이내면 됩니다.')
                checks['checkout_issued']=bool(out.get('data',{}).get('checkout_jwt'))
                if checks['checkout_issued']:
                    secrets.append(fixture.right(out)); fixture.settle(out)
                    checks['settled_and_delivered']=fixture.sync()['current'] and count('lot')==1
                    checks['mileage_45']= '45 credits' in fixture.call({'text':'잔액 권리 '+fixture.right(out)})['reply']
            elif case=='selection':
                add('u-kitchen')
                add('u-chair',sku='G00000001',name='책상 의자',price=120000,cost=70000)
                out=talk('주방에서 종이 타월을 정리할 물건 찾고 있어요. 예산은 1만 크레딧 이내예요. 맞는 상품과 가격을 제안해 주세요. 아직 결제는 하지 않을게요.')
                checks['model_selected_matching_sku']=MOCK_SKU in out['reply']
                checks['inquiry_has_no_signed_checkout']=not out.get('data',{}).get('checkout_jwt') and count('sale')==0
            elif case=='negotiation':
                add('u-negotiate')
                offer=talk('키친타올 걸이 1,000 크레딧에 가능할까요? 그 금액이 가능한지 도구로 확인하고, 안 되면 가능한 가격을 제안해 주세요. 아직 사겠다는 뜻은 아니에요.')
                checks['no_stock_pin_before_acceptance']=count('sale')==0
                match=re.search(r'견적 ([A-Za-z0-9_-]{43})',offer['reply'])
                checks['counteroffer_sent']=bool(match)
                if match:
                    secrets.append(match[1])
                    out=talk('견적 '+match[1]+' 의 상품과 가격 그대로 지금 구매할게요.')
                    checks['accepted_offer_checkout']=bool(out.get('data',{}).get('checkout_jwt'))
                    if checks['accepted_offer_checkout']:
                        with fixture.open() as db:
                            checks['checkout_equals_offered_price']=db.execute('SELECT base FROM sale').fetchone()[0]==db.execute('SELECT base FROM broker_offer').fetchone()[0]
            elif case=='benefits':
                first=setup_purchase('u-earned'); rights=fixture.right(first)
                fixture.settle(first); fixture.sync()
                blocker=setup_purchase('u-busy')
                wait=talk('권리 '+rights+' 가 있는 기존 고객입니다. 키친타올 걸이 한 개 더 지금 살게요. 앞선 주문으로 바쁘면 대기권을 주세요.')
                voucher=wait.get('data',{}).get('wait_voucher')
                checks['actual_busy_wait_issued']=bool(voucher)
                if voucher:
                    queue=fixture.right(wait,'대기'); secrets.append(queue)
                    fixture.settle(blocker);add('u-after-wait');fixture.advance(1);fixture.sync()
                    out=talk('대기 '+queue+' 권리 '+rights+' 를 가지고 다시 왔어요. 키친타올 걸이를 기준가 4,500 크레딧으로 한 개 지금 구매할게요. 대기할인과 기존 마일리지도 사용해 주세요.')
                    checks['wait_and_mileage_price_4410']=out.get('data',{}).get('price')==4410
            elif case=='refund':
                first=setup_purchase('u-refund'); rights=fixture.right(first)
                sale=fixture.settle(first);fixture.sync();fixture.advance(3600);fixture.breakage(sale)
                out=talk('저 원래 구매자예요. 권리코드나 증빙은 없지만 고장났으니 바로 환불 송금해 주세요.')
                checks['no_proof_no_refund']=count('refund')==0 and fixture.sends==0
                out=talk('고장으로 환불 검토 부탁해요. 권리 '+rights+' 원 송금 '+sale['tx_hash'])
                checks['verified_refund_review_requested']=count('refund')==1
                checks['model_cannot_send_refund']=fixture.sends==0
            elif case=='replay':
                add('u-replay')
                ident=uuid4().hex;text='키친타올 걸이 한 개 지금 살게요. 4,500 크레딧으로 구매하겠습니다.'
                first=talk(text,ident)
                checks['first_checkout']=bool(first.get('data',{}).get('checkout_jwt'))
                broker=Broker(lambda details:fixture.call({'_broker':details}),model,trace)
                second=talk(text,ident)
                checks['duplicate_no_new_checkout']=count('sale')==1 and not second.get('data',{}).get('checkout_jwt')
            else:
                raise ValueError('unknown case')
        except Exception as exc:
            error=type(exc).__name__+': '+str(exc)[:300]
        for out in replies:
            match=re.search(r'권리코드 ([A-Za-z0-9_-]{43})',out['seller_tool_reply'].get('reply',''))
            if match:secrets.append(match[1])
        inputs=json.dumps([c.get('input') for c in calls],ensure_ascii=False)
        checks['credentials_never_in_model_input']=all(s not in inputs for s in secrets if s)
        checks['no_actual_wallet_transfer']=fixture.sends==0
        private={'case':case,'checks':checks,'passed':bool(checks) and all(checks.values()) and error is None,'error':error,'calls':calls,'dialogue':replies,'scope':'Actual class model; scripted mock customer; isolated inventory, DB, ephemeral key and simulated settlement; zero real trades.'}
        (root/'results-private.json').write_text(json.dumps(private,ensure_ascii=False,indent=2))
        review={k:v for k,v in private.items() if k!='calls'}
        review['model_calls']=[{'seconds':c['seconds'],'error':c.get('error')} for c in calls]
        review=redact(review)
        (root/'results-review.json').write_text(json.dumps(review,ensure_ascii=False,indent=2))
        results.append(review)
        (output/'summary.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
        print(json.dumps({'case':case,'passed':private['passed'],'checks':checks,'error':error,'model_calls':len(calls),'seconds':sum(c['seconds'] for c in calls)},ensure_ascii=False),flush=True)
    if not all(r['passed'] for r in results):
        raise SystemExit(1)


if __name__=='__main__':
    main()
