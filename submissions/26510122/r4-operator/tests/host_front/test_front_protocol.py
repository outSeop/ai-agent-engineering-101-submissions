"""Five synthetic protocol/guard mocks. No original Model, key, DB, listener or iptables calls."""
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest.mock import patch,call
import json,sys,unittest,asyncio,os
OP=Path('/home/seop/.local/share/ourolabs-r4-checkout/submissions/26510122/r4-operator');SRC=OP/'src/r4_operator_host/front';sys.path.insert(0,str(SRC))
import config as c
from dataclasses import replace
import hashlib,copy
CONFIG_DATA=json.loads(Path(__file__).with_name('front-config.fixture.json').read_text());CONFIG=c.parse(CONFIG_DATA)
import admission_gate as a,front_edge_app as f,transition_guard as g,run_front_edge as h
g.configure(CONFIG,"a"*64)
from starlette.testclient import TestClient
class Store:
 def __init__(self):self.tasks={}
 async def get(self,key,ctx):return self.tasks.get(key)
class QA(unittest.TestCase):
 def setUp(self):
  self.temp=TemporaryDirectory(prefix="front-protocol-test-",dir=OP/"runtime");self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.root.chmod(0o700);self.gate=a.AdmissionGate(self.root/'admission.json',owner=os.getuid());self.gate.initialize_closed();self.store=Store();self.calls=[];self.old=[]
  async def app(scope,receive,send):
   m=await receive();self.calls.append(m['body']);self.store.tasks['own-new']=object()
   await send({'type':'http.response.start','status':200,'headers':[(b'content-type',b'application/json')]});await send({'type':'http.response.body','body':b'{"result":{"id":"own-new"}}'})
  async def old(scope,body):self.old.append((body,scope.get('query_string')));return 200,[(b'content-type',b'application/json')],b'{"old":true}'
  self.edge=f.FrontEdge(app,self.store,old_request=old,admission=self.gate,config=CONFIG);self.client=TestClient(self.edge);self.addCleanup(self.client.close)
 def message(self,task=None):
  m={'messageId':'synthetic-message','role':'ROLE_USER','parts':[{'text':'synthetic inquiry'}]}
  if task:m['taskId']=task
  return json.dumps({'jsonrpc':'2.0','id':1,'method':'SendMessage','params':{'message':m}},separators=(',',':')).encode()
 def test_closed_gate_preserves_card_oldproxy_and_known_own_followups(self):
  self.assertEqual(self.client.get('/.well-known/agent-card.json?a=%2F').content,b'{"old":true}')
  raw=self.message('old-sdk-task');self.assertEqual(self.client.post('/?x=%2F',content=raw).content,b'{"old":true}');self.assertEqual(self.old[-1],(raw,b'x=%2F'))
  self.store.tasks['existing-own']=object();self.assertEqual(self.client.post('/',content=self.message('existing-own')).status_code,200)
  before=len(self.calls);self.assertEqual(self.client.post('/',content=self.message()).status_code,503);self.assertEqual(len(self.calls),before);self.assertEqual(self.gate.read()['admissions'],0)
 def test_open_records_before_sdk_and_count_never_resets(self):
  self.gate.open_if_pristine();self.assertEqual(self.client.post('/',content=self.message()).status_code,200);self.assertEqual(self.gate.read()['admissions'],1)
  self.gate.close();self.assertEqual(self.client.post('/',content=self.message('own-new')).status_code,200);self.assertEqual(self.client.post('/',content=self.message()).status_code,503);self.assertEqual(self.gate.read()['admissions'],1)
  self.gate.path.unlink()
  with self.assertRaises(ValueError):self.gate.initialize_closed()
 def test_apply_postcheck_failure_rolls_back_only_pristine_then_success_opens(self):
  preserve=lambda:None
  with patch.object(g,'identities',return_value={'description':'current'}),patch.object(g,'idle10',return_value=20),patch.object(g,'replace') as replace,patch.object(g,'public_matches',side_effect=ValueError('synthetic postcheck failed')):
   with self.assertRaises(ValueError):g.guarded_apply('https://synthetic.invalid',preserve,self.gate)
   self.assertEqual(replace.call_args_list,[call('18809','18810'),call('18810','18809')]);self.assertFalse(self.gate.read()['open'])
  with patch.object(g,'identities',return_value={'description':'post-idle-current'}),patch.object(g,'idle10',return_value=20),patch.object(g,'replace') as replace,patch.object(g,'public_matches',return_value={'strict':True}):
   g.guarded_apply('https://synthetic.invalid',preserve,self.gate);replace.assert_called_once_with('18809','18810');self.assertTrue(self.gate.read()['open']);self.assertEqual(self.gate.read()['admissions'],0)
 def test_manual_rollback_refuses_any_admission_and_zero_allows_exact_reverse(self):
  self.gate.open_if_pristine();self.gate.admit()
  with patch.object(g,'replace') as replace:
   with self.assertRaises(ValueError):g.guarded_rollback('https://synthetic.invalid',lambda:None,self.gate)
   replace.assert_not_called();self.assertFalse(self.gate.read()['open']);self.assertEqual(self.gate.read()['admissions'],1)
  other=self.root/'zero';other.mkdir(mode=0o700);zero=a.AdmissionGate(other/'admission.json',owner=os.getuid());zero.initialize_closed()
  with patch.object(g,'identities',return_value={}),patch.object(g,'public_matches',return_value={}),patch.object(g,'replace') as replace:
   g.guarded_rollback('https://synthetic.invalid',lambda:None,zero);replace.assert_called_once_with('18810','18809')
 def test_exact_selector_and_all_oldprocesses_plus_new_checked(self):
  g.verify_preserved_fronts() # Read-only all preserved exact manifests, no API or gate access.
  for key,value in [("state_dir",CONFIG_DATA["preserved_edges"][-1]["state_dir"]),("state_dir","runtime//front-compound-edge"),("semantic_instruction","x"*1501),("runtime_path","/tmp/outside")]:
   bad=copy.deepcopy(CONFIG_DATA);bad[key]=value
   with self.assertRaises(ValueError):c.parse(bad)
  configfile=self.root/"RUNTIME-BINDING.json";configfile.write_text(json.dumps(CONFIG_DATA));meta={"files":{"RUNTIME-BINDING.json":hashlib.sha256(configfile.read_bytes()).hexdigest()}};c.load_pinned(self.root,meta);configfile.write_text(configfile.read_text()+" ")
  with self.assertRaises(ValueError):c.load_pinned(self.root,meta)
  line='-P OUTPUT ACCEPT\n-A OUTPUT '+' '.join(g.BASE)+' 18809\n'
  with patch.object(g,'run',return_value=SimpleNamespace(returncode=0,stdout=line)):self.assertEqual(g.chain(),'18809')
  with patch.object(g,'run',return_value=SimpleNamespace(returncode=0,stdout=line.replace('--uid-owner 1000','--uid-owner 0'))):
   with self.assertRaises(ValueError):g.chain()
  fake_edges=tuple(replace(edge,pid_hint=pid) for edge,pid in zip(CONFIG.edges,[6,7,8,11]));fake=replace(CONFIG,main=c.Role(CONFIG.main.service,1),worker=c.Role(CONFIG.worker.service,2),cf_pid_hint=9,edges=fake_edges)
  g.configure(fake,'a'*64)
  commands={edge.pid_hint:str(edge.launcher).encode()+b'\0--port\0'+str(edge.port).encode() for edge in fake.edges};commands[9]=b'cloudflared\0--url\0http://127.0.0.1:18805';commands[10]=str(SRC/'run_front_edge.py').encode()+b'\0--edge-manifest-sha\0'+b'a'*64
  values={fake.main.service:1,fake.worker.service:2,fake.service:10,**{edge.service:edge.pid_hint for edge in fake.edges}}
  with patch.object(g,'service_pid',side_effect=lambda unit:values[unit]),patch.object(g,'pid_alive',return_value=True),patch.object(Path,'read_bytes',lambda path:commands[int(path.parent.name)]):g.preserve_processes(10)
  with patch.object(g,'service_pid',side_effect=lambda unit:values[unit]),patch.object(g,'pid_alive',side_effect=lambda pid:pid!=2):
   with self.assertRaises(ValueError):g.preserve_processes(10)
  g.configure(CONFIG,'a'*64)
  # Same focused group also verifies the narrow test-only root hook; no real runtime code executes.
  self.root.joinpath('agent.json').write_text(json.dumps({'llm':{'base':'market'}}));seen=[]
  class Box:
   def __init__(self,root,ctx):self.root=root
  class BaseBroker:pass
  broker=SimpleNamespace(Broker=BaseBroker,SEMANTIC_INSTRUCTION='base fixture')
  def mind(root,*args):seen.append(('mind',root));return object()
  managed=SimpleNamespace(managed_classes=lambda *args,**kwargs:(Box,mind,object()))
  def capture(factory,root,*args):seen.append(('app',root));return object(),object()
  front=SimpleNamespace(OneDecisionModel=lambda model:model,capture_sdk_app=capture,FrontEdge=lambda *args,**kwargs:SimpleNamespace())
  ctx={'tokens':{},'addresses':{},'shop_url':'https://synthetic.invalid'}
  promptcfg=replace(CONFIG,semantic_instruction='bounded fixture HOST instruction')
  with patch.object(h,'verify',return_value={}),patch.object(h,'load',side_effect=[broker,managed]):
   h.assemble(None,OP,CONFIG.runtime_path,CONFIG.runtime_manifest_sha256,ctx,object(),options_override={},toolbox_factory=lambda cls,root,ctx:cls(root,ctx),_front=front,config=promptcfg,isolated_root=self.root)
  self.assertEqual(seen,[('mind',self.root),('app',self.root)]);self.assertEqual(broker.SEMANTIC_INSTRUCTION,promptcfg.semantic_instruction)
  with patch.object(h,'verify',return_value={}):
   with self.assertRaises(ValueError):h.assemble(None,OP,CONFIG.runtime_path,CONFIG.runtime_manifest_sha256,{**ctx,'tokens':{'shop':'SYNTHETIC_NO_REAL_AUTH'}},object(),options_override={},toolbox_factory=lambda *args:None,_front=front,config=CONFIG,isolated_root=self.root)
if __name__=='__main__':
 r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(QA));(OP/'runtime/compound-inquiry-20261128-audit/common-front-QA.json').write_text(json.dumps({'tests':r.testsRun,'failures':len(r.failures),'errors':len(r.errors),'scope':'synthetic ASGI protocol and mocked guard, not original SDK business integration','actual_Model_HTTP_wallet_DB_service_nat_calls':0,'temporary_state_only':True,'new_task_admission_counter_is_conservative_not_actual_task_count':True},indent=2));raise SystemExit(not r.wasSuccessful())
