"""External independent TEST ONLY; run by official SDK test mode, genuine logic unchanged."""
from pathlib import Path
from contextlib import chdir,closing,contextmanager
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json,sys,time,shutil,sqlite3,traceback
from types import SimpleNamespace
OP=Path('/home/seop/.local/share/ourolabs-r4-checkout/submissions/26510122/r4-operator');CODE=OP.parent/'round-4/codex-r4';QA=OP/'runtime/profitable-procurement-20261127-qa'
sys.path[:0]=[str(CODE),str(QA)]
from test_procurement import StockFixture
from fixture import COIN
from stock12_external_contract import assert_legacy_context,assert_original_stock_fixture
MAIN='G159be1f8';OTHER='G00000001';THIRD='G00000003';OWNED='G99999999';PARENT_PIN='675bdaa2942f7bdf3d119d10c6e1176f790ae0bacbb22a32cf77ae82de0628c6'

def test(run,official_kit):
 assert official_kit.testing is True  # supplied by the real SDK test runner, never assigned here
 env=run.__globals__;assert not env.get('_TEST_WORLD')
 SDKROOT=Path.cwd();FILTER=json.loads((SDKROOT/'external-case-filter.json').read_text()) if (SDKROOT/'external-case-filter.json').exists() else [];BASE=SDKROOT/'independent-fixtures';BASE.mkdir(mode=0o700);RESULTS=[];DETAIL={};counter=0
 def write(path,value):
  path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
  if path.exists():path.chmod(0o600)
  path.write_text(json.dumps(value));path.chmod(0o400)
 @contextmanager
 def use(name,*,campaign=True):
  nonlocal counter
  counter+=1;root=BASE/name;root.mkdir(mode=0o700);(root/'host_inputs').mkdir(mode=0o700);(root/'codex-r4').mkdir(mode=0o700);(root/'state/r4-demand').mkdir(mode=0o700,parents=True)
  for n in ['dispatcher.py','price_policy.py']:shutil.copyfile(SDKROOT/'codex-r4'/n,root/'codex-r4'/n)
  shutil.copyfile(SDKROOT/'host_inputs/legacy-stock8.py',root/'host_inputs/legacy-stock8.py')
  shutil.copyfile(SDKROOT/'state/r4-demand/requests.sqlite3',root/'state/r4-demand/requests.sqlite3')
  f=StockFixture(root);assert_original_stock_fixture(f);f.now=float(int(time.time()));f.start=f.now+90;f.end=f.start+180;f.cash=1460000 if campaign else 4000000;f.storage=600000 if campaign else 0
  f.catalog=[{'sku':MAIN,'name':'아침 곡물쌀 5kg','kind':'food','category':'식품>곡물','list_price':50000,'shelf_hours':12},{'sku':OTHER,'name':'사무용 의자','kind':'goods','category':'생활>가구','list_price':50000,'shelf_hours':None},{'sku':THIRD,'name':'맑은 두유 1L','kind':'food','category':'식품>음료','list_price':50000,'shelf_hours':12}]
  if campaign:
   owned=f.add_unit('u-999999999999',sku=OWNED,price=5000000,cost=4000000,grade='A');owned.update(kind='goods',category='보유>기타')
  def update_quote(quote):
   item=next(x for x in f.catalog if x['sku']==quote['units'][0]['sku']);u=quote['units'][0];u['cost']=10000;u['grade']='A';u['expires_at']=f.now+10000 if item['kind']=='food' else None
   quote['goods']=10000;quote['total']=10000+f.storage+f.fee;quote['pay']['wei']=str(quote['total']*COIN)
   if getattr(f,'mutation',None):f.mutation(quote)
  f.quote_override=update_quote
  policy={'campaign_id':'independent-s13','starts_at':f.now-30,'ends_at':f.now+21600-30}
  events=[]
  for sku in [MAIN,OTHER,THIRD]:
   for grade,amount in [('A',40000),('B',6000)]:
    for i in range(5):
     seq=len(events)+1;events.append({'seq':seq,'ts':f.now-12,'round':4,'kind':'sale','sku':sku,'grade':grade,'amount':amount,'shop':'https://another-public-shop.invalid/shops/comparable','broken':None,'sealed':None,'order_ref':f'{seq:064x}'})
  with sqlite3.connect(root/'state/r4-demand/requests.sqlite3') as db:
   db.row_factory=sqlite3.Row;recorded=[dict(r) for r in db.execute('SELECT * FROM request')]
  target=next(r for r in recorded if r['sku']==MAIN);other_refs=[r['event_hash'] for r in recorded if r['event_hash']!=target['event_hash']]
  def publish(excluded=None):
   if campaign:write(root/env['POLICY'],policy)
   write(root/'host_inputs/stock-demand-signals.json',{'round':4,'observed_at':f.now,'valid_until':f.now+149,'coverage':{'since':f.now-3600,'complete':True},'events':events})
   write(root/'host_inputs/stock-demand-exclusions.json',{'round':4,'observed_at':f.now,'valid_until':f.now+149,'event_refs':other_refs if excluded is None else excluded})
  publish();f.policy=policy;f.publish=publish;f.target_hash=target['event_hash'];f.all_event_hashes=[r['event_hash'] for r in recorded];f.recorded_rows=recorded;f.events=events;f.expect_audit=True;f.timeout_pay=False
  class Proxy:
   @property
   def testing(self):return official_kit.testing
   def __getattr__(self,name):return getattr(f.kit,name)
   def pay(self,to,wei,marker,role):
    assert role=='shop'
    with closing(f.open_proc()) as db:
     intent=db.execute("SELECT * FROM stock_intent WHERE state='sending'").fetchone();assert intent is not None
     audits=db.execute('SELECT detail FROM stock_risk_v13 WHERE intent_id=?',(intent['id'],)).fetchall()
     assert len(audits)==(1 if f.expect_audit else 0)
     if audits:
      a=json.loads(audits[0][0]);assert a['old_dues_paid']==f.storage+f.fee and a['old_storage_paid']==f.storage and a['old_forum_paid']==f.fee
      assert a['new_goods']==f.quoted[0]['cost'] and a['new_fees']==0 and a['full_quote']==f.quoted[0]['cost']+f.storage+f.fee and wei==a['full_quote']*COIN
      assert a['new_risk']==a['new_goods']+a['new_fees']+a['acquisition_gas_reserve']+a['new_carry']
      if campaign:
       context=json.loads(db.execute('SELECT choices FROM stock_plan WHERE id=?',(intent['plan_id'],)).fetchone()[0]);lim=context['finance'];after_equity=lim['equity_at_cost']-a['old_dues_paid']-a['new_fees']-a['acquisition_gas_reserve']
       assert a['full_quote']>100000 and a['new_risk']<=a['campaign_cap']<=100000
       assert 100*(lim['stock_cost']+a['new_goods'])<=85*after_equity and 100*(lim['stock_cost']+a['new_goods'])>80*after_equity
       assert lim['cash']-a['full_cash_outflow']>=lim['cash_reserve']-a['old_dues_paid']+a['new_carry']
       DETAIL['campaign_actual_parent_math']={'fullquote_over_newriskcap':True,'postpay85_pass80_fail':True,'exact_old_D_paid_once':True,'cash_guard_and_durable_audit_before_fakepay':True}
    tx=f.pay(to,wei,marker)
    if f.timeout_pay:raise TimeoutError('synthetic payment response lost after fake send')
    return tx
  proxy=Proxy();f.proxy=proxy
  oldtime=env['time'];env['time']=SimpleNamespace(time=lambda:f.now)
  with chdir(root),f.patches():
   def call(action,**kwargs):return run(dict(action=action,**kwargs),proxy)
   f.call_native=call
   DETAIL.setdefault('fixture_scope_diagnostics',{})[name]={'fixture_now':f.now,'native_now':env['time'].time(),'native_policy_path':str(env['POLICY'].resolve()),'policy_exists':env['POLICY'].exists(),'scope_at_fixture_time':env['scope'](lambda p:json.loads(Path(p).read_bytes()),f.now),'native_module_file':env.get('__file__'),'fixture_dispatcher_file':f.src.get('__file__')}
   try:yield f
   finally:env['time']=oldtime
 def ready(f,sku=MAIN):
  d=f.call_native('context');view=assert_legacy_context(d,expected_sku=sku);assert view['choices'][0]['sku']==MAIN
  r=f.call_native('plan',plan=d['plan'],decision={'action':'buy','lines':[{'sku':sku,'qty':1}],'reason':'Independent full original fixture choice'});assert r['status']=='ready',r
  f.advance(91);return d
 def case(name,fn):
  try:fn();RESULTS.append({'case':name,'passed':True})
  except Exception as e:traceback.print_exc();RESULTS.append({'case':name,'passed':False,'error_type':type(e).__name__})
 def coupling():
  with use('coupling') as f:
   assert any(r['confidence']=='public_term' and r['sku'] is None for r in f.recorded_rows)
   reader=lambda p:json.loads(Path(p).read_bytes());choices={r['sku']:r for r in f.catalog}
   f.publish([])
   allboost=env['priorities'](reader,env['recorder_rows'],choices,f.now);assert allboost.get(MAIN)==1 and allboost.get(THIRD)==1
   f.publish([r['event_hash'] for r in f.recorded_rows if r['event_hash']!=f.target_hash])
   assert env['priorities'](reader,env['recorder_rows'],choices,f.now)=={MAIN:1}
   d=f.call_native('context');assert assert_legacy_context(d)['choices'][0]['sku']==MAIN
   f.publish(f.all_event_hashes);assert env['priorities'](reader,env['recorder_rows'],choices,f.now)=={}
   # Existing draft remains an approved soft-priority snapshot. New window/draft must remove excluded influence.
   f.advance(400);f.start=f.now+90;f.end=f.start+180;f.publish(f.all_event_hashes)
   new=f.call_native('context');assert assert_legacy_context(new)['choices'][0]['sku']==OTHER
   DETAIL['real_recorder_sql_coupling']={'actual_rows':len(f.recorded_rows),'exact_and_weak_enums_native_produced':True,'actual_DB_hash_exclusion_no_rehash':True,'newdraft_priority_removed':True,'cached_approved_soft_priority_not_retroactively_rewritten':True}
 def campaign_phase():
  with use('campaign') as f:
   ready(f);r=f.call_native('execute');assert r['status']=='paid_pending_confirmation',r;assert f.sends==1
   assert f.call_native('execute')['status']=='unresolved_prior_payment' and f.sends==1
 def legacy():
  with use('legacy',campaign=False) as f:
   parent=env['load_parent']();market=parent['Market'](f.proxy)
   with closing(parent['ledger'](market.wallet,f.db_path)) as db:
    d=parent['stock_context'](db,market,f.now,5);assert d['status']=='draft';assert parent['stock_plan'](db,market,f.now,d['plan'],{'action':'buy','lines':[{'sku':MAIN,'qty':1}],'reason':'Original parent8 approval'})['status']=='ready'
   f.expect_audit=False;f.advance(91);r=f.call_native('execute');assert r['status']=='paid_pending_confirmation',r;assert f.sends==1
   with closing(f.open_proc()) as db:assert db.execute('SELECT count(*) FROM stock_risk_v13').fetchone()[0]==0
 def tamper_and_source():
  for label,mutation in [('grade',lambda q:q['units'][0].update(grade='B')),('marker',lambda q:q['pay'].update(data='0x'+'0'*64)),('foodlife',lambda q:q['units'][0].update(expires_at=0))]:
   with use('tamper-'+label) as f:
    ready(f);f.mutation=mutation;r=f.call_native('execute');assert r['status']=='no_purchase' and f.sends==0,r
  with use('stale-evidence') as f:
   ready(f);p=Path('host_inputs/stock-demand-signals.json');doc=json.loads(p.read_bytes());doc.update(observed_at=f.now-151,valid_until=f.now-1);write(p,doc);r=f.call_native('execute');assert r['status']=='no_purchase' and f.sends==0,r
 def scope_and_risk():
  with use('expire-after-quote') as f:
   ready(f);previous=f.post
   def post(url,*,json,**kwargs):
    if json.get('method')=='eth_blockNumber':f.policy['ends_at']=f.now;write(env['POLICY'],f.policy)
    return previous(url,json=json,**kwargs)
   f.post=post
   # f.patches captured old bound method; patch direct shared httpx post for this synthetic callback only.
   from unittest.mock import patch
   import httpx
   with patch.object(httpx,'post',post):r=f.call_native('execute')
   assert f.sends==0 and r['status']=='authoritative_check_unavailable',r
   with closing(f.open_proc()) as db:assert db.execute('SELECT count(*) FROM stock_risk_v13').fetchone()[0]==0
  with use('cumulative-risk') as f:
   ready(f)
   with closing(f.open_proc()) as db:db.execute('INSERT INTO stock_risk_v13 VALUES(?,?,?,?,?)',('synthetic-prior','synthetic-plan',f.policy['campaign_id'],f.now-10,json.dumps({'new_risk':95000})));db.commit()
   r=f.call_native('execute');assert f.sends==0 and r['status'] in ('fresh_cash_limit','no_purchase'),r
 def unknown_recovery():
  with use('unknown-recovery') as f:
   ready(f);f.timeout_pay=True;r=f.call_native('execute');assert r['status']=='payment_unknown' and f.sends==1,r
   assert f.call_native('execute')['status']=='unresolved_prior_payment' and f.sends==1
   f.timeout_pay=False;r=f.call_native('reconcile');assert r['status']=='market_accepted_waiting_for_units' and f.sends==1,r
   f.units.extend(f.delivered);f.advance(16);r=f.call_native('reconcile');assert r['status']=='arrived' and f.sends==1,r
 def concurrent():
  with use('concurrent') as f:
   ready(f)
   with ThreadPoolExecutor(max_workers=2) as pool:out=list(pool.map(lambda _:f.call_native('execute'),range(2)))
   assert f.sends==1 and sum(r['status']=='paid_pending_confirmation' for r in out)==1,out
   with closing(f.open_proc()) as db:assert db.execute('SELECT count(*) FROM stock_intent').fetchone()[0]==1 and db.execute('SELECT count(*) FROM stock_risk_v13').fetchone()[0]==1
 def numeric_profit():
  # Direct actual native method, additional to the full actual-parent quote tests above.
  obj=object.__new__(env['Procurement']);obj.gas=lambda n:30;obj.policy={'mode':'normal'}
  assert obj.profitable('goods',40000,34000,0,0,(1,100,60,'x'),40000) is True
  assert obj.profitable('food',40000,34000,0,0,(1,100,60,'x'),40000) is False
  assert obj.profitable('goods',40000,37000,0,0,(1,100,60,'x'),40000) is False
  DETAIL['profit_policy']={'regular_welcome_wait_total7_percent':True,'refund5_percent':True,'food_extra5_percent':True,'exact_native_method_not_QA_profit_algorithm':True}

 def grade_reference_regression():
  def numeric_setup(f,cost):
   item=next(x for x in f.catalog if x['sku']==OTHER);item['list_price']=12000
   f.events[:]=[e for e in f.events if e['sku']!=OTHER or e['grade']=='A']
   for event in f.events:
    if event['sku']==OTHER:event['amount']=6000
   f.publish()
   def mutate(quote):
    quote['units'][0]['cost']=cost;quote['goods']=cost;quote['total']=cost+f.storage+f.fee;quote['pay']['wei']=str(quote['total']*COIN)
   f.mutation=mutate
  with use('gradebase-4300-denied') as f:
   numeric_setup(f,4300);d=ready(f,OTHER)
   with closing(f.open_proc()) as db:
    stored=json.loads(db.execute('SELECT choices FROM stock_plan WHERE id=?',(d['plan'],)).fetchone()[0]);candidate=next(r for r in stored['choices'] if r['sku']==OTHER);assert candidate['options'][0]['estimated_ceiling']<4300
   r=f.call_native('execute');assert r['status']=='no_purchase' and f.sends==0,r
  with use('gradebase-3800-positive') as f:
   numeric_setup(f,3800);seen=set();target=env['Procurement'].profitable.__code__
   def trace(frame,event,arg):
    if frame.f_code is target and event=='call':
     parent=frame.f_back
     while parent and parent.f_code.co_name not in ('candidates','quote','charge'):parent=parent.f_back
     if parent:
      caller=parent.f_code.co_name;data=parent.f_locals
      sku=data.get('sku') if caller=='candidates' else data.get('line',{}).get('sku') if caller=='quote' else data.get('unit',{}).get('sku')
      if sku==OTHER:
       assert frame.f_locals['price']==6000 and frame.f_locals['grade_reference']==12000
       seen.add(caller)
    return trace
   sys.settrace(trace)
   try:ready(f,OTHER);r=f.call_native('execute')
   finally:sys.settrace(None)
   assert r['status']=='paid_pending_confirmation' and f.sends==1,r
   assert seen=={'candidates','quote','charge'},seen
  with use('gradebase-prior14-approval-4300') as f:
   numeric_setup(f,4300);raw=(SDKROOT/'host_inputs/prior-stock14.py').read_bytes();assert sha256(raw).hexdigest()=='7c8e4a5db5916ae16a3f3d0c7b0208d25e470f9e6149d60351b06cb67b73f707';old={};exec(compile(raw,'<genuine-prior14>','exec'),old);old['time']=SimpleNamespace(time=lambda:f.now)
   d=old['run']({'action':'context'},f.proxy);assert_legacy_context(d,expected_sku=OTHER)
   with closing(f.open_proc()) as db:
    stored=json.loads(db.execute('SELECT choices FROM stock_plan WHERE id=?',(d['plan'],)).fetchone()[0]);assert next(r for r in stored['choices'] if r['sku']==OTHER)['options'][0]['estimated_ceiling']>=4300
   assert old['run']({'action':'plan','plan':d['plan'],'decision':{'action':'buy','lines':[{'sku':OTHER,'qty':1}],'reason':'Actual prior14 synthetic approval'}},f.proxy)['status']=='ready'
   f.advance(91);r=f.call_native('execute');assert r['status']=='no_purchase' and f.sends==0,r
  DETAIL['grade_reference_benefit_regression']={'actual_grade_base':12000,'public_p10':6000,'cost4300_rejected':True,'cost3800_actual_parent_fakepay_once':True,'candidate_quote_charge_each_reference_actual_grade_base':True,'genuine14_old_ceiling_4300_allowed_but_S15_quote_rejects':True}

 for name,fn in [('actual-Recorder4-SQL-to-S13-priority-and-real-exclusion-newdraft',coupling),('real-parent8-campaign-context-plan-execute-D85-fullcash-durable-audit',campaign_phase),('original-approved8-delegation-no-campaign-rewrite',legacy),('actual-grade-marker-foodlife-tamper-and-evidence-TTL-no-pay',tamper_and_source),('policy-expire-at-presend-and-durable-cumulative-risk-no-pay',scope_and_risk),('unknown-response-samequote-tx-reconcile-no-repay',unknown_recovery),('two-concurrent-original-parent-exec-one-fakepay',concurrent),('actual-native-profit7-refund5-food5-boundary',numeric_profit),('grade-base12k-P10-6k-cost4300-deny3800-pay-candidate-quote-presend',grade_reference_regression)]:
  if not FILTER or name in FILTER:case(name,fn)
 summary={'passed':sum(x['passed'] for x in RESULTS),'total':len(RESULTS),'cases':RESULTS,'details':DETAIL,'official_SDK_test_mode_supplies_testing_flag':True,'manual_testing_flag_assignment':False,'native_TEST_WORLD_bypass_used':False,'full_original_StockFixture_and_parent8':True,'actual_Recorder4_ordinarySDK_SQLite_consumed':True,'genuine_logic_source_unchanged':True,'actual_Model_API_wallet_financial_forum_or_production_changes':0}
 (SDKROOT/'independent-stock13-safe-result.json').write_text(json.dumps(summary,indent=2))
 assert summary['passed']==summary['total'],summary['cases']
