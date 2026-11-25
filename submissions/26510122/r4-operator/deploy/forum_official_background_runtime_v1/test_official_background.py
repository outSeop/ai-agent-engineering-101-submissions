from pathlib import Path
import importlib.util,json,sys,tempfile,unittest
from types import SimpleNamespace
OP=Path('/home/seop/.local/share/ourolabs-r4-checkout/submissions/26510122/r4-operator')
sys.path[:0]=[str(OP/'kit'),str(OP/'deploy')]
import agent_kit as official
import forum_campaign_operator as campaign
spec=importlib.util.spec_from_file_location('own_background',Path(__file__).with_name('r4_forum_official_background_host.py'));host=importlib.util.module_from_spec(spec);spec.loader.exec_module(host)
class Model:
 def __init__(self,decisions):self.decisions=iter(decisions);self.calls=0
 def complete(self,messages,**kwargs):self.calls+=1;return json.dumps(next(self.decisions))
def publish(sku='G01234567',grade='A'):return {'action':'forum_marketing','args':{'action':'publish','decision':{'action':'spotlight','sku':sku,'grade':grade}}}
def sleep():return {'action':'sleep','args':{'seconds':300}}
class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.op=Path(self.tmp.name)/'operator';self.op.mkdir();self.root=self.op.parent/'shop';self.root.mkdir();self.calls=[];self.active=False;self.clock=1000
  self.ctx={'name':'outseop-r4','market':'https://example.invalid','tokens':{},'addresses':{}}
  self.view={'status':'options','spotlight_allowed':True,'items':[{'sku':'G01234567','grade':'A','name':'fixture small A','spotlight_eligible':True},{'sku':'G89abcdef','grade':'C','name':'fixture C','spotlight_eligible':False}],'reply_options':[]}
  self.out={'status':'posted','post':123}
  def execute(args):
   self.calls.append(args)
   if args['action']=='reconcile':return {'status':'nothing_to_reconcile'}
   if args['action']=='context':return self.view
   return self.out
  self.c=SimpleNamespace(execute=execute,customer_active=lambda:self.active,next_poll=0)
  official.log=lambda *a,**k:None
 def hook(self,decisions=None):
  self.model=Model(decisions or [publish(),sleep()]);return host.BackgroundTick(official,self.c,self.op,self.root,{},self.model,self.ctx,campaign=campaign,now=lambda:self.clock)
 def joined(self):self.ctx.update(shop_url='https://example.invalid/shop');self.ctx['tokens']['shop']='SYNTHETIC_NO_REAL_TOKEN'
 def test_construction_before_join_no_ctx_shop_url(self):
  h=self.hook();self.assertEqual(h.tick()['status'],'registration_not_ready');self.assertEqual(self.calls,[]);self.assertEqual(self.model.calls,0)
 def test_same_ctx_after_join_works_original_runonce(self):
  h=self.hook();self.joined();r=h.tick();self.assertEqual(r['status'],'posted');self.assertEqual(r['publication_attempts'],1);self.assertEqual(self.model.calls,2)
 def test_closed_choice_can_repair_without_attempt(self):
  self.joined();h=self.hook([publish('G89abcdef','C'),publish(),sleep()]);r=h.tick();self.assertEqual(r['publication_attempts'],1);self.assertEqual(len([x for x in self.calls if x['action']=='publish']),1)
 def test_customer_priority_noexecute(self):
  self.joined();self.active=True;h=self.hook();self.assertEqual(h.tick()['status'],'postponed');self.assertEqual(self.calls,[])
 def test_cooldown_noexecute(self):
  self.joined();self.c.next_poll=1001;h=self.hook();self.assertEqual(h.tick()['status'],'postponed');self.assertEqual(self.calls,[])
 def test_unknown_no_retry(self):
  self.joined();self.out={'status':'unknown'};h=self.hook([publish(),publish(),sleep()]);r=h.tick();self.assertEqual(r['publication_attempts'],1);self.assertEqual(sum(x['action']=='publish' for x in self.calls),1)
 def test_private_request_response_outcome_persist(self):
  self.joined();h=self.hook();h.tick();folder=next((self.op/'runtime/forum-background-official').glob('tick-*'));self.assertTrue((folder/'model-request-1.json').exists());self.assertTrue((folder/'model-response-1-private.json').exists());self.assertTrue((folder/'publication-outcome-private.json').exists());self.assertNotIn(self.ctx['tokens']['shop'],(folder/'model-request-1.json').read_text());self.assertEqual((folder/'model-request-1.json').stat().st_mode&0o777,0o600)
 def test_native_full_audit_source_persists(self):
  self.joined();h=self.hook();old=self.c.execute
  def execute(args):
   if args['action']=='context':h.audit('native_input',{'items':[{'name':'PUBLIC_FIXTURE'}]});h.audit('native_result',self.view)
   return old(args)
  self.c.execute=execute;h.tick();folder=next((self.op/'runtime/forum-background-official').glob('tick-*'));self.assertEqual(len(list(folder.glob('native_input-*.json'))),1);self.assertEqual(len(list(folder.glob('native_result-*.json'))),1)
 def test_total_25_seconds_not_per_call(self):
  from unittest.mock import patch
  folder=Path(self.tmp.name)/'budget';folder.mkdir();clock=[0];timeouts=[]
  def complete(messages,**kwargs):timeouts.append(kwargs['timeout']);return '{}'
  with patch.object(host.time,'monotonic',side_effect=lambda:clock[0]):
   m=host.RecordingModel(SimpleNamespace(complete=complete),folder,[]);m.complete([]);clock[0]=10;m.complete([]);clock[0]=26
   with self.assertRaises(host.OfficialForumModelFailure):m.complete([])
  self.assertEqual(timeouts,[25,15]);self.assertEqual(m.calls,2)
if __name__=='__main__':unittest.main()
