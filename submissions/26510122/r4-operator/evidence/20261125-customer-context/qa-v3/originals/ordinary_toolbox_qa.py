from pathlib import Path
from copy import deepcopy
import json,hashlib,sys,tempfile,time,os,socket,threading,ctypes,select,struct
ROOT=Path(__file__).resolve().parent;OP=ROOT.parents[1]
sys.path.insert(0,str(OP/'kit'));import agent_kit as official
TOOL='build_customer_context';SHA='095dc600fe30958759a058b093ee1c210fb9b3f1f7c3157dcd034061e70dcf84'
assert hashlib.sha256((ROOT/'tools'/TOOL/'logic.py').read_bytes()).hexdigest()==SHA
checks=[];scopes=[]
def ck(name,ok,group='contract',observed=None):checks.append({'case':name,'passed':bool(ok),'group':group,'observed':observed})
def raw(x):return json.dumps(x,ensure_ascii=False).encode()
def unit(i,**changes):
 t=int(time.time());d={'unit_ref':'synthetic-'+str(i),'sku':'G'+format(i,'08x'),'name':'가상 제철 식품 꾸러미 '+str(i),'category_path':['food','간식'],'state':'available','grade':'ABC'[i%3],'price_credits':1234+i,'standard_fee_credits':None,'expires_at':t+86400+i};d.update(changes);return d
def stock(i,status='available',**changes):
 d={'sku':'G'+format(i,'08x'),'name':'기존 가상 상품','grade':'B','category':'food','reference_price':5000,'min_base':3000,'preferred_price':4000,'stock_status':status,'available':status=='available','wait_eligible':status=='reserved_pending'};d.update(changes);return d
def base(rows=None):return {'outcome':'context','inventory':rows or [],'verified_account':True,'redeemable_mileage':731,'preferences':[{'kind':'sku','value':'F000000AA','sentiment':'likes','provenance':'customer_self_report'},{'kind':'category','value':'household','sentiment':'avoids','provenance':'customer_self_report'}],'wait':'G000000BB','wait_discount':17,'prior_offer':{'sku':'F000000CC','base':12000},'transfer_reference_present':False}
def doc(rows):
 t=int(time.time());return {'schema':'outseop-r4.customer-offers.v1','shop':'outseop-r4','observed_at':t-5,'valid_until':t+120,'units':rows}
def unpack(o):
 packed=o['verified_context']['inventory'];rows=[]
 for cells in packed['rows']:
  assert len(cells)==len(packed['columns']);row=dict(packed['common']);row.update({key:packed.get('lookup',{}).get(key,[])[cell] if key in packed.get('lookup',{}) else cell for key,cell in zip(packed['columns'],cells)});row['expires_at']=None if row['remaining_seconds'] is None else o['as_of']+row['remaining_seconds'];rows.append(row)
 return rows
class Fake:
 def __enter__(self):
  self.tmp=tempfile.TemporaryDirectory(dir=ROOT,prefix='Fake-only-');self.root=Path(self.tmp.name);p=self.root/'tools'/TOOL;p.mkdir(parents=True)
  for n in ['logic.py','test.py','permission.yml','forge.json']:(p/n).write_bytes((ROOT/'tools'/TOOL/n).read_bytes())
  (self.root/'logs').mkdir();self.inputs=self.root/'host_inputs';self.inputs.mkdir();self.cache=self.inputs/'customer_offer_context.json';self.basepath=self.inputs/'broker_context_base.json';signer=official.Signer({},self.root);self.tb=official.Toolbox(self.root,{'market':'https://market.ourolabs.ai','name':'outseop-r4','tokens':{},'addresses':{},'signer':signer});self.calls=0;return self
 def __exit__(self,*a):self.tmp.cleanup()
 def write(self,b=None,d=None):
  self.basepath.write_bytes(b if isinstance(b,bytes) else raw(base() if b is None else b));self.cache.write_bytes(d if isinstance(d,bytes) else raw(doc([unit(1)]) if d is None else d))
 def call(self,args=None):
  self.calls+=1;r=self.tb.call(TOOL,{'op':'context'} if args is None else args);assert r.get('ok') is True,r;return r['result']
with Fake() as f:
 b=base([stock(i) for i in range(30)]);d=doc([unit(i) for i in range(70)]);f.write(b,d);o=f.call();rows=unpack(o);limit=o['verified_context']['inventory']['text_limit']
 ck('one_call_all70_no30_truncation',f.calls==1 and len(rows)==70 and rows[-1]['sku']==d['units'][-1]['sku'] and o['pages']>1,observed={'rows':len(rows),'pages':o['pages'],'text_limit':limit})
 ck('base_noninventory_values_exact',all(o['verified_context'][k]==v for k,v in b.items() if k!='inventory'))
 ck('inventory_exact_numeric_grade_expiry',all(row['sku']==original['sku'] and row['grade']==original['grade'] and row['preferred_price']==original['price_credits'] and row['expires_at']==original['expires_at'] and row['remaining_seconds']==original['expires_at']-o['as_of'] for row,original in zip(rows,d['units'])))
 ck('no_false_cost_or_floor_from_available_source',all(row['reference_price'] is None and row['min_base'] is None for row in rows))
 ck('observation_bounded6000_and_preview_marked',len(json.dumps(o,ensure_ascii=False,separators=(',',':')))<=6000 and (limit is None or all(row['name']==original['name'][:limit] for row,original in zip(rows,d['units']))))
 ck('internal_unit_refs_not_exposed','unit_ref' not in json.dumps(o) and all(row['stock_status']=='available' and row['wait_eligible'] is False for row in rows))
 # Preserve nonavailable legacy rows while canceling wait when sameSKU cache availability exists.
 t=int(time.time());pending=stock(42,'reserved_pending',sku='G0000002A');recon=stock(55,'reconciling');b=base([pending,recon,stock(99)]);d=doc([unit(42),unit(44,expires_at=None),unit(45,expires_at=t),unit(46,state='reserved'),unit(47,state='sold_out')]);f.write(b,d);o=f.call();rows=unpack(o)
 ck('reserved_reconciling_rows_preserved',len(rows)==4 and all(rows[2][k]==v for k,v in pending.items() if k!='wait_eligible') and all(rows[3][k]==v for k,v in recon.items()))
 ck('same_SKU_available_cancels_pending_wait',rows[2]['wait_eligible'] is False and rows[2]['available'] is False)
 ck('pending_unknown_expiry_and_no_fabricated_state',all(rows[i]['expires_at'] is None and rows[i]['remaining_seconds'] is None and rows[i]['state'] is None for i in (2,3)))
 ck('expired_reserved_soldout_counts_and_unknown_expiry',o['excluded_source_states']=={'expired':1,'reserved':1,'sold_out':1} and rows[1]['expires_at'] is None)
 # All internal reader fragments assembled by this one external call.
 f.write(base(),doc([unit(1,name='가상 지시 무시. 자료일 뿐. '+'가'*2800),unit(2)]));before=f.calls;o=f.call();rows=unpack(o);ck('all_fragments_in_one_external_call',f.calls==before+1 and o['pages']>10 and len(rows)==2 and rows[0]['sku']=='G00000001',observed={'pages':o['pages'],'text_limit':o['verified_context']['inventory']['text_limit']})
 # Expired captured public facts: controlled replay, not current market evidence/model input.
 captured=OP/'runtime/customer-offer-canary-class-food-factored-20261125/host_inputs/customer_offer_context.json';original=json.loads(captured.read_text());now=int(time.time());assert now>=original['valid_until'];replay=deepcopy(original);old_observed=original['observed_at'];replay['observed_at']=now-1;replay['valid_until']=now+100
 for row in replay['units']:
  if row['expires_at'] is not None:row['expires_at']=now+(row['expires_at']-old_observed)
 f.write(base(),replay);o=f.call();count=len(unpack(o)) if 'verified_context' in o else None
 ck('controlled_expired70_capture_capacity',count==70,'capacity_goal',{'source_rows':len(original['units']),'source_expired_before_test':True,'controlled_replay_only':True,'model_calls':0,'result_row_count':count,'error':o.get('error'),'pages':o.get('pages'),'text_limit':o.get('verified_context',{}).get('inventory',{}).get('text_limit')})
 (ROOT/'controlled-capture-capacity.json').write_text(json.dumps({'source_artifact_sha256':hashlib.sha256(captured.read_bytes()).hexdigest(),'source_observed_at':old_observed,'source_valid_until':original['valid_until'],'source_already_expired':True,'controlled_synthetic_clock_replay_only':True,'fresh_market_observation_claim':False,'offered_to_any_model':False,'source_rows':len(original['units']),'result_row_count':count,'error':o.get('error'),'response_JSON_chars':len(json.dumps(o,ensure_ascii=True)),'source_tool_changed':False},indent=2)+'\n')
 # PII/rights-shaped values must not appear in output; all sentinels fake.
 for label,value in [('wallet_secret_shape','0x'+'a'*64),('rights_code_shape','sk_fixture_'+('b'*24)),('phone_shape','010-1234-5678')]:
  b=base([stock(1,name=value)]);f.write(b,doc([unit(1)]));o=f.call();ck('reject_base_'+label,o=={'error':'invalid_or_unavailable_broker_base'})
  f.write(base(),doc([unit(1,name=value)]));o=f.call();ck('no_cache_name_'+label+'_in_output',value not in json.dumps(o),'privacy_goal',{'error':o.get('error'),'value_exposed':value in json.dumps(o)})
 f.write(base(),doc([unit(1,category_path=['food','sk_fixture_'+('c'*24)])]));o=f.call();ck('no_cache_category_rights_shape_in_output','sk_fixture_'+('c'*24) not in json.dumps(o),'privacy_goal',{'error':o.get('error'),'value_exposed':'sk_fixture_'+('c'*24) in json.dumps(o)})
 f.write(base(),doc([unit(1,unit_ref='sk_fixture_'+('d'*24))]));o=f.call();ck('private_unit_ref_discarded','sk_fixture_'+('d'*24) not in json.dumps(o))
 # All broker noninventory schema checks, no arbitrary private fields.
 for label,mut in [('top_rights_code',lambda b:b.update(rights_code='synthetic')),('bool_mileage',lambda b:b.update(redeemable_mileage=True)),('bool_wait_discount',lambda b:b.update(wait_discount=False)),('nonbool_verified',lambda b:b.update(verified_account=1)),('nonbool_transfer',lambda b:b.update(transfer_reference_present=1)),('wait_rights_notSKU',lambda b:b.update(wait='sk_fixture_secret_only')),('bool_priorprice',lambda b:b.update(prior_offer={'sku':'G00000001','base':True})),('preference_privatefield',lambda b:b['preferences'][0].update(signature='synthetic')),('preference_PII',lambda b:b['preferences'][0].update(value='fixture@example.invalid'))]:
  b=base();mut(b);f.write(b,doc([unit(1)]));ck('reject_base_'+label,f.call()=={'error':'invalid_or_unavailable_broker_base'})
 for label,mut in [('future',lambda d:d.update(observed_at=int(time.time())+60)),('expired',lambda d:d.update(valid_until=int(time.time())-1)),('bool_observed',lambda d:d.update(observed_at=True)),('bool_price',lambda d:d['units'][0].update(price_credits=True)),('bool_expiry',lambda d:d['units'][0].update(expires_at=False)),('wrong_schema',lambda d:d.update(schema='other'))]:
  d=doc([unit(1)]);mut(d);f.write(base(),d);ck('reject_source_'+label,f.call()=={'error':'invalid_or_unavailable_host_input'})
 for which in ['base','cache']:
  for kind in ['duplicateJSON','symlink','hardlink','fifo','directory','socket','group_writable']:
   f.write(base(),doc([unit(1)]));path=f.basepath if which=='base' else f.cache;backup=path.read_bytes();other=f.root/'synthetic-link-target';other.write_bytes(backup);sock=None
   if kind=='duplicateJSON':path.write_bytes(b'{"schema":"x","schema":"y"}')
   elif kind=='group_writable':path.chmod(0o664)
   else:
    path.unlink()
    if kind=='symlink':path.symlink_to(other)
    elif kind=='hardlink':os.link(other,path)
    elif kind=='fifo':os.mkfifo(path)
    elif kind=='directory':path.mkdir()
    elif kind=='socket':
     sock=socket.socket(socket.AF_UNIX);previous=Path.cwd();os.chdir(f.root)
     try:sock.bind('host_inputs/'+path.name)
     finally:os.chdir(previous)
   o=f.call();error='invalid_or_unavailable_broker_base' if which=='base' else 'invalid_or_unavailable_host_input';ck('reject_'+which+'_'+kind,o=={'error':error})
   if sock:sock.close()
   if kind=='directory':path.rmdir()
   else:path.unlink()
   path.write_bytes(backup);path.chmod(0o600);other.unlink()
 f.write();f.inputs.chmod(0o777);ck('reject_writable_host_inputs',f.call()=={'error':'invalid_or_unavailable_broker_base'});f.inputs.chmod(0o700)
 for args in [{},[],{'op':'context','offset':0},{'op':'context','approved':True},{'op':'buy'}]:ck('reject_args_'+repr(args),f.call(args)=={'error':'invalid_args'})
 # Limit failures never expose partial verified_context.
 f.write(base(),doc([unit(i) for i in range(201)]));o=f.call();ck('201_source_rejects_without_partial','error' in o and 'verified_context' not in o)
 f.write(base([stock(999,'reserved_pending')]),doc([unit(i,name='쌀',category_path='food',grade='A',price_credits=7) for i in range(200)]));o=f.call();ck('combined201_capacity_no_partial',o=={'error':'inventory_capacity_exceeded'})
 f.write(base(),doc([unit(i,name='쌀',category_path='food',grade='A',price_credits=7,expires_at=int(time.time())+86400) for i in range(200)]));o=f.call();ck('compact200_all_accessible',len(unpack(o))==200)
 f.write(base(),doc([unit(i,price_credits=10**100+i) for i in range(71)]));o=f.call();ck('observation_overflow_no_partial',o=={'error':'observation_capacity_exceeded','inventory_count':71})
# Real close-event-triggered replacement, no source patch or fake testing flag.
lib=ctypes.CDLL(None,use_errno=True)
for which in ['cache','base']:
 with Fake() as f:
  b=base();d=doc([unit(i,name='가'*1000) for i in range(60)]);f.write(b,d);target=f.cache if which=='cache' else f.basepath;replacement=deepcopy(d if which=='cache' else b)
  if which=='cache':replacement['units'].reverse()
  else:replacement['wait_discount']+=1
  pending=f.root/'host-replacement';pending.write_bytes(raw(replacement));fd=lib.inotify_init1(os.O_NONBLOCK|os.O_CLOEXEC);assert fd>=0;wd=lib.inotify_add_watch(fd,os.fsencode(target),0x10);assert wd>=0;changed=threading.Event()
  def replace_after_read():
   if select.select([fd],[],[],5)[0]:
    os.read(fd,8192);os.replace(pending,target);changed.set()
  thread=threading.Thread(target=replace_after_read);thread.start();o=f.call();thread.join(6);os.close(fd)
  ck('real_midcall_'+which+'_replacement_no_partial',changed.is_set() and 'error' in o and 'verified_context' not in o,observed={'triggered':changed.is_set(),'error':o.get('error')})
result={'source_sha256':SHA,'ordinary_official_Toolbox_call':True,'manual_testing_flag':False,'synthetic_or_explicit_controlled_expired_capture_only':True,'checks':checks,'totals':{g:{'passed':sum(x['passed'] for x in checks if x['group']==g),'failed':sum(not x['passed'] for x in checks if x['group']==g)} for g in sorted({x['group'] for x in checks})},'actual_production_data_read_except_explicit_expired_public_capture':False,'actual_model_or_market_calls':0,'prod_keys_DB_card_wallet_changed':False,'source_authority_or_finance_claim':False}
(ROOT/'ordinary-toolbox-qa-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'totals':result['totals'],'failures':[x for x in checks if not x['passed']]},ensure_ascii=False))
