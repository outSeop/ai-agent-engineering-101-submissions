from pathlib import Path
from copy import deepcopy
import json,sys,tempfile,time,os,socket,re,hashlib
ROOT=Path(__file__).resolve().parent;OP=ROOT.parents[1];sys.path.insert(0,str(OP/'kit'));import agent_kit as official
TOOL='render_public_product_reply';SHA='dc7e34eb065da6661f74aa7b8ab8bf2f9f3ee3e292fa83fac11c0a567c115bd7';assert hashlib.sha256((ROOT/'tools'/TOOL/'logic.py').read_bytes()).hexdigest()==SHA
checks=[]
def ck(name,ok,group='contract',observed=None):checks.append({'case':name,'passed':bool(ok),'group':group,'observed':observed})
def unit(i,**updates):
 t=int(time.time());x={'unit_ref':'SYNTHETIC-'+str(i),'sku':'G'+format(i,'08x'),'name':'PRIVATE_SYNTHETIC_NAME_DO_NOT_EXPOSE','category_path':['food'],'state':'available','grade':'ABC'[(i-1)%3],'price_credits':1000+i,'standard_fee_credits':12,'expires_at':t+600+i};x.update(updates);return x
def context():
 t=int(time.time());return {'schema':'outseop-r4.customer-offers.v1','shop':'outseop-r4','observed_at':t-1,'valid_until':t+100,'units':[unit(1),unit(2),unit(3)]}
def args(*pairs):return {'items':[{'sku':s,'grade':g} for s,g in (pairs or [('G00000001','A')])]}
with tempfile.TemporaryDirectory(dir=ROOT,prefix='Fake-only-') as temp:
 root=Path(temp);tool=root/'tools'/TOOL;tool.mkdir(parents=True);(root/'logs').mkdir();inputs=root/'host_inputs';inputs.mkdir(mode=0o700);cache=inputs/'customer_offer_context.json'
 for n in ['logic.py','test.py','permission.yml','forge.json']:(tool/n).write_bytes((ROOT/'tools'/TOOL/n).read_bytes())
 signer=official.Signer({},root);tb=official.Toolbox(root,{'market':'https://market.ourolabs.ai','name':'outseop-r4','tokens':{},'addresses':{},'signer':signer})
 def write(x):
  if cache.exists():cache.chmod(0o600)
  cache.write_bytes(x if isinstance(x,bytes) else json.dumps(x,ensure_ascii=False).encode());cache.chmod(0o400)
 def call(a=None):
  envelope=tb.call(TOOL,args() if a is None else a);assert envelope.get('ok') is True,envelope;return envelope['result']
 d=context();write(d);out=call(args(('G00000003','C'),('G00000001','A'),('G00000002','B')));text=out.get('reply','')
 ck('three_exact_selected_pairs_order',out['status']=='rendered' and [line.split()[0] for line in text.splitlines()[:3]]==['G00000003','G00000001','G00000002'])
 ck('only_fixed_success_keys',set(out)=={'status','reply','observed_at','valid_until'})
 ck('source_prices_grades_only',all(f"{x['sku']} {x['grade']}등급 · {x['price_credits']:,}크레딧" in text for x in d['units']))
 ck('no_private_name_ref_fee_or_financial_data','PRIVATE_SYNTHETIC' not in text and 'SYNTHETIC-' not in text and all(k not in out for k in ['data','checkout_jwt','wallet','customer','mileage']))
 ck('fees_separate_and_reconfirmation','수수료·가스 별도' in text and '결제 전 재고·조건 재확인' in text)
 ck('reply450_snapshot_times_exact',len(text)<=450 and out['observed_at']==d['observed_at'] and out['valid_until']==d['valid_until'])
 remaining=[int(x) for x in re.findall(r'남은 시간 (\d+)초',text)];ck('remaining_conservative',len(remaining)==3 and all(v<=row['expires_at']-out['observed_at'] for v,row in zip(remaining,[d['units'][2],d['units'][0],d['units'][1]])))
 # Exact grade selection: sameSKU distinct grades is valid, samepair multiplicity is not.
 d=context();d['units'].append(unit(8,sku='G00000001',grade='C',price_credits=555));write(d);z=call(args(('G00000001','C')));ck('sameSKU_correct_grade_selected',z['status']=='rendered' and '555크레딧' in z['reply'] and '1,001' not in z['reply'])
 for label,a in [('no_items',{}),('empty',{'items':[]}),('four',{'items':[{'sku':'G00000001','grade':'A'}]*4}),('duplicate',args(('G00000001','A'),('G00000001','A'))),('extra_price',{'items':[{'sku':'G00000001','grade':'A','price_credits':1}]}),('extra_jwt',dict(args(),checkout_jwt='fake')),('extra_to',dict(args(),to='fake')),('extra_approved',dict(args(),approved=True)),('extra_text',dict(args(),text='환불 완료')),('grade_bool',{'items':[{'sku':'G00000001','grade':True}]}),('sku_path',args(('../G00000001','A')))]:ck('invalid_args_'+label,call(a)=={'status':'unavailable','reason':'invalid_args'})
 for label,mut,expected in [('missing',lambda x:x['units'].pop(0),'selection_unavailable'),('wrong_grade',lambda x:x['units'][0].update(grade='B'),'selection_unavailable'),('reserved',lambda x:x['units'][0].update(state='reserved'),'selection_unavailable'),('sold',lambda x:x['units'][0].update(state='sold_out'),'selection_unavailable'),('expired',lambda x:x['units'][0].update(expires_at=int(time.time())-1),'selection_unavailable'),('duplicate_available',lambda x:x['units'].append(dict(x['units'][0],unit_ref='other')),'selection_unavailable'),('duplicate_reserved',lambda x:x['units'].append(dict(x['units'][0],unit_ref='other',state='reserved')),'selection_unavailable'),('bool_price',lambda x:x['units'][0].update(price_credits=True),'invalid_snapshot'),('bool_expiry',lambda x:x['units'][0].update(expires_at=False),'invalid_snapshot'),('max_price_exceeded',lambda x:x['units'][0].update(price_credits=10**12+1),'invalid_snapshot'),('future',lambda x:x.update(observed_at=int(time.time())+60),'stale_snapshot'),('expired_snapshot',lambda x:x.update(valid_until=int(time.time())-1),'stale_snapshot'),('overlong_TTL',lambda x:x.update(valid_until=x['observed_at']+151),'stale_snapshot'),('wrong_schema',lambda x:x.update(schema='other'),'invalid_snapshot'),('bool_observed',lambda x:x.update(observed_at=True),'invalid_snapshot')]:
  d=context();mut(d);write(d);z=call(args(('G00000001','A'),('G00000002','B')));ck('all_or_nothing_'+label,z=={'status':'unavailable','reason':expected} and 'reply' not in z)
 write(b'{"shop":"x","shop":"y"}');ck('duplicateJSON_rejected',call()=={'status':'unavailable','reason':'invalid_snapshot'})
 write(b'\xff');ck('invalidUTF8_rejected',call()=={'status':'unavailable','reason':'invalid_snapshot'})
 d=context();d['units'][0]['expires_at']=10**500;write(d);ck('overlong_reply_no_partial',call()=={'status':'unavailable','reason':'reply_too_long'})
 d=context();d['units'][0].update(expires_at=None,category_path=['food']);write(d);z=call();ck('unknown_expiry_not_inferred_nonfood','비식품' not in z.get('reply',''),'semantic_goal',{'status':z.get('status'),'inferred_nonfood':'비식품' in z.get('reply','')})
 # Actual filesystem variants; no source mocking or testing flag.
 for label in ['symlink','hardlink','fifo','directory','socket','mode600']:
  write(context());data=cache.read_bytes();other=root/'fake-source';other.write_bytes(data);other.chmod(0o400);sock=None
  if label=='mode600':cache.chmod(0o600)
  else:
   cache.unlink()
   if label=='symlink':cache.symlink_to(other)
   elif label=='hardlink':os.link(other,cache)
   elif label=='fifo':os.mkfifo(cache)
   elif label=='directory':cache.mkdir()
   else:
    sock=socket.socket(socket.AF_UNIX);prev=Path.cwd();os.chdir(root)
    try:sock.bind('host_inputs/customer_offer_context.json')
    finally:os.chdir(prev)
  z=call();ck('filesystem_'+label,z=={'status':'unavailable','reason':'source_unavailable'})
  if sock:sock.close()
  if label=='directory':cache.rmdir()
  else:cache.unlink()
  other.unlink();write(context())
 inputs.chmod(0o777);ck('writable_parent_rejected',call()=={'status':'unavailable','reason':'source_unavailable'});inputs.chmod(0o700)
 # Informational renderer is not itself an exception to Broker's original guard.
 ck('existing_money_guard_would_still_block_rendered_text',bool(re.search(r'\d[\d,.\s]*(?:credits?|크레딧|원|wei|tokrw|eth)',text,re.I)))
result={'reviewed_logic_sha256':SHA,'ordinary_official_Toolbox_call':True,'manual_testing_flag':False,'all_inputs_synthetic':True,'checks':checks,'totals':{g:{'passed':sum(x['passed'] for x in checks if x['group']==g),'failed':sum(not x['passed'] for x in checks if x['group']==g)} for g in sorted({x['group'] for x in checks})},'actual_Broker_originalSDK_classModel_finalHTTP_E2E_done':False,'actual_model_market_DB_wallet_calls':0,'generated_source_changed':False}
(ROOT/'ordinary-toolbox-qa-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'totals':result['totals'],'failures':[x for x in checks if not x['passed']]},ensure_ascii=False))
