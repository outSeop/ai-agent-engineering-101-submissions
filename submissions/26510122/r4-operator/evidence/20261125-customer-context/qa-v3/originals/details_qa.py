from pathlib import Path
import json,time
ROOT=Path(__file__).resolve().parent
prefix=(ROOT/'ordinary_toolbox_qa.py').read_text().split('\nwith Fake() as f:',1)[0];ns={'__file__':str(ROOT/'ordinary_toolbox_qa.py')};exec(compile(prefix,'external_unchanged_fixture','exec'),ns)
Fake=ns['Fake'];base=ns['base'];doc=ns['doc'];unit=ns['unit'];unpack=ns['unpack'];checks=[]
def ck(case,ok,group='contract',observed=None):checks.append({'case':case,'passed':bool(ok),'group':group,'observed':observed})
def request(o,row):return {'op':'details','snapshot':o['snapshot'],'detail_pin':o['detail_pin'],'as_of':o['as_of'],'row':row,'sku':unpack(o)[row]['sku']}
with Fake() as f:
 d=doc([unit(i,name='가상 긴 품목 이름과 조건을 보존하는 상세 안내 '+str(i)) for i in range(70)]);b=base();f.write(b,d);o=f.call();rows=unpack(o);ck('lookup_codec_reconstructs_exact_numbers_grades',all(row['preferred_price']==x['price_credits'] and row['grade']==x['grade'] for row,x in zip(rows,d['units'])))
 ck('all_account_fields_exact_under_codec',all(o['verified_context'][k]==v for k,v in b.items() if k!='inventory'))
 a=request(o,69);detail=f.call(a);ck('details_exact_last70_name_path',detail.get('name')==d['units'][69]['name'] and detail.get('category_path')==d['units'][69]['category_path'] and detail.get('sku')==d['units'][69]['sku'])
 ck('detail_does_not_emit_account_or_private_ref',all(k not in detail for k in ['verified_context','unit_ref','redeemable_mileage','preferences']))
 for label,mutation,expected in [('wrong_pin',{'detail_pin':'0'*64},'detail_observation_changed'),('wrong_snapshot',{'snapshot':'0'*64},'snapshot_changed'),('wrong_sku',{'sku':'Gffffffff'},'detail_row_not_found'),('bool_row',{'row':True},'invalid_args'),('row200',{'row':200},'invalid_args'),('bool_asof',{'as_of':False},'invalid_args'),('offset0',{'offset':0},'invalid_args'),('offset1',{'offset':1},'invalid_args')]:
  bad=dict(a,**mutation);ck('detail_reject_'+label,f.call(bad)=={'error':expected})
 changed=json.loads(json.dumps(d));changed['units'][69]['price_credits']+=1;f.write(b,changed);ck('details_reject_changed_source',f.call(a)=={'error':'snapshot_changed'})
 # Detail lookup reuses full body, exact long public text is fragmented without exposing account fields.
 longname='상세가상 '+'가'*2800;longpath=['food','나'*5000];f.write(base(),doc([unit(1,name=longname,category_path=longpath)]));o=f.call();a=request(o,0);parts=[];steps=0
 for _ in range(30):
  z=f.call(a);assert 'error' not in z,z;steps+=1;parts.append(z['fragment']['text']);a=z['next_args']
  if a is None:break
 full=json.loads(''.join(parts));ck('large_details_all_fragments_exact',a is None and full['name']==longname and full['category_path']==longpath,observed={'detail_calls':steps})
 ck('preview_marked_and_category_root_preserved',o['verified_context']['inventory']['text_limit'] is not None and unpack(o)[0]['name']!=longname and unpack(o)[0]['category_path']==['food'])
 # Benign product specification/date strings are not secret data.
 for label,value in [('date_spec','가상 상품 제조일 2026.11.25'),('numeric_dimensions','가상 규격 10 20 30 센티')]:
  f.write(base(),doc([unit(1,name=value)]));z=f.call();ck('benign_'+label+'_does_not_hold_all', 'verified_context' in z,'benign_text_goal',{'error':z.get('error')})
result={'ordinary_official_Toolbox_call':True,'manual_testing_flag':False,'synthetic_only':True,'checks':checks,'totals':{g:{'passed':sum(x['passed'] for x in checks if x['group']==g),'failed':sum(not x['passed'] for x in checks if x['group']==g)} for g in sorted({x['group'] for x in checks})},'model_verified_codec_use':False,'actual_model_or_market_calls':0,'production_integration_or_finance_claim':False}
(ROOT/'details-qa-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'totals':result['totals'],'failures':[x for x in checks if not x['passed']]},ensure_ascii=False))
