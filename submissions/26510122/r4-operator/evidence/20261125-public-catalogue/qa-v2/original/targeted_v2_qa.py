from pathlib import Path
import argparse,hashlib,json,sys,tempfile,time
P=argparse.ArgumentParser();P.add_argument('--sources',required=True);P.add_argument('--output',required=True);a=P.parse_args();source=Path(a.sources);out=Path(a.output);out.mkdir(exist_ok=True,parents=True);op=Path('/home/seop/.local/share/ourolabs-r4-checkout/submissions/26510122/r4-operator');sys.path.insert(0,str(op/'kit'));import agent_kit as official
checks=[]
def ck(name,ok,observed=None):checks.append(dict(case=name,passed=bool(ok),observed=observed))
def unit(i,**kw):
 x=dict(unit_ref='SYNTH-'+str(i),sku=f'G{i:08x}',name='합성 상품 사과',category_path=['식품','과일'],state='available',grade='A',price_credits=1000+i,standard_fee_credits=2,expires_at=int(time.time())+1000);x.update(kw);return x
def doc(n):
 t=int(time.time());return dict(schema='outseop-r4.customer-offers.v1',shop='outseop-r4',observed_at=t-1,valid_until=t+148,units=[unit(i) for i in range(1,n+1)])
with tempfile.TemporaryDirectory(dir=out,prefix='Synthetic-targeted-') as t:
 root=Path(t);tool=root/'tools/public_catalogue';tool.mkdir(parents=True);(root/'logs').mkdir();inputs=root/'host_inputs';inputs.mkdir(mode=0o700);file=inputs/'customer_offer_context.json'
 for n in ('logic.py','test.py','permission.yml','forge.json'):(tool/n).write_bytes((source/n).read_bytes())
 tb=official.Toolbox(root,dict(market='https://market.ourolabs.ai',name='outseop-r4',tokens={},addresses={},signer=official.Signer({},root)))
 def write(d):
  if file.exists():file.chmod(0o600)
  file.write_text(json.dumps(d,ensure_ascii=False));file.chmod(0o400)
 def call(args):
  e=tb.call('public_catalogue',args);assert e.get('ok'),e;z=e['result'];assert len(json.dumps(z,ensure_ascii=False))<=5500;return z
 for n in (117,500):
  d=doc(n);write(d);last=d['units'][-1]['sku'];upper=last.upper()
  for label,req in [('literal',dict(text=upper+' 가격과 등급 알려주세요')),('focus',dict(text='가격 알려주세요',focus_skus=[upper])),('literal_priority',dict(text=upper+' 가격',focus_skus=[d['units'][0]['sku'],upper]))]:
   z=call(dict(op='context',**req));ck('late_'+label+'_'+str(n),z.get('status')=='ready' and [r[0] for r in z['rows']]==[last] and z['catalogue']['criteria']['skus']==[last],dict(returned=[r[0] for r in z.get('rows',[])]))
   if z.get('status')=='ready' and len(z['rows'])==1:
    item=dict(zip(('sku','grade'),z['rows'][0][:2]));ck('legacy_exact_source_match_'+label+'_'+str(n),any(u['sku']==item['sku'] and u['grade']==item['grade'] for u in d['units']))
  for word in ('말고 다른 상품','제외','대안','비교','대신','rather than','without'):
   z=call(dict(op='context',text=upper+' '+word+' 가격 알려주세요',focus_skus=[upper]));ck('neutral_'+word+'_'+str(n),z.get('status')=='ready' and z['catalogue']['criteria']['skus']==[] and z['catalogue']['matched_count']==n)
  z=call(dict(op='context',text='Gffffffff 가격 알려주세요'));ck('missing_literal_no_substitute_'+str(n),z.get('status')=='ready' and z['rows']==[] and z['catalogue']['missing_skus']==['Gffffffff'])
  ids=[u['sku'] for u in d['units'][-9:]];z=call(dict(op='context',text=' '.join(s.upper() for s in ids)+' 가격'));nx=z['catalogue']['next_args'];z2=call(nx);ck('literal_nine_paging_'+str(n),[r[0] for r in z['rows']]+[r[0] for r in z2['rows']]==ids and nx['skus']==ids and z2['query_id']==z['query_id'])
 # Source spellings stay distinct from normalized internal comparison; render feeds original exact financial lookup.
 d=doc(3);d['units'][0]['sku']='Gabcdefab';d['units'][1]['sku']='G0026722f';write(d)
 for u in d['units'][:2]:
  for opx,args in [('render',dict(items=[dict(sku=u['sku'].upper(),grade='A')])),('fallback',dict(text=u['sku'].upper()+' 가격 알려주세요'))]:
   z=call(dict(op=opx,**args));ck('source_spelling_'+opx+'_'+u['sku'],z.get('status')=='rendered' and u['sku']+' A등급' in z['reply'] and f"{u['price_credits']:,}크레딧" in z['reply'])
 # Canonical cursor accepts case-only equivalent filters; every substantive filter change is rejected.
 a=dict(op='search',skus=[u['sku'].upper() for u in d['units']],exclude_skus=[],grade='A',category='식품',q='상품 과일',sort='price_asc',max_price=2000,min_remaining_seconds=50,limit=1);z=call(a);nx=z['catalogue']['next_args'];z2=call(dict(nx,skus=[s.upper() for s in nx['skus']]));ck('cursor_casing_equivalent',z2.get('status')=='ready' and z2['query_id']==z['query_id'])
 for k,v in [('exclude_skus',['G00000003']),('q','사과'),('max_price',1999),('min_remaining_seconds',51),('grade','B'),('category','생활'),('sort','source'),('limit',2),('as_of',nx['as_of']-1)]:
  x=dict(nx);x[k]=v;ck('cursor_changed_'+k,call(x)==dict(status='unavailable',reason='query_restart_required'))
 for q in ('test@example.net','../folder','/etc/hosts','config.json','Bearer abcd','서울 테헤란로 123','test＠example.net','dir／file','eyJabc.def.ghi','ghp_abcdef'):
  ck('unsafe_q_'+q,call(dict(op='search',q=q))==dict(status='unavailable',reason='unsafe_query_cursor'))
 for word in ('구매','결제','환불','마일리지','대기권','동의','견적수락','권리','송금','다른','말고','제외','비교','최저가','추천','pay','buy','refund','instead'):
  z=call(dict(op='fallback',text='Gabcdefab 가격과 '+word+' 알려주세요'));ck('fallback_block_'+word,z==dict(status='unavailable',reason='fallback_not_applicable'))
 # Case-insensitive duplicate pair still fails closed; prices and rights are never accepted from args.
 d['units'].append(dict(d['units'][0],sku='GABCDEFAB',unit_ref='other'));write(d);z=call(dict(op='render',items=[dict(sku='Gabcdefab',grade='A')]));ck('case_duplicate_ambiguous',z==dict(status='unavailable',reason='selection_ambiguous'))
 for x in [dict(op='render',items=[dict(sku='Gabcdefab',grade='A',price=1)]),dict(op='fallback',text='Gabcdefab 가격',approved=True),dict(op='context',text='가격',focus_skus=[True])]:ck('invalid_untrusted_'+str(len(checks)),call(x)==dict(status='unavailable',reason='invalid_args'))
 result=dict(source_hashes={n:hashlib.sha256((source/n).read_bytes()).hexdigest() for n in ('logic.py','test.py','permission.yml','forge.json')},checks=checks,passed=sum(c['passed'] for c in checks),failed=sum(not c['passed'] for c in checks),all_inputs_synthetic=True,ordinary_official_Toolbox_call=True,clock_patched=False,manual_testing_flag=False,generated_source_changed=False,actual_model_market_DB_wallet_calls=0)
 (out/'targeted-v2-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(dict(passed=result['passed'],failed=result['failed'],failures=[c for c in checks if not c['passed']]),ensure_ascii=False))
