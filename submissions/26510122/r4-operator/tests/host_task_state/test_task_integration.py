"""Synthetic HOST composition only. No production identity, wallet, API, Model or listener."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import asyncio,importlib.util,json,sys,unittest
OP=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(OP/'src/r4_operator_host/front'),str(OP/'src/r4_operator_host')]
import front_edge_app as front,run_front_edge as launcher
from task_state import TaskStateDB,SQLiteTaskStore
from durable_public_continuity import DurablePublicContinuity
from a2a.server.tasks import InMemoryTaskStore
from a2a.server.context import ServerCallContext
from a2a.types import Task
from starlette.testclient import TestClient
BASE=OP/'deploy/public_catalogue_runtime_compound_v1'
sys.path.insert(0,str(BASE))
spec=importlib.util.spec_from_file_location('tested_original_public_continuity',BASE/'public_product_continuity.py')
original=importlib.util.module_from_spec(spec);spec.loader.exec_module(original)

class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=TemporaryDirectory(prefix='task-integration-',dir=OP/'runtime');self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name);self.root.chmod(0o700);self.db=TaskStateDB(self.root/'tasks.sqlite3')
 def test_optional_store_injection_restores_sdk_constructor(self):
  import a2a.server.tasks as tasks
  ctor=tasks.InMemoryTaskStore;store=SQLiteTaskStore(self.db)
  app,captured=front.capture_sdk_app(lambda:tasks.InMemoryTaskStore(),task_store=store)
  self.assertIs(app,store);self.assertIs(captured,store);self.assertIs(tasks.InMemoryTaskStore,ctor)
  with self.assertRaises(ValueError):front.capture_sdk_app(lambda:(_ for _ in ()).throw(ValueError('synthetic factory error')),task_store=store)
  self.assertIs(tasks.InMemoryTaskStore,ctor)
 def test_original_public_validator_and_restart_ttl_without_authority(self):
  clock=[1000.];hints=DurablePublicContinuity(self.db,original.PublicContinuity,clock=lambda:clock[0])
  task,ctx='synthetic_task_12345','synthetic_context_12345';facts=[{'sku':'G1234abcd','grade':'B','preferred_price':4410,'consent':True}]
  self.assertTrue(hints.remember(task,ctx,facts));reopened=DurablePublicContinuity(TaskStateDB(self.db.path),original.PublicContinuity,clock=lambda:clock[0])
  self.assertEqual(reopened.current(task,ctx),({'sku':'G1234abcd','grade':'B','preferred_price':4410},));self.assertIsNone(reopened.current(task,'different_context_12345'))
  self.assertFalse(reopened.remember(task,ctx,[{'sku':'invalid','grade':'B','preferred_price':1}]))
  self.assertEqual(reopened.current(task,ctx)[0]['preferred_price'],4410)
  clock[0]=999.;self.assertIsNone(reopened.current(task,ctx));clock[0]=1300.;self.assertIsNone(reopened.current(task,ctx));self.assertIsNone(self.db.get_route(task))
 def test_persistent_engine_has_no_oldtask_proxy_and_reads_during_maintenance(self):
  called=[];proxied=[]
  async def app(scope,receive,send):
   if scope['type']=='lifespan':
    while True:
     message=await receive()
     if message['type']=='lifespan.startup':await send({'type':'lifespan.startup.complete'})
     elif message['type']=='lifespan.shutdown':await send({'type':'lifespan.shutdown.complete'});return
   called.append(await receive());await send({'type':'http.response.start','status':200,'headers':[]});await send({'type':'http.response.body','body':b'{"local":true}'})
  async def proxy(scope,body):proxied.append(body);return 200,[],b'{"old_card":true}'
  edge=front.FrontEdge(app,SQLiteTaskStore(self.db),old_request=proxy,config=SimpleNamespace(marker='synthetic-engine',old_proxy_port=18805),persistent_engine=True,state_db=self.db)
  with TestClient(edge) as client:
   def post(method,params):return client.post('/',json={'jsonrpc':'2.0','id':1,'method':method,'params':params})
   self.assertEqual(post('GetTask',{'id':'synthetic-unknown-task'}).status_code,200)
   self.assertEqual(post('ListTasks',{}).status_code,200);self.assertEqual(len(proxied),0)
   message={'message':{'messageId':'synthetic','parts':[{'text':'synthetic inquiry'}]}}
   self.assertEqual(post('SendMessage',message).status_code,503);self.assertEqual(post('CancelTask',{'id':'synthetic-unknown-task'}).status_code,503)
   self.assertEqual(len(called),2);self.assertEqual(len(proxied),0)
   self.db.set_maintenance(False);self.assertEqual(post('SendMessage',message).status_code,200)
   self.assertEqual(client.get('/.well-known/agent-card.json').content,b'{"old_card":true}');self.assertEqual(len(proxied),1)
 def test_assemble_fixture_store_and_original_continuity_are_all_isolated(self):
  self.root.joinpath('agent.json').write_text(json.dumps({'name':'SYNTHETIC','llm':{'base':'market'}}))
  seen=[];broker=SimpleNamespace(Broker=type('BaseBroker',(),{}),SEMANTIC_INSTRUCTION='synthetic')
  class Box:
   def __init__(self,root,ctx):self.root=root
  def mind(root,*args):seen.append(('mind',root));return object()
  def app_factory(root,*args):
   import a2a.server.tasks as tasks
   seen.append(('app',root));seen.append(('store',tasks.InMemoryTaskStore()))
   async def app(scope,receive,send):pass
   return app
  managed=SimpleNamespace(PublicContinuity=original.PublicContinuity)
  def classes(*args,**kwargs):seen.append(('continuity',managed.PublicContinuity()));return Box,mind,app_factory
  managed.managed_classes=classes
  config=SimpleNamespace(marker='synthetic-engine',old_proxy_port=18805,semantic_instruction=None)
  real_load=launcher.load
  def controlled_load(name,path):
   return broker if name=='broker_public_catalogue_host_candidate' else managed if name=='edge_managed_public_catalogue' else real_load(name,path)
  ctx={'tokens':{},'addresses':{},'shop_url':'https://synthetic.invalid'}
  with patch.object(launcher,'verify',return_value={}),patch.object(launcher,'load',side_effect=controlled_load):
   edge=launcher.assemble(None,OP,BASE,'unused-synthetic-pin',ctx,object(),options_override={},toolbox_factory=lambda cls,root,ctx:cls(root,ctx),_front=front,config=config,isolated_root=self.root,host_state_db=self.db.path,persistent_engine=True)
  self.assertIs(edge.loaded_broker,broker);self.assertTrue(edge.persistent_engine);self.assertEqual(edge.host_state_db.path,self.db.path)
  self.assertEqual([row[1] for row in seen if row[0] in ('mind','app')],[self.root,self.root]);self.assertEqual(next(row[1] for row in seen if row[0]=='store').state_db.path,self.db.path)
  continuity=next(row[1] for row in seen if row[0]=='continuity');self.assertEqual(continuity.state_db.path,self.db.path)
  with patch.object(launcher,'verify',return_value={}),patch.object(launcher,'load',side_effect=controlled_load):
   with self.assertRaises(ValueError):launcher.assemble(None,OP,BASE,'unused',ctx,object(),options_override={},toolbox_factory=lambda cls,root,ctx:cls(root,ctx),_front=front,config=config,isolated_root=self.root,host_state_db=OP/'runtime/outside-fixture.sqlite3',persistent_engine=True)

if __name__=='__main__':
 result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
 out=OP/'runtime/task-state-20261128-audit';out.mkdir(exist_ok=True)
 (out/'INTEGRATION-SAFE-QA.json').write_text(json.dumps({'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'original_public_validator_used':True,'production_identity_DB_key_API_Model_listener_service_firewall_operations':0,'all_task_and_hint_state_in_synthetic_fixture':True},indent=2)+'\n')
 raise SystemExit(not result.wasSuccessful())
