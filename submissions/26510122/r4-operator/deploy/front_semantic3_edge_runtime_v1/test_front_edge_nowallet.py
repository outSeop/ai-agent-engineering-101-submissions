from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import json,sys,unittest,time,asyncio,shutil
OP=Path('/home/seop/.local/share/ourolabs-r4-checkout/submissions/26510122/r4-operator');sys.path[:0]=[str(Path(__file__).parent),str(OP/'kit')]
import agent_kit as official
import run_front_edge as host
from front_edge_app import referenced_task,OneDecisionModel,_REQUEST_BUDGET,EdgeModelBudgetExceeded
from starlette.testclient import TestClient
B=OP/'deploy/public_catalogue_runtime_v4f';PIN='7f542904fc84e44d92b2558e72146aa7863fdd8d9208ce45c98e5e5b397b24d6'
class NoWallet:
 def grant(self,*a):raise AssertionError('wallet must not execute')
class FakeModel:
 def __init__(self):self.calls=0;self.timeouts=[]
 def complete(self,messages,**kwargs):self.calls+=1;self.timeouts.append(kwargs.get('timeout'));return json.dumps({'action':'quote_and_send','args':{'sku':'G00000001','proposed_price':1000}})
class Tests(unittest.TestCase):
 def setUp(self):
  self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.sdkroot=Path(self.temp.name)/'sdk-root';(self.sdkroot/'tools').mkdir(parents=True)
  for name in ('a2a_info','shop_info'):shutil.copytree(OP.parent/'round-4/tools'/name,self.sdkroot/'tools'/name)
  self.old=[];self.actions=[];self.model=FakeModel();ctx={'name':'outseop-r4','market':'https://market.ourolabs.ai','shop_url':'https://synthetic-local-only.invalid','tokens':{},'addresses':{},'signer':NoWallet()}
  async def old(scope,body):self.old.append((scope['method'],scope['path'],body));return 200,[(b'content-type',b'application/json')],b'{"old_backend":true}'
  actions=self.actions
  def factory(base,root,ctx):
   class FakeFinancial(base):
    def decision_tool(self,details):
     actions.append(details)
     if details['action']=='context':return {'outcome':'context','inventory':[{'sku':'G00000001','grade':'A','name':'合成','preferred_price':1000,'reference_price':1000,'min_base':1000,'stock_status':'available','available':True,'wait_eligible':False}],'verified_account':False,'redeemable_mileage':0,'preferences':[],'wait':None,'prior_offer':None}
     return {'outcome':'canary_only','reply':'합성 금융 선택만 기록했습니다.','state':'input_required'}
   return FakeFinancial(self.sdkroot,ctx)
  # Original app's task-store instance is captured, not replaced by a custom store.
  self.app=host.assemble(official,OP,B,PIN,ctx,self.model,trace=Path(self.temp.name)/'trace.jsonl',old_request=old,options_override={},toolbox_factory=factory,_front=__import__('front_edge_app'))
  self.client=TestClient(self.app,base_url='https://synthetic-local-only.invalid');self.addCleanup(self.client.close)
 def tearDown(self):
  def refs(path,key):
   result=set()
   if path.exists():
    for line in path.read_text().splitlines():
     try:x=json.loads(line)
     except:continue
     if x.get(key):result.add(x[key])
   return result
  prod=OP.parent/'round-4/.kit'
  self.assertFalse(refs(self.sdkroot/'.kit/decision-trace-private.jsonl','request_ref') & refs(prod/'decision-trace-private.jsonl','request_ref'))
  self.assertFalse(refs(self.sdkroot/'.kit/transport-metrics.jsonl','internal_ref') & refs(prod/'transport-metrics.jsonl','internal_ref'))
 def message(self,task=None,text='G00000001 서명된 결제권을 보내 주세요.'):
  m={'messageId':'synthetic-msg-'+str(time.time_ns()),'role':'ROLE_USER','parts':[{'text':text}],'metadata':{'from':'unverified-fixture'}}
  if task:m['taskId']=task
  return {'jsonrpc':'2.0','id':1,'method':'SendMessage','params':{'message':m}}
 def test_new_then_known_task_original_sdk(self):
  r=self.client.post('/',headers={'A2A-Version':'1.0'},json=self.message());self.assertEqual(r.status_code,200);x=r.json()['result'];task=x.get('task',x);self.assertIn('INPUT_REQUIRED',task['status']['state']);first=task['id']
  r=self.client.post('/',headers={'A2A-Version':'1.0'},json=self.message(first));self.assertNotIn('error',r.json());self.assertEqual(self.old,[]);self.assertEqual(self.model.calls,2);self.assertTrue(all(x<=30 for x in self.model.timeouts));self.assertEqual(self.app.background_loops_started,0)
 def test_unknown_old_task_preserves_original_request_bytes(self):
  raw=json.dumps(self.message('old-sdk-task-0123456789'),ensure_ascii=False,separators=(',',':')).encode();r=self.client.post('/',headers={'A2A-Version':'1.0','content-type':'application/json'},content=raw);self.assertEqual(r.content,b'{"old_backend":true}');self.assertEqual(self.old[0][2],raw);self.assertEqual(self.model.calls,0);self.assertEqual(self.actions,[])
 def test_card_GET_old_proxy_and_marker(self):
  r=self.client.get('/.well-known/agent-card.json');self.assertEqual(r.content,b'{"old_backend":true}');self.assertEqual(r.headers['x-r4-edge'],'r4-semantic3-front-v1');self.assertEqual(self.model.calls,0)
 def test_unknown_GetTask_old_proxy(self):
  r=self.client.post('/',json={'jsonrpc':'2.0','id':1,'method':'GetTask','params':{'id':'old-sdk-task-0123456789'}});self.assertEqual(r.content,b'{"old_backend":true}');self.assertEqual(self.model.calls,0)
 def test_large_body_rejected_before_any_executor(self):
  r=self.client.post('/',content=b'x'*65537);self.assertEqual(r.status_code,413);self.assertEqual(self.old,[]);self.assertEqual(self.model.calls,0)
 def test_log_failure_does_not_break_response(self):
  self.app.trace=Path(self.temp.name)/'missing'/'trace';r=self.client.post('/',headers={'A2A-Version':'1.0'},json=self.message());self.assertEqual(r.status_code,200);self.assertTrue(self.app.trace_unavailable)
 def test_proxy_preserves_query_on_fixed_destination(self):
  from unittest.mock import patch
  observed=[]
  class Headers:
   def multi_items(self):return [('content-type','application/json')]
  class Client:
   def __init__(self,**kwargs):pass
   async def __aenter__(self):return self
   async def __aexit__(self,*args):pass
   async def request(self,method,url,**kwargs):observed.append(str(url));return SimpleNamespace(status_code=200,headers=Headers(),content=b'{}')
  self.app.old_request=None
  with patch('front_edge_app.httpx.AsyncClient',Client):asyncio.run(self.app.proxy({'method':'GET','path':'/.well-known/agent-card.json','headers':[],'query_string':b'a=%2F&b=hello+world'},b''))
  self.assertEqual(observed,['http://127.0.0.1:18807/.well-known/agent-card.json?a=%2F&b=hello+world'])
 def test_original_URL_drift_fails_before_Model_finance(self):
  self.app.before_new=lambda:(_ for _ in ()).throw(ValueError('URL drift fixture'))
  r=self.client.post('/',headers={'A2A-Version':'1.0'},json=self.message());self.assertEqual(r.status_code,503);self.assertEqual(self.model.calls,0);self.assertEqual(self.actions,[])
 def test_original_URL_drift_blocks_old_task_proxy(self):
  self.app.before_new=lambda:(_ for _ in ()).throw(ValueError('URL drift fixture'))
  r=self.client.post('/',headers={'A2A-Version':'1.0'},json=self.message('old-sdk-task-0123456789'));self.assertEqual(r.status_code,503);self.assertEqual(self.model.calls,0);self.assertEqual(self.actions,[]);self.assertEqual(self.old,[])
 def test_one_model_call_per_request_and_no_background(self):
  m=OneDecisionModel(self.model)
  with self.assertRaises(EdgeModelBudgetExceeded):m.complete([])
  token=_REQUEST_BUDGET.set({'calls':0,'deadline':time.monotonic()+25})
  try:
   m.complete([])
   with self.assertRaises(EdgeModelBudgetExceeded):m.complete([])
  finally:_REQUEST_BUDGET.reset(token)
if __name__=='__main__':unittest.main()
