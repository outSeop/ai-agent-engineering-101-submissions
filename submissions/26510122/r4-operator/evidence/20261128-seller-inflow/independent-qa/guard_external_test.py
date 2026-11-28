from pathlib import Path
from contextlib import chdir,closing
from types import SimpleNamespace
from hashlib import sha256
import json,sys,shutil
BINDING=json.loads((Path.cwd()/'qa-binding.json').read_bytes());OP=Path(BINDING['operator']).resolve(strict=True);CODE=OP.parent/'round-4/codex-r4';sys.path[:0]=[str(CODE),str(Path(BINDING['support']))]
from portable_forum_contract import original_fixture,owned_offer

def test(run,kit):
 assert kit.testing is True
 top=run.__globals__;root=Path.cwd();base=root/'diagnostic-fixtures';base.mkdir(mode=0o700);cases=[];facts={}
 def use(name,fn,grade='A',life=7200):
  here=base/name;here.mkdir(mode=0o700);(here/'codex-r4').mkdir(mode=0o700)
  for p in (root/'codex-r4').iterdir():
   if p.is_file():shutil.copyfile(p,here/'codex-r4'/p.name)
  f=original_fixture(here,now=1795800000);item=owned_offer(f,name='합성 계란 10구',category='식품>계란',grade=grade,life=life)
  original_get=f.get
  def get(url,*,params=None,**kw):
   if url==f.kit.market+'/api/forum' and params and params.get('limit')==1:return f.response(url,[p for p in f.posts if p['id']>params['since']][:1])
   return original_get(url,params=params,**kw)
  f.get=get;policy=f.db_path.parent/'marketing-owner-policy.json';policy.write_text(json.dumps({'schema':'outseop-r4.marketing-owner.v1','active':True,'generation':'a'*64,'token':'b'*64}));policy.chmod(0o600)
  class Proxy:
   @property
   def testing(self):return kit.testing
   def __getattr__(self,n):return getattr(f.kit,n)
  with chdir(here),f.patches():
   top['OWNER']=w12=top['load_wrapper']();w12.OWNER=m11=w12.optimize_classifier(w12.load_verified11());m11.OWNER=m11.load_owner();v9=m11.OWNER.load_v9();v9.PARENT.time=SimpleNamespace(time=lambda:f.now)
   with closing(v9.PARENT.open_forum(f.kit.address('shop').lower(),f.db_path)):pass
   def call(action,**kw):return run({'action':action,'scheduler_generation':'a'*64,'operation_timeout':30,**kw},Proxy())
   fn(f,item,call,m11,v9)
   assert f.sends==0
 def case(name,fn,**kw):
  try:use(name,fn,**kw);cases.append({'case':name,'passed':True})
  except Exception as error:
   import traceback;traceback.print_exc();cases.append({'case':name,'passed':False,'error_type':type(error).__name__})
 def hard(f,item,call,m11,v9):
  offer={'sku':item['sku'],'grade':'A','name':item['name'],'category':item['category'],'price':10000,'expiry':f.now+7200,'certificate':True}
  positives={'계란 가격 문의드립니다.':'strict','계란이 필요한 상황이에요. 집에서 쓰기 편한 후보를 보고 싶어요.':'reference'}
  # Explicit generic constraints are judged per offered item, not discarded as soft context.
  for text,expected in positives.items():
   post={'id':1,'ts':f.now,'round':4,'role':'buyer','author':'synthetic-buyer','thread':None,'text':text};assert m11.classify(v9,post,offer,f.now)==expected
  negatives=['계란 C등급 가격 문의드립니다.','계란 7,000크레딧 이하 가격 문의드립니다.','계란 유통기한 3일 이상 가격 문의드립니다.','계란 20구 가격 문의드립니다.','GFFFFFFFF 가격 문의드립니다.','계란 말고 가격 문의드립니다.','계란 무가당 가격 문의드립니다.','계란 알레르기 있어서 가격 문의드립니다.','계란 영수증 가격 문의드립니다.','계란 환불 문의드립니다.','계란 구매했어요. 가격 문의드립니다.','계란 소포장만 가격 문의드립니다.','계란 USB 호환 가격 문의드립니다.','계란 5V 지원 가격 문의드립니다.']
  for text in negatives:
   post={'id':1,'ts':f.now,'round':4,'role':'buyer','author':'synthetic-buyer','thread':None,'text':text};assert m11.classify(v9,post,offer,f.now) is None
  facts['synthetic_predicate_checks']={'strict':1,'reference':1,'negative_denied':len(negatives)}
 def final_render(f,item,call,m11,v9):
  strict=f.add_post('계란 가격 문의드립니다.');reference=f.add_post('계란이 필요한 상황이에요. 집에서 쓰기 편한 후보를 보고 싶어요.')
  menu=call('slate_context');assert {strict['id'],reference['id']}<={r['thread'] for r in menu['source']['reply_options']}
  assert call('publish',decision={'action':'reply','sku':item['sku'],'grade':'A','thread':strict['id']})['status']=='posted';assert not f.calls[-1]['text'].startswith(m11.REFERENCE_TITLE)
  f.advance(331);assert call('publish',decision={'action':'reply','sku':item['sku'],'grade':'A','thread':reference['id']})['status']=='posted';body=f.calls[-1]['text'];assert body.startswith(m11.REFERENCE_TITLE);assert item['sku'] in body and '10,000' in body and 'A등급' in body and 'checkout_jwt' not in body
  facts['fake_final_render']={'strict_published':True,'reference_label_and_facts':True,'fake_POSTs':len(f.calls)}
 def fresh(f,item,call,m11,v9):
  p=f.add_post('계란 가격 문의드립니다.');assert call('slate_context')['source']['reply_options'];item['grade']='B';assert call('publish',decision={'action':'reply','sku':item['sku'],'grade':'A','thread':p['id']})['status']!='posted';assert not f.calls
  facts['final_grade_changed_POSTs']=0
 def urgent(f,item,call,m11,v9):
  assert call('publish',decision={'action':'spotlight','sku':item['sku'],'grade':'C'})['status']=='posted';f.advance(3601);menu=call('slate_context');assert any(r['sku']==item['sku'] and r['spotlight_eligible'] for r in menu['source']['items'])
  f.lost_response=True;assert call('publish',decision={'action':'spotlight','sku':item['sku'],'grade':'C'})['status']=='unknown';assert f.calls[-1]['text'].startswith(m11.URGENT_TITLE);assert len(f.calls)==2
  assert call('slate_context')['status']=='unresolved_publish';f.advance(121);assert call('reconcile')['status']=='reconciled';f.advance(3601)
  assert call('publish',decision={'action':'spotlight','sku':item['sku'],'grade':'C'})['status']!='posted';assert len(f.calls)==2
  facts['urgent_epoch_unknown']={'one_normal_plus_one_urgent_fake_POSTs':2,'same_day_urgent_repeat_denied':True,'unknown_original_reconcile_preserved':True}
 def fused_pack(f,item,call,m11,v9):
  offer={'sku':item['sku'],'grade':'A','name':'합성 두유 190ml 12팩','category':'식품>두유','price':8000,'expiry':f.now+7200,'certificate':True}
  for text in ['두유를 구할 수 있나요500ml','두유를 구할 수 있어요500ml','두유를 구매 원해요500ml','두유를 찾고 있어요500ml','두유를 구매하고 싶어요500ml','두유를 구매하려고요500ml','두유를 구할 수 있나요USB']:
   post={'id':1,'ts':f.now,'round':4,'role':'buyer','author':'synthetic-buyer','thread':None,'text':text};assert m11.classify(v9,post,offer,f.now) is None
  post={'id':1,'ts':f.now,'round':4,'role':'buyer','author':'synthetic-buyer','thread':None,'text':'두유 190ml가 필요해요'};assert m11.classify(v9,post,offer,f.now)=='strict'
  facts['fused_pack_boundary']={'attached_wrong_pack_or_Latin_denied':7,'normal_correct_pack_strict':1}
 case('fused_pack_three_negatives_correct_pack_control',fused_pack);case('strict_reference_and_14_hard_protected_negatives',hard);case('actual_parent_final_strict_reference_body',final_render);case('final_grade_change_blocks_POST',fresh);case('urgent_C_once_per_day_and_unknown_reconcile',urgent,grade='C',life=18000)
 (root/'guards-safe.json').write_text(json.dumps({'schema':'r4-native15-independent-legacy-guards.v1','passed':sum(c['passed'] for c in cases),'total':len(cases),'cases':cases,'facts':facts,'original_full_ForumFixture':True,'standard_SDK_test_mode':True,'pool_transport_branch_exercised':False,'legacy_testing_true_preserves_business_guards_only':True,'testing_flag_not_assigned':True,'all_POSTs_fake_only':True,'actual_API_Model_POST_finance_production_calls':0},indent=2))
