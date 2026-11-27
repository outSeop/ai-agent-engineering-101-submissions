"""Synthetic host transport + real SDK native2 dispatch + original SDK Mind.run_once. No API/Model/POST."""
from pathlib import Path
import importlib.util,json,sys,tempfile,time,unittest
from copy import deepcopy
from types import SimpleNamespace
OP=Path('/home/seop/.local/share/ourolabs-r4-checkout/submissions/26510122/r4-operator')
sys.path[:0]=[str(OP/'kit'),str(OP.parent/'round-4/codex-r4')]
import agent_kit as official
spec=importlib.util.spec_from_file_location('staged_marketing_glue',Path(__file__).with_name('marketing_request_glue.py'));host=importlib.util.module_from_spec(spec);spec.loader.exec_module(host)
import marketing_runtime

def choose(sku='G01234567',grade='A',thread=None):
 d={'action':'reply' if thread else 'spotlight','sku':sku,'grade':grade}
 if thread:d['thread']=thread
 return {'action':'forum_marketing','args':{'action':'publish','decision':d}}
def sleep():return {'action':'sleep','args':{'seconds':300}}
class FakeClassModel:
 def __init__(self,steps):self.steps=iter(steps);self.calls=0;self.messages=[]
 def complete(self,messages,**kwargs):self.calls+=1;self.messages.append(deepcopy(messages));return json.dumps(next(self.steps))
class GlueQA(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);base=Path(self.tmp.name);self.runtime=base/'operator';self.runtime.mkdir();self.root=base/'shop';self.root.mkdir();self.now=int(time.time());self.active=False;self.calls=[];self.pubresult={'status':'dry_selection'}
  official.mk.LOG_FILE=None
  self.sdk=host.capture_original_sdk(official,OP)
  self.source={'schema':'outseop-r4.forum-candidates.v1','observed_at':self.now,'valid_until':self.now+90,'spotlight_allowed':True,'own_spotlight_history':[{'grade':'C','category':None,'at':self.now-100},{'grade':'C','category':None,'at':self.now-200}],
   'items':[{'sku':'G01234567','grade':'A','name':'합성 차 2개입','price':1000,'category':'식품/차','expiry':self.now+9000,'certificate':True,'spotlight_eligible':True},{'sku':'G89abcdef','grade':'C','name':'합성 차 3개입','price':700,'category':'식품/차','expiry':self.now+8000,'certificate':True,'spotlight_eligible':True}],
   'reply_options':[{'thread':123,'request':'합성 차 A등급 찾아요','eligible':[{'sku':'G01234567','grade':'A'}]}]}
  self.envelope=lambda:{'status':'options','source':deepcopy(self.source)}
  def transport(args):
   self.calls.append(deepcopy(args))
   if args=={'action':'reconcile'}:return {'status':'nothing_to_reconcile'}
   if args=={'action':'slate_context'}:return self.envelope()
   if args.get('action')=='publish':return deepcopy(self.pubresult)
   raise AssertionError('unsupported synthetic transport action')
  self.transport=transport
  self.coordinator=marketing_runtime.MarketingCoordinator(transport,None,customer_active=lambda:self.active,now=lambda:self.now)
  self.ctx={'name':'outseop-r4','market':'https://market.ourolabs.ai','shop_url':'https://synthetic.invalid','tokens':{'shop':'SYNTHETIC_NOT_A_REAL_TOKEN'},'addresses':{}}
 def setup_hook(self,steps=None):
  self.model=FakeClassModel(steps or [choose(),sleep()])
  self.hook=host.build_stage(self.sdk,self.coordinator,OP,self.root,{},self.model,self.ctx,execute=self.transport,runtime_operator=self.runtime,clock=lambda:self.now)
  return self.hook
 def publications(self):return [x for x in self.calls if x['action']=='publish']
 def test_actual_sdk_native2_then_original_mind_dry_gate(self):
  h=self.setup_hook();r=h.tick();self.assertEqual(r['status'],'dry_selection');self.assertEqual(r['model_calls'],2);self.assertEqual(len(self.publications()),1)
  self.assertEqual([x['action'] for x in self.calls],['reconcile','slate_context','publish'])
  folders=list((self.runtime/'runtime/forum-background-official').glob('tick-*'));self.assertEqual(len(folders),1)
  self.assertEqual(len(list(folders[0].glob('native_input-*.json'))),1);self.assertEqual(len(list(folders[0].glob('native_result-*.json'))),1)
  text=json.dumps(self.model.messages,ensure_ascii=False);self.assertNotIn(self.ctx['tokens']['shop'],text);self.assertNotIn('wallet',json.dumps(self.source))
 def test_sdk_original_capture_survives_mutable_module_class_change(self):
  old=official.Mind
  try:
   official.Mind=SimpleNamespace(run_once=lambda:None)
   self.assertIs(self.sdk.Mind,old);self.assertIs(self.sdk.Mind.run_once,self.sdk.run_once)
  finally:official.Mind=old
 def test_private_item_field_rejected_before_model(self):
  self.source['items'][0]['cost']=500;h=self.setup_hook();r=h.tick();self.assertEqual(self.model.calls,0);self.assertFalse(self.publications());self.assertEqual(r['status'],'native_forum_slate_unavailable')
 def test_private_top_field_rejected(self):
  self.source['cash']=100000;h=self.setup_hook();h.tick();self.assertEqual(self.model.calls,0)
 def test_extra_envelope_rejected(self):
  self.envelope=lambda:{'status':'options','source':self.source,'private':{}};h=self.setup_hook();h.tick();self.assertEqual(self.model.calls,0)
 def test_stale_source_rejected(self):
  self.source['valid_until']=self.now;h=self.setup_hook();h.tick();self.assertEqual(self.model.calls,0)
 def test_future_source_rejected(self):
  self.source['observed_at']=self.now+1;h=self.setup_hook();h.tick();self.assertEqual(self.model.calls,0)
 def test_sensitive_text_rejected(self):
  self.source['items'][0]['name']='fixture '+'.'.join(['eyJ'+'a'*16,'b'*16,'c'*16]);h=self.setup_hook();h.tick();self.assertEqual(self.model.calls,0)
 def test_duplicate_pair_native_rejected(self):
  self.source['items'].append(deepcopy(self.source['items'][0]));h=self.setup_hook();h.tick();self.assertEqual(self.model.calls,0)
 def test_blockedstatus_forwarded_without_source_or_model(self):
  self.envelope=lambda:{'status':'cooldown'};h=self.setup_hook();r=h.tick();self.assertEqual(r['status'],'cooldown');self.assertEqual(self.model.calls,0)
 def test_customer_priority_no_source_or_model(self):
  self.active=True;h=self.setup_hook();r=h.tick();self.assertEqual(r['status'],'postponed');self.assertEqual(self.calls,[]);self.assertEqual(self.model.calls,0)
 def test_closed_C_choice_repairs_without_publishattempt(self):
  h=self.setup_hook([choose('G89abcdef','C'),choose(),sleep()]);r=h.tick();self.assertEqual(r['status'],'dry_selection');self.assertEqual(r['publication_attempts'],1);self.assertEqual(len(self.publications()),1);self.assertEqual(self.publications()[0]['decision']['grade'],'A')
 def test_unknown_publication_no_retry(self):
  self.pubresult={'status':'unknown'};h=self.setup_hook([choose(),choose(),sleep()]);r=h.tick();self.assertEqual(r['publication_attempts'],1);self.assertEqual(len(self.publications()),1)
 def test_exact_reply_uses_same_transport(self):
  h=self.setup_hook([choose(thread=123),sleep()]);h.tick();self.assertEqual(len(self.publications()),1);self.assertEqual(self.publications()[0]['decision']['thread'],123)
 def test_unlisted_reply_blocked_before_publisher(self):
  h=self.setup_hook([choose(thread=456),sleep()]);h.tick();self.assertFalse(self.publications())
 def test_false_first_signup_no_model(self):
  self.ctx.pop('shop_url');h=self.setup_hook();r=h.tick();self.assertEqual(r['status'],'registration_not_ready');self.assertEqual(self.model.calls,0);self.assertEqual(self.calls,[])
 def test_old_publisher5_cannot_enter_new_factory_transport(self):
  source=OP.parent/'round-4/tools/forum_marketing';pins={name:host.sha256((source/name).read_bytes()).hexdigest() for name in host.EXACT4}
  with self.assertRaises(ValueError):host.PinnedBusinessTransport(SimpleNamespace(root=self.root,ctx=self.ctx),source,pins,official)
 def test_unverified_fixture_cannot_implicitly_target_live_audit_root(self):
  with self.assertRaises(ValueError):host.build_stage(self.sdk,self.coordinator,OP,self.root,{},FakeClassModel([]),self.ctx,execute=self.transport)
 def test_publication_outcome_excludes_private_fields(self):
  with self.assertRaises(ValueError):host.public_outcome({'status':'posted','post':1,'cash':100})
  self.assertEqual(host.public_outcome({'status':'posted','post':1}),{'status':'posted','post':1})
 def test_factory_creates_no_loop_and_is_not_live_bound(self):
  h=self.setup_hook();self.assertTrue(h.staging_contract['original_run_once_preserved']);self.assertFalse(h.staging_contract['connected_to_running_main']);self.assertFalse(h.staging_contract['new_loop_created']);self.assertEqual(self.calls,[])
if __name__=='__main__':
 result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(GlueQA))
 summary={'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'genuine_native2_ordinary_SDK_used':True,'business_source_transport':'synthetic fixture; new genuine tool admission tested separately when frozen','Model':'Mock via original SDK Mind.run_once, no actual model API','HTTP_POSTs':0,'actual_Model_calls':0,'production_root_or_service_changes':0,'runtime_sessions_temporary_only':True,'connected_to_running_main':False}
 Path(__file__).with_name('SAFE-QA.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));raise SystemExit(not result.wasSuccessful())
