"""Five synthetic protocol/guard mocks. No original Model, key, DB, listener or iptables calls."""
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest.mock import patch,call
import json,sys,unittest,asyncio,os
sys.path.insert(0,str(Path(__file__).parent))
import admission_gate as a,front_edge_app as f,transition_guard as g
from starlette.testclient import TestClient
class Store:
 def __init__(self):self.tasks={}
 async def get(self,key,ctx):return self.tasks.get(key)
class QA(unittest.TestCase):
 def setUp(self):
  self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.root.chmod(0o700);self.gate=a.AdmissionGate(self.root/'admission.json',owner=os.getuid());self.gate.initialize_closed();self.store=Store();self.calls=[];self.old=[]
  async def app(scope,receive,send):
   m=await receive();self.calls.append(m['body']);self.store.tasks['own-new']=object()
   await send({'type':'http.response.start','status':200,'headers':[(b'content-type',b'application/json')]});await send({'type':'http.response.body','body':b'{"result":{"id":"own-new"}}'})
  async def old(scope,body):self.old.append((body,scope.get('query_string')));return 200,[(b'content-type',b'application/json')],b'{"old":true}'
  self.edge=f.FrontEdge(app,self.store,old_request=old,admission=self.gate);self.client=TestClient(self.edge);self.addCleanup(self.client.close)
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
   self.assertEqual(replace.call_args_list,[call('18808','18809'),call('18809','18808')]);self.assertFalse(self.gate.read()['open'])
  with patch.object(g,'identities',return_value={'description':'post-idle-current'}),patch.object(g,'idle10',return_value=20),patch.object(g,'replace') as replace,patch.object(g,'public_matches',return_value={'strict':True}):
   g.guarded_apply('https://synthetic.invalid',preserve,self.gate);replace.assert_called_once_with('18808','18809');self.assertTrue(self.gate.read()['open']);self.assertEqual(self.gate.read()['admissions'],0)
 def test_manual_rollback_refuses_any_admission_and_zero_allows_exact_reverse(self):
  self.gate.open_if_pristine();self.gate.admit()
  with patch.object(g,'replace') as replace:
   with self.assertRaises(ValueError):g.guarded_rollback('https://synthetic.invalid',lambda:None,self.gate)
   replace.assert_not_called();self.assertFalse(self.gate.read()['open']);self.assertEqual(self.gate.read()['admissions'],1)
  other=self.root/'zero';other.mkdir(mode=0o700);zero=a.AdmissionGate(other/'admission.json',owner=os.getuid());zero.initialize_closed()
  with patch.object(g,'identities',return_value={}),patch.object(g,'public_matches',return_value={}),patch.object(g,'replace') as replace:
   g.guarded_rollback('https://synthetic.invalid',lambda:None,zero);replace.assert_called_once_with('18809','18808')
 def test_exact_selector_and_all_oldprocesses_plus_new_checked(self):
  line='-P OUTPUT ACCEPT\n-A OUTPUT '+' '.join(g.BASE)+' 18808\n'
  with patch.object(g,'run',return_value=SimpleNamespace(returncode=0,stdout=line)):self.assertEqual(g.chain(),'18808')
  with patch.object(g,'run',return_value=SimpleNamespace(returncode=0,stdout=line.replace('--uid-owner 1000','--uid-owner 0'))):
   with self.assertRaises(ValueError):g.chain()
  commands={6:b'/op/front_edge_runtime_v3/run_front_edge.py\000--port\00018806',7:b'/op/front_semantic_edge_runtime_v2/run_front_edge.py\000--port\00018807',8:b'/op/front_semantic3_edge_runtime_v1/run_front_edge.py\000--port\00018808',9:b'cloudflared\000--url\000http://127.0.0.1:18805',10:b'/op/front_compound_edge_runtime_v1/run_front_edge.py\000--port\00018809'}
  pids=lambda unit='ourolabs-market-r4.service':1 if unit=='ourolabs-market-r4.service' else 2 if unit=='ourolabs-market-r4-worker.service' else 10
  with patch.object(g,'service_pid',side_effect=pids),patch.object(g,'pid_alive',return_value=True),patch.object(Path,'read_bytes',lambda p:commands[int(p.parent.name)]):g.preserve_processes(1,2,6,7,8,9,10)
  with patch.object(g,'service_pid',side_effect=pids),patch.object(g,'pid_alive',side_effect=lambda pid:pid!=2):
   with self.assertRaises(ValueError):g.preserve_processes(1,2,6,7,8,9,10)
if __name__=='__main__':
 r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(QA));Path(__file__).with_name('SAFE-QA.json').write_text(json.dumps({'tests':r.testsRun,'failures':len(r.failures),'errors':len(r.errors),'scope':'synthetic ASGI protocol and mocked guard, not original SDK business integration','actual_Model_HTTP_wallet_DB_service_nat_calls':0,'temporary_state_only':True,'new_task_admission_counter_is_conservative_not_actual_task_count':True},indent=2));raise SystemExit(not r.wasSuccessful())
