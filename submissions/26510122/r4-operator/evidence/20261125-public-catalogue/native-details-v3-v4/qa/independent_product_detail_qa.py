from pathlib import Path
from copy import deepcopy
import argparse,ast,hashlib,json,re,sys,tempfile,time
P=argparse.ArgumentParser();P.add_argument('--sources',required=True);P.add_argument('--output',required=True);P.add_argument('--operator-kit',default='/home/seop/.local/share/ourolabs-r4-checkout/submissions/26510122/r4-operator/kit');a=P.parse_args();source=Path(a.sources);out=Path(a.output);out.mkdir(parents=True,exist_ok=True);sys.path.insert(0,a.operator_kit);import agent_kit as official
checks=[]
# Execute only the unchanged pure command parser AST, never financial dispatcher operations.
dispatcher=Path(a.operator_kit).parent.parent/'round-4/codex-r4/dispatcher.py'
node=next(n for n in ast.parse(dispatcher.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='parse')
parser_ns={};exec(compile(ast.Module(body=[node],type_ignores=[]),str(dispatcher),'exec'),parser_ns)
def usable_CTA(reply,sku):
 explicit=('구매 '+sku) in reply or (sku+' 지금 구매할게요') in reply
 generic=bool(re.search(r'구매\s*<[^>]*(?:SKU|sku|상품코드)[^>]*>',reply))
 return (explicit or generic) and parser_ns['parse']('구매 '+sku)[0]=='buy'
def ck(n,b,observed=None):checks.append(dict(case=n,passed=bool(b),observed=observed))
def unit(i,**kw):
 x=dict(unit_ref='SYNTH-'+str(i),sku=f'G{i:08x}',name='[가상브랜드] 가상 두부 300g 2팩',category_path=['식품','두부'],state='available',grade='C',price_credits=12345+i,standard_fee_credits=0,expires_at=int(time.time())+900);x.update(kw);return x
def doc(rows):
 t=int(time.time());return dict(schema='outseop-r4.customer-offers.v1',shop='outseop-r4',observed_at=t-1,valid_until=t+148,units=rows)
def render(*items):return dict(op='render',items=[dict(sku=s,grade=g) for s,g in items])
with tempfile.TemporaryDirectory(dir=out,prefix='Synthetic-name-unit-') as tmp:
 root=Path(tmp);tool=root/'tools/public_catalogue';tool.mkdir(parents=True);(root/'logs').mkdir();inputs=root/'host_inputs';inputs.mkdir(mode=0o700);cache=inputs/'customer_offer_context.json'
 for n in ('logic.py','test.py','permission.yml','forge.json'):(tool/n).write_bytes((source/n).read_bytes())
 tb=official.Toolbox(root,dict(market='https://market.ourolabs.ai',name='outseop-r4',tokens={},addresses={},signer=official.Signer({},root)));calls=0
 def write(d):
  if cache.exists():cache.chmod(0o600)
  cache.write_bytes(d if isinstance(d,bytes) else json.dumps(d,ensure_ascii=False).encode());cache.chmod(0o400)
 def call(args):
  global calls;calls+=1;e=tb.call('public_catalogue',args);assert e.get('ok'),e;z=e['result'];ck('output5500_'+str(calls),len(json.dumps(z,ensure_ascii=False))<=5500,'output_budget')
  if z.get('status')=='rendered':ck('reply450_'+str(calls),len(z['reply'])<=450,'output_budget')
  return z
 u=unit(1,sku='Gabcdefab');d=doc([u]);write(d);z=call(render(('GABCDEFAB','C')));reply=z.get('reply','')
 ck('single_source_name_complete',z.get('status')=='rendered' and u['name'] in reply)
 ck('source_packaging_preserved','300g 2팩' in reply)
 ck('source_SKU_case_preserved','Gabcdefab' in reply and 'GABCDEFAB' not in reply)
 ck('source_grade_price_unchanged','C등급' in reply and '12,346크레딧' in reply)
 ck('market_whole_unit_one',bool(re.search(r'(?:판매|시장|거래|정단위|한.?단위).*1\s*(?:개|份|단위|회|묶음|세트)',reply)))
 ck('packaging_not_sold_as_split',not any(x in reply for x in ('낱개 판매','반팩 판매','분할 판매')))
 ck('purchase_next_step_CTA','구매' in reply and ('결제권' in reply or 'checkout' in reply.lower()) and 'Gabcdefab' in reply and usable_CTA(reply,'Gabcdefab'))
 ck('fees_gas_recheck','수수료' in reply and '가스' in reply and '재확인' in reply)
 ck('fixed_success_schema',set(z)=={'status','reply','observed_at','valid_until'})
 ck('original_times',z.get('observed_at')==d['observed_at'] and z.get('valid_until')==d['valid_until'])
 for n,name in enumerate(('[가상브랜드] 가상 계란 30구 2판','가상 2인용 찌개 재료 300g×3팩','가상 식품 (무게 미제공)','가상'+('긴'*105)+' 500g 4팩'),1):
  u=unit(n,name=name);write(doc([u]));v=call(render((u['sku'],'C')));ck('benign_name_and_packaging_'+str(n),v.get('status')=='rendered' and name in v['reply'])
 u1=unit(1,name='[가상] 동일 두부 300g 2팩');u2=unit(2,name='[가상] 동일 두부 300g 3팩');write(doc([u1,u2]));v=call(render((u1['sku'],'C'),(u2['sku'],'C')))
 ck('two_selected_names_units_present_or_explicit_budget_error',v.get('status')=='unavailable' and bool(v.get('reason')) or v.get('status')=='rendered' and all(u['name'] in v['reply'] and u['sku'] in v['reply'] for u in (u1,u2)))
 v=call(dict(op='fallback',text=u1['sku']+' 가격과 등급 알려주세요'));ck('fallback_has_source_name_unit_CTA',v.get('status')=='rendered' and u1['name'] in v['reply'] and '구매' in v['reply'] and ('결제권' in v['reply'] or 'checkout' in v['reply'].lower()) and usable_CTA(v['reply'],u1['sku']))
 for word in ('구매','결제','환불','권리','마일리지','대기권','비교','제외','다른','최저가','pay','refund'):
  v=call(dict(op='fallback',text=u1['sku']+' 가격과 '+word+' 알려주세요'));ck('fallback_financial_closed_'+word,v.get('status')=='unavailable' and 'reply' not in v)
 # Three explicitly-selected items must all appear or be refused; never silently drop one.
 three=[unit(i,name=f'가상 상품 {i} 100g {i}팩') for i in range(1,4)];write(doc(three));v=call(render(*[(u['sku'],'C') for u in three]));ck('three_never_silent_partial',v.get('status')=='unavailable' and bool(v.get('reason')) or v.get('status')=='rendered' and all(u['sku'] in v['reply'] for u in three))
 long=unit(1,name='가상 긴상품 '+('긴'*180)+' 700g 6팩');write(doc([long]));v=call(render((long['sku'],'C')));ck('long_name_no_hidden_packaging_loss',v.get('status')=='unavailable' and bool(v.get('reason')) or v.get('status')=='rendered' and '700g 6팩' in v['reply'] and ('…' in v['reply'] or long['name'] in v['reply']))
 for label,name in [('url','https://example.invalid/SYNTHETIC'),('wallet','판매자 '+('0x'+'a'*64)),('phone','가상 전화 010-1234-5678'),('bidi','가상\u202e상품'),('newline','가상\n상품')]:
  u=unit(1,name=name);write(doc([u]));v=call(render((u['sku'],'C')));ck('unsafe_name_no_disclosure_'+label,v.get('status')=='unavailable' and name not in json.dumps(v,ensure_ascii=False))
 # Same name prefix, different packaging at the end: initial search/context must expose enough to distinguish.
 prefix='[가상브랜드] '+('이름'*20)+' 가상 두부 '
 rows=[unit(1,name=prefix+'300g 2팩'),unit(2,name=prefix+'300g 3팩')];write(doc(rows));v=call(dict(op='search',q='두부',limit=8));names=[r[2] for r in v.get('rows',[])]
 ck('search_packaging_distinguishable',v.get('status')=='ready' and len(names)==2 and all(isinstance(x,str) for x in names) and names[0]!=names[1] and '2팩' in names[0] and '3팩' in names[1])
 ck('preview_metadata_consistent',v.get('status')=='ready' and v.get('text_limit',0)>=24 and v.get('catalogue',{}).get('name_preview_limit')==v.get('text_limit'))
 # Original prices/state/grade and no caller financial modifications.
 u=unit(1);write(doc([u]));ck('caller_price_rejected',call(dict(op='render',items=[dict(sku=u['sku'],grade='C',price_credits=1)]))==dict(status='unavailable',reason='invalid_args'))
 for state in ('reserved','sold_out','reconciling'):
  write(doc([dict(u,state=state)]));v=call(render((u['sku'],'C')));ck('state_closed_'+state,v.get('status')=='unavailable')
 write(doc([u,dict(u,unit_ref='other')]));v=call(render((u['sku'],'C')));ck('duplicate_pair_closed',v.get('status')=='unavailable')
 write(doc([dict(u,expires_at=None)]));v=call(render((u['sku'],'C')));ck('unknown_expiry_not_nonfood',v.get('status')=='rendered' and '미제공' in v['reply'] and '비식품' not in v['reply'])
 # Pagination output and exact next_args on new longer name previews.
 for n in (117,5000):
  rows=[unit(i,name='[가상] 포장이 다른 가상 상품 '+str(i)+' 300g 2팩') for i in range(1,n+1)];write(doc(rows));args=dict(op='search',q='상품',sort='source',limit=8);v=call(args);seen=[]
  for _ in range(100 if n==117 else 3):
   if v.get('status')!='ready':break
   seen.extend(r[0] for r in v['rows']);nx=v['catalogue']['next_args']
   if nx is None:break
   v=call(nx)
  ck('new_name_paging_'+str(n),v.get('status')=='ready' and seen==[u['sku'] for u in rows[:len(seen)]] and (n!=117 or len(seen)==117) and v['catalogue']['source_count']==n)
result=dict(source_hashes={n:hashlib.sha256((source/n).read_bytes()).hexdigest() for n in ('logic.py','test.py','permission.yml','forge.json')},checks=checks,passed=sum(c['passed'] for c in checks if c.get('observed')!='output_budget'),failed=sum(not c['passed'] for c in checks),ordinary_SDK_Toolbox_call=True,all_inputs_synthetic=True,manual_testing_flag=False,source_changes=False,actual_model_market_DB_wallet_calls=0)
(out/'independent-product-detail-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(dict(passed=sum(c['passed'] for c in checks),failed=result['failed'],failures=[c for c in checks if not c['passed']]),ensure_ascii=False))
