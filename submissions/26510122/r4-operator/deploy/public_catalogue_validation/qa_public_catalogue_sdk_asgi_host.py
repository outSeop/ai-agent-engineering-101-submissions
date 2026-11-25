"""Independent single-catalogue official ASGI tests; all data and Model are synthetic."""
import argparse,json,time,re
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock
from contextlib import redirect_stdout,redirect_stderr,nullcontext
from copy import deepcopy
import public_catalogue_class_canary_host as host
OP=next(p for p in Path(__file__).resolve().parents if (p/'kit/agent_kit.py').exists())


def snapshot(count):
    now=int(time.time())
    return {'schema':'outseop-r4.customer-offers.v1','shop':'outseop-r4','observed_at':now,'valid_until':now+150,'units':[
      {'unit_ref':'synthetic-catalogue-'+str(i),'sku':f'G{i+1:08x}','name':('가'*126 if i==16 else '합성 식품 '+str(i)),
       'category_path':['식품','과일'],'state':'available','grade':'A','price_credits':100+i,
       'standard_fee_credits':None,'expires_at':now+3600+i} for i in range(count)]}


def latest_page(messages):
    for message in reversed(messages):
        if message['role']=='system':continue
        try:parsed=json.loads(message['content'])
        except ValueError:continue
        found=host.pages_in(parsed)
        if found:return found[-1]
    raise AssertionError('no genuine page delivered to Model')


def decoded(page):
    rows=[]
    for cells in page['rows']:
        row=dict(page['common']);row.update(zip(page['columns'],cells))
        for key,values in page['lookup'].items():row[key]=values[row[key]]
        rows.append(row)
    return rows


def prepare(root,count,bundle,pin,label):
    data=snapshot(count);source=root/(label+'-source.json');source.write_bytes(host.encode(data));source.chmod(0o400)
    session=root/label;raw,value=host.prepare(OP,session,source,bundle,pin)
    assert len(value['units'])==count and raw==source.read_bytes()
    return session,raw,value


def main(bundle,pin,output):
    output.mkdir(parents=True,exist_ok=False);results=[]
    cases=output/'cases';cases.mkdir(mode=0o700)
    with nullcontext(cases) as temporary:
        root=Path(temporary)
        for count in (117,500):
            session,raw,value=prepare(root,count,bundle,pin,'search-'+str(count));turns=[];observed_cursor=[];model=Mock()
            def step(messages,**kwargs):
                page=latest_page(messages);rows=decoded(page);assert 0<len(rows)<=8
                if len(turns)==0:
                    turns.append('refine');args={'exclude_skus':[rows[0]['sku']],'limit':8}
                    return json.dumps({'action':'search_products','args':args})
                if len(turns)==1:
                    turns.append('cursor');args=deepcopy(page['catalogue']['next_args']);assert args is not None and args.get('op')=='search'
                    observed_cursor.append(deepcopy(args));return json.dumps({'action':'search_products','args':args})
                turns.append('render');return json.dumps({'action':'render_public_products','args':{'items':[{'sku':r['sku'],'grade':r['grade']} for r in rows[:3]]}})
            model.complete.side_effect=step
            with (output/('search-'+str(count)+'-private.log')).open('x') as log,redirect_stdout(log),redirect_stderr(log):r=host.run_asgi(OP,session,raw,value,model)
            assert r['status']=='verified_catalogue_final_reply' and r['final_genuine_operation']=='render',r
            assert [c['op'] for c in r['catalogue_calls']]==['context','search','search','render']
            assert r['legacy_context_calls']==1 and r['supplier_calls']==1 and r['financial_executor_attempts']==0
            assert len(turns)==3 and len(observed_cursor)==1
            assert max(n for call in r['Model_metrics'] for n in call['page_rows_in_history'])<=8
            assert max(n for call in r['Model_metrics'] for n in call['page_characters_in_history'])<=5500
            assert all(c['snapshot_sha256']==host.digest(raw) for c in r['catalogue_calls'])
            assert all(c['source_count']==count for c in r['catalogue_calls'] if c['page_rows'] is not None)
            assert r['old_builder_invocations']==0 and not r['old_builder_source_present']
            results.append({'label':'search-refine-next-render-'+str(count),'passed':True,'safe_result':r})
        session,raw,value=prepare(root,500,bundle,pin,'timeout-public');model=Mock();model.complete.side_effect=TimeoutError('synthetic immediate timeout')
        with (output/'timeout-public-private.log').open('x') as log,redirect_stdout(log),redirect_stderr(log):r=host.run_asgi(OP,session,raw,value,model)
        assert r['status']=='verified_catalogue_final_reply' and r['final_genuine_operation']=='fallback',r
        assert [c['op'] for c in r['catalogue_calls']]==['context','fallback'] and r['legacy_context_calls']==1
        original=json.loads((session/'logs/asgi-response-private.json').read_bytes());task=original['result'].get('task',original['result']);reply=task['status']['message']['parts'][0]['text']
        assert any(u['sku'] in reply for u in value['units']) and ('일부' in reply or '조회' in reply)
        assert not re.search(r'추천합니다|최저가입니다|조건을?\s*충족합니다|구매\s*완료|결제\s*완료|환불\s*완료',reply)
        results.append({'label':'immediate-ModelTimeout-genuine-partial-fallback','passed':True,'safe_result':r})
        questions={
          'purchase':'식품 재고 가격 등급 유통기한도 알려주세요. G00000001 구매하겠습니다.',
          'refund':'식품 재고 가격 등급 유통기한 문의와 환불 검토도 요청합니다.',
          'right':'식품 재고 가격 등급 유통기한 문의입니다. 권리 '+('R'*43),
          'payment':'식품 재고 가격 등급 유통기한 문의입니다. 원래 송금해시 0x'+('1'*64),
        }
        for label,question in questions.items():
            session,raw,value=prepare(root,117,bundle,pin,'protected-'+label);model=Mock();model.complete.side_effect=TimeoutError('synthetic immediate timeout')
            original=json.loads((session/'host_inputs/broker_context_base.json').read_bytes());original.update(verified_account=True,redeemable_mileage=42,prior_offer={'sku':'G00000001','base':100})
            with (output/('protected-'+label+'-private.log')).open('x') as log,redirect_stdout(log),redirect_stderr(log):r=host.run_asgi(OP,session,raw,value,model,question,original)
            assert not any(c['op']=='fallback' for c in r['catalogue_calls']),r
            assert r['legacy_context_calls']==1 and r['legacy_fixture_unchanged'] and r['financial_executor_attempts']==0
            view=json.loads(model.complete.call_args.args[0][1]['content'])['verified_context']
            assert view['verified_account'] is True and view['redeemable_mileage']==42 and view['prior_offer']==original['prior_offer']
            results.append({'label':'protected-'+label+'-fallback-zero','passed':True,'safe_result':r})
    summary={'schema':'single-catalogue-SDK-ASGI-independent.v1','cases':len(results),'passed':sum(x['passed'] for x in results),'actual_Model_or_market_calls':0,'old_builder_invoked':False,'source_auth_manifest_sha256':pin,'results':results}
    (output/'safe-summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps({k:v for k,v in summary.items() if k!='results'}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--runtime-bundle',type=Path,required=True);p.add_argument('--runtime-manifest-sha',required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();main(a.runtime_bundle,a.runtime_manifest_sha,a.output)
