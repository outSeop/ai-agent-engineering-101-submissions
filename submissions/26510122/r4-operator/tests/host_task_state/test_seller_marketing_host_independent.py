"""Independent HOST boundary regressions. Synthetic temp state/owned children only.
No market/Model/network, keys, original business DB or production services.
"""
import asyncio,importlib.util,json,os,sqlite3,subprocess,sys,tempfile,threading,time,unittest
from pathlib import Path
SOURCE=Path(__file__).resolve().parents[2]/'src/r4_operator_host/seller_marketing_host.py'
spec=importlib.util.spec_from_file_location('seller_marketing_independent',SOURCE);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
GEN='a'*64;TOKEN='b'*64
class IndependentHostTests(unittest.TestCase):
 def fixture(self):
  temp=tempfile.TemporaryDirectory(prefix='r4-marketing-independent-');self.addCleanup(temp.cleanup);root=Path(temp.name);directory=root/'state/r4-benefits';directory.mkdir(mode=0o700,parents=True);p=directory/'marketing-owner-policy.json';p.write_text(json.dumps({'schema':'outseop-r4.marketing-owner.v1','active':True,'generation':GEN,'token':TOKEN}));p.chmod(0o600)
  return root,m.OwnerPolicy(root,GEN),m.JobStore(root/'host/marketing-jobs.sqlite3')
 async def invoke(self,app,receive_hook=None):
  response=[]
  async def receive():
   if receive_hook:receive_hook()
   return {'type':'http.request','body':json.dumps({'generation':GEN}).encode()}
  async def send(message):response.append(message)
  await app({'type':'http','method':'POST','path':m.IPC_PATH,'headers':[(b'authorization',('Bearer '+TOKEN).encode())]},receive,send)
  return response[0]['status']
 @staticmethod
 async def passthrough(scope,receive,send):raise AssertionError('unexpected public request')
 def test_timeout_has_no_TERM_grace_late_child_effect(self):
  root,_,_=self.fixture();ready=root/'ready';late=root/'late'
  child='import signal,time;from pathlib import Path;signal.signal(signal.SIGTERM,signal.SIG_IGN);Path('+repr(str(ready))+').write_text("ready");time.sleep(.6);Path('+repr(str(late))+').write_text("late");time.sleep(10)'
  parent='import subprocess,sys,time;subprocess.Popen([sys.executable,"-c",'+repr(child)+']);time.sleep(10)'
  started=time.monotonic();out=m.run_owned([sys.executable,'-c',parent],.3,root);elapsed=time.monotonic()-started
  self.assertTrue(ready.exists(),'fixture child must have installed TERM handler before deadline')
  time.sleep(.7);self.assertEqual(out['status'],'marketing_cycle_timeout');self.assertFalse(late.exists(),'owned TERM-resistant child initiated a late effect after the deadline')
  self.assertLess(elapsed,.8,'cleanup must not open a full second of late execution')
 def test_successful_worker_return_still_kills_its_owned_descendant(self):
  root,_,_=self.fixture();ready=root/'ready';late=root/'late'
  child='import time;from pathlib import Path;Path('+repr(str(ready))+').write_text("ready");time.sleep(.5);Path('+repr(str(late))+').write_text("late")'
  parent='import subprocess,sys,time;from pathlib import Path;subprocess.Popen([sys.executable,"-c",'+repr(child)+'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);\nfor _ in range(100):\n if Path('+repr(str(ready))+').exists():break\n time.sleep(.005)\nprint('+repr(m.RESULT_MARK+'{"status":"no_selection"}')+',flush=True)'
  result=m.run_owned([sys.executable,'-c',parent],2,root);self.assertTrue(ready.exists());self.assertEqual(result['status'],'no_selection');time.sleep(.6);self.assertFalse(late.exists())
 def test_ASGI_waits_for_first_cycle_and_conflicting_tick_is_409(self):
  _,policy,store=self.fixture();entered=threading.Event();release=threading.Event();events=[]
  def cycle(**kwargs):entered.set();self.assertTrue(release.wait(2));events.append('cycle_finished');return {'status':'no_selection'}
  app=m.HandoffASGI(self.passthrough,m.Controller(policy,store,cycle))
  async def check():
   first=asyncio.create_task(self.invoke(app));self.assertTrue(await asyncio.to_thread(entered.wait,1));self.assertFalse(first.done());self.assertEqual(await self.invoke(app),409);self.assertFalse(first.done());release.set();status=await first;events.append('old_tick_returned');return status
  try:self.assertEqual(asyncio.run(check()),200)
  finally:release.set()
  self.assertEqual(events,['cycle_finished','old_tick_returned'])
 def test_policy_disabled_after_HTTP_auth_blocks_claim(self):
  _,policy,store=self.fixture();called=[];app=m.HandoffASGI(self.passthrough,m.Controller(policy,store,lambda **kw:called.append(kw)))
  def disable():
   value=json.loads(policy.path.read_text());value['active']=False;policy.path.write_text(json.dumps(value))
  self.assertEqual(asyncio.run(self.invoke(app,disable)),503);self.assertEqual(called,[])
  with sqlite3.connect(store.path) as db:self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0],0)
 def test_disabled_policy_before_native_phase_prevents_tool_call(self):
  root,policy,_=self.fixture();value=json.loads(policy.path.read_text());value['active']=False;policy.path.write_text(json.dumps(value));calls=[]
  cycle=m.SDKForumCycle.__new__(m.SDKForumCycle);cycle.policy=policy;cycle.customer_active=lambda:False;cycle.maintenance=lambda:False;cycle.toolbox=type('Box',(),{'run':lambda *a,**kw:calls.append(kw)})()
  result=cycle.execute({'action':'publish','decision':{}},time.monotonic()+1,30)
  self.assertEqual(result,{'status':'postponed'});self.assertEqual(calls,[])
 def test_unknown_interruption_never_opens_new_selection(self):
  root,policy,store=self.fixture();old,_=store.claim(GEN)
  with sqlite3.connect(store.path) as db:db.execute("UPDATE jobs SET owner_process='99999999:0' WHERE id=?",(old,))
  cycle=m.SDKForumCycle.__new__(m.SDKForumCycle);cycle.refresh=lambda:None;cycle.sessions=root/'sessions';cycle.sessions.mkdir(mode=0o700);statuses=iter(['unknown','nothing_to_reconcile']);operations=[]
  def execute(args,deadline,budget):operations.append((args,budget));return {'status':next(statuses)}
  cycle.execute=execute;controller=m.Controller(policy,store,cycle)
  self.assertEqual(controller.run(GEN)['status'],'unknown')
  with sqlite3.connect(store.path) as db:self.assertEqual(db.execute('SELECT state FROM jobs WHERE id=?',(old,)).fetchone()[0],'interrupted')
  self.assertEqual(controller.run(GEN)['status'],'nothing_to_reconcile')
  with sqlite3.connect(store.path) as db:self.assertEqual(db.execute('SELECT state FROM jobs WHERE id=?',(old,)).fetchone()[0],'reconciled_interruption')
  self.assertEqual(operations,[({'action':'reconcile'},10),({'action':'reconcile'},10)])
  summaries=[json.loads(p.read_text()) for p in cycle.sessions.glob('*/SUMMARY-SAFE.json')];self.assertTrue(all(x['model_calls']==0 and x['publication_attempts']==0 for x in summaries))
if __name__=='__main__':unittest.main()
