from pathlib import Path
from copy import deepcopy
import argparse, hashlib, json, os, re, socket, sys, tempfile, time
P=argparse.ArgumentParser();P.add_argument('--sources',required=True);P.add_argument('--output',required=True);A=P.parse_args()
SOURCE=Path(A.sources);OUT=Path(A.output);OUT.mkdir(parents=True,exist_ok=True)
OP=Path('/home/seop/.local/share/ourolabs-r4-checkout/submissions/26510122/r4-operator')
sys.path.insert(0,str(OP/'kit'));import agent_kit as official
TOOL='public_catalogue';checks=[];times=[]
def ck(name,ok,group='contract',observed=None):checks.append(dict(case=name,passed=bool(ok),group=group,observed=observed))
def unit(i,**changes):
 t=int(time.time());x=dict(unit_ref='SYNTH-'+str(i),sku=f'G{i:08X}',name='합성 상품 사과 '+str(i),category_path=['식품','과일'],state='available',grade='ABC'[(i-1)%3],price_credits=1000+i,standard_fee_credits=12,expires_at=t+900)
 x.update(changes);return x
def doc(n=3):
 t=int(time.time());return dict(schema='outseop-r4.customer-offers.v1',shop='outseop-r4',observed_at=t-1,valid_until=t+148,units=[unit(i) for i in range(1,n+1)])
def search(**kw):return dict(op='search',**kw)
with tempfile.TemporaryDirectory(dir=OUT,prefix='Synthetic-only-') as temp:
 root=Path(temp);tool=root/'tools'/TOOL;tool.mkdir(parents=True);(root/'logs').mkdir();inputs=root/'host_inputs';inputs.mkdir(mode=0o700);cache=inputs/'customer_offer_context.json'
 for name in ('logic.py','test.py','permission.yml','forge.json'):(tool/name).write_bytes((SOURCE/name).read_bytes())
 tb=official.Toolbox(root,dict(market='https://market.ourolabs.ai',name='outseop-r4',tokens={},addresses={},signer=official.Signer({},root)))
 def write(d):
  if cache.exists():cache.chmod(0o600)
  cache.write_bytes(d if isinstance(d,bytes) else json.dumps(d,ensure_ascii=False).encode());cache.chmod(0o400)
 def call(a):
  t=time.perf_counter();e=tb.call(TOOL,a);times.append(time.perf_counter()-t)
  if e.get('ok') is not True: return dict(status='sdk_error',reason=e.get('error','unknown'))
  z=e['result'];ck('every_output_budget_'+str(len(times)),len(json.dumps(z,ensure_ascii=False))<=5500,'output_budget');return z
 for n in (117,200,500,1000,5000):
  d=doc(n);write(d);a=search(q='상품 과일',sort='price_asc',limit=8);z=call(a);seen=[];pages=0;filters=True;counts=True;allpage=True
  while z.get('status')=='ready':
   cat=z['catalogue'];rows=z['rows'];counts &= cat['source_count']==n and cat['matched_count']==n and cat['offset']==len(seen) and cat['returned_count']==len(rows)
   seen.extend(r[0] for r in rows);pages+=1;nx=cat['next_args']
   if nx is None:break
   filters &= all(nx.get(k)==v for k,v in a.items())
   if not allpage and pages>=4:break
   z=call(nx)
  ck('capacity_'+str(n),z.get('status')=='ready' and counts and filters and seen==[f'G{i:08X}' for i in range(1,len(seen)+1)] and (not allpage or len(seen)==n),'capacity',dict(total=n,observed=len(seen),pages=pages,all_pages=allpage))
  if n in (117,500):
   sku=f'G{n:08X}';z=call(dict(op='context',text=sku+' 가격과 등급 알려주세요',focus_skus=[sku]));ck('literal_last_row_context_'+str(n),z.get('status')=='ready' and [r[0] for r in z['rows']]==[sku],'goal',dict(returned_skus=[r[0] for r in z.get('rows',[])]))
   z=call(search(skus=[sku]));ck('last_row_search_'+str(n),z.get('status')=='ready' and [r[0] for r in z['rows']]==[sku])
 # Mixed/exclusion requests must keep initial context neutral, never select excluded SKU as purchase intent.
 d=doc(12);write(d);z=call(dict(op='context',text='G0000000C 말고 다른 상품 알려주세요'));ck('context_exclusion_not_restricted_to_literal',z.get('status')=='ready' and len(z['rows'])>1)
 # Every condition survives exact next_args; changing any cursor criterion requires restart.
 d=doc(20)
 for u in d['units']:u.update(grade='A',name='합성 빨간 사과',price_credits=1500)
 write(d);a=search(q=' 빨간   과일 ',skus=[f'G{i:08X}' for i in range(1,21)],exclude_skus=['G00000002'],category='식품',grade='A',max_price=1600,min_remaining_seconds=60,sort='expiry_asc',limit=2);z=call(a);nx=z.get('catalogue',{}).get('next_args');ck('all_filter_query_ready',z.get('status')=='ready' and bool(nx))
 if nx:
  expected=dict(a,q='빨간 과일');ck('next_args_preserve_all_filters',all(nx.get(k)==v for k,v in expected.items()))
  for key,val in [('q','사과'),('exclude_skus',[]),('skus',[]),('category','생활'),('grade','B'),('max_price',1601),('min_remaining_seconds',59),('sort','source'),('limit',3),('as_of',nx['as_of']-1),('snapshot','0'*64),('query_id','0'*64)]:
   bad=dict(nx);bad[key]=val;v=call(bad);ck('cursor_change_'+key,v==dict(status='unavailable',reason='query_restart_required'))
  for key in ('skus','exclude_skus','min_remaining_seconds','q'):
   bad=dict(nx);bad.pop(key);v=call(bad);ck('cursor_omission_'+key,v==dict(status='unavailable',reason='query_restart_required'))
  write(dict(d,units=list(reversed(d['units']))));ck('cursor_source_swap',call(nx)==dict(status='unavailable',reason='query_restart_required'))
 # Render uses exact source pair and no caller price/financial data.
 d=doc();write(d);sel=dict(op='render',items=[dict(sku='G00000003',grade='C'),dict(sku='G00000001',grade='A')]);z=call(sel);reply=z.get('reply','');ck('render_source_pair_order',z.get('status')=='rendered' and reply.splitlines()[0].startswith('G00000003 C등급') and '1,003크레딧' in reply and '1,001크레딧' in reply)
 ck('render_fixed_schema',set(z)=={'status','reply','observed_at','valid_until'} and len(reply)<=450 and '수수료·가스 별도' in reply and '결제 전' in reply)
 ck('render_no_name_ref_rights','합성' not in reply and 'SYNTH-' not in reply and all(k not in z for k in ('wallet','mileage','checkout_jwt','customer')))
 for label,change,reason in [('duplicate_available',lambda x:x['units'].append(dict(x['units'][0],unit_ref='other')),'selection_ambiguous'),('duplicate_reserved',lambda x:x['units'].append(dict(x['units'][0],unit_ref='other',state='reserved')),'selection_ambiguous'),('reserved',lambda x:x['units'][0].update(state='reserved'),'selection_unavailable'),('expired',lambda x:x['units'][0].update(expires_at=int(time.time())-1),'selection_unavailable'),('bool_price',lambda x:x['units'][0].update(price_credits=True),'selection_unavailable'),('bool_expiry',lambda x:x['units'][0].update(expires_at=False),'selection_unavailable')]:
  d=doc();change(d);write(d);v=call(sel);ck('render_all_or_nothing_'+label,v==dict(status='unavailable',reason=reason) and 'reply' not in v)
 d=doc();d['units'][0]['expires_at']=None;write(d);v=call(dict(op='render',items=[dict(sku='G00000001',grade='A')]));ck('unknown_expiry_not_nonfood',v.get('status')=='rendered' and '유통기한 미제공' in v['reply'] and '비식품' not in v['reply'])
 # Fallback closed opt-in; all information-only tests use synthetic names and no customer state.
 write(doc());v=call(dict(op='fallback',text='G00000001 가격과 등급 알려주세요'));ck('public_info_fallback_only',v.get('status')=='rendered' and v['reply'].startswith('현재 조회 목록 일부'))
 for word in ('구매','결제','환불','송금','취소','주문','대기권','마일리지','잔액','권한','계약','동의','견적수락','다른','말고','제외','대신','비교','추천','최저가','할인','포인트','pay','refund','buy','accept quote','instead','cheapest','order'):
  v=call(dict(op='fallback',text='G00000001 가격과 '+word+' 알려주세요'));ck('fallback_denies_'+word,v==dict(status='unavailable',reason='fallback_not_applicable'),'fallback_safety')
 for text in ('가격 알려주세요','G00000001','G00000001 가격 test@example.net','G00000001 가격 https://example.net'):
  ck('fallback_unverified_or_private_'+str(len(text)),call(dict(op='fallback',text=text))==dict(status='unavailable',reason='fallback_not_applicable'),'fallback_safety')
 # Type/schema/output/source safety, with actual filesystem boundary objects.
 invalid=[None,True,[],{'op':1},search(limit=True),search(offset=True),search(offset=1),search(max_price=True),search(max_price=0),search(max_price=1.0),search(min_remaining_seconds=True),search(q='x'*65),search(grade=''),search(skus=['../G00000001']),search(exclude_skus='bad'),search(sort='eval'),dict(op='context',text='x'*1501),dict(op='render',items=[dict(sku='G00000001',grade='A',price=1)]),dict(op='render',items=[dict(sku='G00000001',grade='A')]*2)]
 for i,a in enumerate(invalid):ck('invalid_args_'+str(i),call(a)==dict(status='unavailable',reason='invalid_args'))
 for label,change,reason in [('future',lambda x:x.update(observed_at=int(time.time())+60),'stale_snapshot'),('expired',lambda x:x.update(valid_until=int(time.time())-1),'stale_snapshot'),('long_TTL',lambda x:x.update(valid_until=x['observed_at']+151),'stale_snapshot'),('bool_observed',lambda x:x.update(observed_at=True),'invalid_snapshot'),('wrong_schema',lambda x:x.update(schema='bad'),'invalid_snapshot'),('too_many_rows',lambda x:x.update(units=[None]*5001),'invalid_snapshot'),('extra_rights',lambda x:x.update(wallet='SYNTHETIC'),'invalid_snapshot')]:
  d=doc();change(d);write(d);ck('snapshot_'+label,call(search())==dict(status='unavailable',reason=reason))
 for label,raw in [('duplicates',b'{"shop":"x","shop":"y"}'),('utf8',b'\xff'),('nan',b'{"x":NaN}')]:
  write(raw);ck('raw_'+label,call(search())==dict(status='unavailable',reason='invalid_snapshot'))
 for label in ('symlink','hardlink','fifo','directory','socket','mode600','over2MiB'):
  write(doc());other=root/'fake-source';other.write_bytes(cache.read_bytes());other.chmod(0o400);sock=None
  if label=='mode600':cache.chmod(0o600)
  elif label=='over2MiB':cache.chmod(0o600);cache.write_bytes(b' '*((2*1024*1024)+1));cache.chmod(0o400)
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
  ck('filesystem_'+label,call(search())==dict(status='unavailable',reason='source_unavailable'))
  if sock:sock.close()
  if label=='directory':cache.rmdir()
  else:cache.unlink()
  other.unlink()
 write(doc());inputs.chmod(0o777);ck('writable_parent_rejected',call(search())==dict(status='unavailable',reason='source_unavailable'));inputs.chmod(0o700)
result=dict(source_hashes={name:hashlib.sha256((SOURCE/name).read_bytes()).hexdigest() for name in ('logic.py','test.py','permission.yml','forge.json')},checks=checks,summary={g:dict(passed=sum(x['passed'] for x in checks if x['group']==g),failed=sum(not x['passed'] for x in checks if x['group']==g)) for g in sorted({x['group'] for x in checks})},ordinary_official_Toolbox_call=True,manual_testing_flag=False,all_inputs_synthetic=True,actual_model_market_DB_wallet_calls=0,generated_source_changed=False,durations_seconds=dict(calls=len(times),max=max(times),total=sum(times)))
(OUT/'ordinary-toolbox-qa-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(dict(summary=result['summary'],failures=[x for x in checks if not x['passed']],durations=result['durations_seconds']),ensure_ascii=False))
