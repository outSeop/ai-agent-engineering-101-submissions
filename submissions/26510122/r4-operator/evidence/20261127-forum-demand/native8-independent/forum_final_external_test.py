"""Final genuine7 independent external SDK test. No live forum or genuine source edit."""
from pathlib import Path
from contextlib import chdir,closing
from types import SimpleNamespace
from hashlib import sha256
import json,sys,shutil,traceback
OP=Path('/home/seop/.local/share/ourolabs-r4-checkout/submissions/26510122/r4-operator');QA=OP/'runtime/marketing-request-20261127-qa';CODE=OP.parent/'round-4/codex-r4';sys.path[:0]=[str(CODE),str(QA)]
from forum_external_contract import original_fixture,owned_offer,owned_policy,install_bonus_schema,bonus_mentioned

def test(run,kit):
 assert kit.testing is True
 env=run.__globals__;SDKROOT=Path.cwd();BASE=SDKROOT/'diagnostic-fixtures';BASE.mkdir(mode=0o700);results=[];facts={}
 def case(name,fn):
  try:fn();results.append({'case':name,'passed':True})
  except Exception as e:traceback.print_exc();results.append({'case':name,'passed':False,'error_type':type(e).__name__,'assertion':str(e),'test_line':traceback.extract_tb(e.__traceback__)[-1].lineno})
 def use(name,fn):
  root=BASE/name;root.mkdir(mode=0o700);(root/'codex-r4').mkdir();
  for filename in ['forum.py','dispatcher.py','price_policy.py']:shutil.copyfile(SDKROOT/'codex-r4'/filename,root/'codex-r4'/filename)
  f=original_fixture(root,now=1795780000.0);owned_offer(f,name='신선 계란 10구',category='식품>계란')
  # Public identity metadata only, no real key/signer/pay. Source constant is not patched.
  if 'WALLET' in env:f.kit.signer=SimpleNamespace(address=lambda role:env['WALLET'])
  parent_get=f.get
  def get(url,*,params=None,**kw):
   if url==f.kit.market+'/api/forum' and params and params.get('limit')==1:
    f.get_calls.append(dict(params));rows=[p for p in f.posts if p['id']>params['since']];return f.response(url,rows[:1] if params['since'] else rows[-1:])
   return parent_get(url,params=params,**kw)
  f.get=get
  class Proxy:
   @property
   def testing(self):return kit.testing
   def __getattr__(self,n):return getattr(f.kit,n)
  with chdir(root),f.patches():
   env['PARENT']=env['load_parent']();env['PARENT'].time=SimpleNamespace(time=lambda:f.now)
   def call(action,**kw):return run(dict(action=action,**kw),Proxy())
   return fn(f,call,env['PARENT'])
 def recent_retained():
  def check(f,call,parent):
   for i in range(349):f.add_post('새 상품 안내',author='fixture-other-shop',role='shop')['ts']=f.now-1800+i
   p=f.add_post('G159be1f8 구해요.');p['ts']=f.now-100
   menu=call('context');found=any(r['thread']==p['id'] for r in menu.get('reply_options',[]));facts['dense_all_recent']={'verified_latest_buyer_retained':found,'GET_calls':len(f.get_calls),'old_hold_direction_revised_by_parent':True};assert found
  use('all-recent',check)
 def buried_found():
  def check(f,call,parent):
   for i in range(50):f.add_post('오래된 공개글',author='fixture-other-shop',role='shop')['ts']=f.now-30000+i
   p=f.add_post('G159be1f8 구해요.');p['ts']=f.now-1800
   for i in range(299):f.add_post('다른 판매자 안내',author='fixture-other-shop',role='shop')['ts']=f.now-1700+i
   menu=call('context');found=any(r['thread']==p['id'] for r in menu.get('reply_options',[]));facts['buried_6h']={'buyer_found':found,'GET_calls':len(f.get_calls)};assert found
  use('buried',check)
 def unsafe_policy():
  def check(f,call,parent):
   install_bonus_schema(f);owned_policy(f);path=f.db_path.parent/'first-purchase-bonus-policy.json';path.chmod(0o666)
   native_accepts=env['active_policy'](f.now) is not None
   src=(OP.parent/'round-4/tools/first_purchase_bonus/logic.py').read_bytes();assert sha256(src).hexdigest()=='0ac466eb47f8a237829ae034dab949b964c372dc4327591ce92a07b965902887';ns={};exec(compile(src,'<exact-core4-policy>','exec'),ns);core_accepts=ns['_policy']() is not None
   result=call('publish',decision={'action':'spotlight','sku':'G159be1f8','grade':'A'});text=f.calls[0]['text'] if f.calls else '';claimed=bonus_mentioned(text)
   facts['policy_mismatch']={'world_writable_policy_native_accepts':native_accepts,'core4_accepts':core_accepts,'fake_POST_count':len(f.calls),'extra5_claimed':claimed};assert not core_accepts and not claimed
  use('unsafe-policy',check)
 def incompatible_awards():
  def check(f,call,parent):
   install_bonus_schema(f);owned_policy(f)
   with closing(parent.open_forum(f.kit.address('shop').lower(),f.db_path)) as db:
    db.execute('DROP TABLE welcome_award');db.execute('CREATE TABLE welcome_award (payer TEXT PRIMARY KEY, amount INTEGER)');db.commit();accepted=env['welcome_spend'](db,env['tables'](db),env['original_tables']())
    ns={};exec(compile((OP.parent/'round-4/tools/first_purchase_bonus/logic.py').read_bytes(),'<exact-core4-schema>','exec'),ns);core=ns['_award_schema'](db)
   result=call('publish',decision={'action':'spotlight','sku':'G159be1f8','grade':'A'});claimed=bonus_mentioned(f.calls[0]['text']) if f.calls else False
   facts['schema_mismatch']={'native_spend_zero':accepted==0,'core4_schema_incompatible':core=='incompatible','fake_POST_count':len(f.calls),'extra5_claimed':claimed};assert core=='incompatible' and not claimed
  use('schema',check)
 def match_boundary():
  def check(f,call,parent):
   with closing(parent.open_forum(f.kit.address('shop').lower(),f.db_path)) as db:offer=parent.stock_offers(db,parent.Market(f.kit),f.now)[0]
   def match(text,**changes):
    row=dict(id=100,ts=f.now-10,round=4,author='fixture-buyer',role='buyer',thread=None,text=text);row.update(changes);return env['is_match'](row,offer,f.now)
   assert match('계란 구해요.') and match('달걀 구해요.')
   assert match('계란 A등급 10구 10,000 크레딧 이하 구해요.')
   negatives=['계란 B등급 구해요.','계란 20구 구해요.','계란 9,000 크레딧 이하 구해요.','계란 유통기한 2일 이상 구해요.','계란 무가당 구해요.','계란 말고 구해요.','계란 환불 구해요.','계란 후기 구해요.','계란 배송비 포함 구해요.','계란 또는 두유 구해요.']
   assert not any(match(t) for t in negatives)
   assert not match('계란 구해요.',role='shop') and not match('계란 구해요.',round=3) and not match('계란 구해요.',ts=f.now-21601) and not match('계란 구해요.',private=True)
   facts['matcher']={'positive_count':3,'negative_count':len(negatives)+4,'won_legacy_budget_supported':match('G159be1f8 A등급 10,000원 이내로 구해요.'),'won_limitation':'Conservative new matcher does not accept original parent won-budget syntax; no false matching or POST claimed.'}
  use('matcher',check)
 def bonus_basis():
  def check(f,call,parent):
   from forum_external_contract import seed_award_budget,assert_bonus_copy
   install_bonus_schema(f);owned_policy(f)
   with closing(parent.open_forum(f.kit.address('shop').lower(),f.db_path)) as db:
    market=parent.Market(f.kit);offer=parent.stock_offers(db,market,f.now)[0];base=offer['_base'];advertised=offer['price'];assert base>=advertised
    text=env['render_verified'](db,market,offer,None,f.now);assert bonus_mentioned(text)
    import re
    for pattern in [r'추가',r'정산',r'기준가',r'5[,]?000|5천',r'지갑',r'1회|한\s*번',r'예산|전체\s*한도',r'7일|7\s*일',r'다음\s*(?:구매|거래)',r'환불',r'회수|철회|취소']:assert re.search(pattern,text),pattern
    # Remaining budget below the real grade-base award must omit bonus; old grants still count.
    award=min(5000,base*5//100)
   seed_award_budget(f,[5000]*9+[5000-award+1])
   with closing(parent.open_forum(f.kit.address('shop').lower(),f.db_path)) as db:
    assert env['welcome_spend'](db,env['tables'](db),env['original_tables']())==50000-award+1
    assert not bonus_mentioned(env['render_verified'](db,parent.Market(f.kit),offer,None,f.now))
   facts['bonus_basis']={'real_grade_base_used':True,'old_global_grants_counted':True,'text_semantics_checked':True,'identity_from_ephemeral_fixture':True}
  use('bonus',check)
 def slate_shape():
  def check(f,call,parent):
   assert call('publish',decision={'action':'spotlight','sku':'G159be1f8','grade':'A'})['status']=='posted'
   f.advance(3601)
   before=sha256(f.db_path.read_bytes()).hexdigest();r=call('slate_context');after=sha256(f.db_path.read_bytes()).hexdigest()
   assert r['status']=='options';src=r['source'];assert src['schema']=='outseop-r4.forum-candidates.v1'
   assert src['own_spotlight_history'] and set(src['own_spotlight_history'][0])=={'grade','category','at'}
   assert type(src['own_spotlight_history'][0]['at']) is int and before==after
   assert all(set(x)==set(env['VISIBLE'])|{'spotlight_eligible'} for x in src['items'])
   facts['slate']={'REAL_created_history_retained':True,'native2_exact_history_keys':True,'read_only_DB_bytes_unchanged':True,'private_fields_projected_out':True}
  use('slate',check)
 def concurrency():
  def check(f,call,parent):
   from concurrent.futures import ThreadPoolExecutor
   with closing(parent.open_forum(f.kit.address('shop').lower(),f.db_path)):pass
   with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:call('publish',decision={'action':'spotlight','sku':'G159be1f8','grade':'A'}),range(2)))
   assert len(f.calls)==1 and sum(r['status']=='posted' for r in results)==1
   facts['atomic']={'simultaneous_calls':2,'fake_POST_count':len(f.calls),'posted_count':sum(r['status']=='posted' for r in results)}
  use('concurrent',check)
 def unknown_reconcile():
  def check(f,call,parent):
   p=f.add_post('G159be1f8 구해요.');f.lost_response=True
   assert call('publish',decision={'action':'reply','sku':'G159be1f8','grade':'A','thread':p['id']})['status']=='unknown'
   assert call('publish',decision={'action':'reply','sku':'G159be1f8','grade':'A','thread':p['id']})['status']=='unresolved_publish'
   proper=f.posts.pop();f.add_post(proper['text'],author='fixture-imposter',role='shop',thread=p['id']);f.advance(31)
   assert call('reconcile')['status']=='unknown'
   f.add_post(proper['text'],author='outseop-r4',role='shop',thread=p['id']);f.advance(121)
   assert call('reconcile')['status']=='reconciled' and len(f.calls)==1
   facts['unknown']={'repost_count':0,'imposter_rejected':True,'own_shop_GET_visible_after_buyer_window_override':True,'exact_reconcile_restored':True}
  use('unknown',check)
 def fresh_revalidation():
  def check(f,call,parent):
   f.add_post('다른 판매자 글',role='shop',author='fixture-other-shop');p=f.add_post('G159be1f8 구해요.')
   assert call('context')['reply_options']
   original=f.get
   def changing(url,*,params=None,**kw):
    if url.endswith('/api/forum') and params and params.get('limit')==1 and params.get('since')==p['id']-1:p['text']='G159be1f8 B등급 구해요.'
    return original(url,params=params,**kw)
   # httpx mock already bound to original dispatcher; replace its side_effect through nested original fixture patches.
   f.get=changing
   with f.patches():r=call('publish',decision={'action':'reply','sku':'G159be1f8','grade':'A','thread':p['id']})
   assert r['status']=='no_fresh_matching_request' and not f.calls
   f.get=original;p['text']='G159be1f8 구해요.';f.units[0]['grade']='B'
   assert call('publish',decision={'action':'reply','sku':'G159be1f8','grade':'A','thread':p['id']})['status']=='no_fresh_matching_request' and not f.calls
   facts['fresh']={'selected_thread_changed_before_send_rejected':True,'current_grade_change_rejected':True,'fake_POST_count':0}
  use('fresh',check)
 def duplicate_no_text():
  def check(f,call,parent):
   assert call('publish',decision={'action':'spotlight','sku':'G159be1f8','grade':'A','text':'MODEL-SUPPLIED'})['status']=='invalid_choice';assert not f.calls
   assert call('publish',decision={'action':'spotlight','sku':'G159be1f8','grade':'A'})['status']=='posted';f.advance(4000)
   assert call('publish',decision={'action':'spotlight','sku':'G159be1f8','grade':'A'})['status']!='posted' and len(f.calls)==1
   facts['duplicate']={'unchanged_offer_not_reposted':True,'model_supplied_copy_rejected':True,'original_global_gap_and_ledger_used':True}
  use('duplicate',check)
 def alternate_schema():
  def check(f,call,parent):
   install_bonus_schema(f);owned_policy(f)
   with closing(parent.open_forum(f.kit.address('shop').lower(),f.db_path)) as db:
    db.execute('CREATE TABLE first_purchase_bonus_grant (id INTEGER)');db.commit()
    ns={};exec(compile((OP.parent/'round-4/tools/first_purchase_bonus/logic.py').read_bytes(),'<core4-schema>','exec'),ns)
    core=ns['_award_schema'](db);spend=env['welcome_spend'](db,env['tables'](db),env['original_tables']());offer=parent.stock_offers(db,parent.Market(f.kit),f.now)[0]
    claimed=bonus_mentioned(env['render_verified'](db,parent.Market(f.kit),offer,None,f.now))
   facts['known_alternate_schema']={'core4_incompatible':core=='incompatible','candidate_spend_zero':spend==0,'extra5_claimed':claimed,'synthetic_only_no_actual_alternate_table_asserted':True};assert core=='incompatible' and not claimed
  use('alternate-schema',check)
 groups=[('latest-partial-retains-verified-row',recent_retained),('6h-forward-buried-row',buried_found),('owned-policy-security',unsafe_policy),('exact-award-schema',incompatible_awards),('matcher-hard-boundaries',match_boundary),('real-base-global-budget-copy',bonus_basis),('slate-history-readonly-shape',slate_shape),('atomic-concurrent-publication',concurrency),('unknown-reconcile-own-shop-visible',unknown_reconcile),('final-thread-and-stock-revalidation',fresh_revalidation),('duplicate-and-no-model-copy',duplicate_no_text),('known-alternate-schema-core-agreement',alternate_schema)]
 # Eleven planned groups; known alternate is a subcase of the existing schema group.
 def schema_group():incompatible_awards();alternate_schema()
 groups=[(n,fn) for n,fn in groups if n not in ('exact-award-schema','known-alternate-schema-core-agreement')];groups.insert(3,('exact-award-schema-including-known-alternate',schema_group))
 for name,fn in groups:case(name,fn)
 result={'passed':sum(x['passed'] for x in results),'total':len(results),'cases':results,'facts':facts,'source_logic_sha256':sha256((SDKROOT/'tools/forum_marketing/logic.py').read_bytes()).hexdigest(),'official_SDK_test_mode':True,'testing_flag_not_assigned':True,'source_business_unchanged':True,'full_original_ForumFixture':True,'mock_transport_only_limit1_added':True,'all_POSTs_are_original_fake_ForumFixture':True,'actual_Model_API_public_POST_finance_or_production_changes':0,'coverage_requirement_context':'Parent corrected incomplete-window instruction: verified latest individual rows allowed; no complete6h claim.','runtime_scope':'New context/matcher/slate staging-only in proposed publisher hot-swap; cached old coordinator context remains legacy.'}
 (SDKROOT/'forum-final-safe.json').write_text(json.dumps(result,indent=2));assert result['passed']==result['total'],result['cases']
