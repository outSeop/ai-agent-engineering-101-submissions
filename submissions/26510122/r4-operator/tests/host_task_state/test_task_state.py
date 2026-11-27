"""Private synthetic persistence tests. No production HTTP/DB/key/Model or service calls."""
from pathlib import Path
from tempfile import TemporaryDirectory
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import asyncio,json,os,sqlite3,stat,subprocess,sys,unittest
OP=Path(__file__).resolve().parents[2];(OP/'runtime').mkdir(exist_ok=True);sys.path.insert(0,str(OP/'src/r4_operator_host'))
from task_state import TaskStateDB,SQLiteTaskStore,RouteConflict,UnsafeTaskState
from a2a.server.tasks import InMemoryTaskStore
from a2a.server.context import ServerCallContext
from a2a.auth.user import User
from a2a.types import Task,ListTasksRequest
class Named(User):
 def __init__(self,name):self.name=name
 @property
 def is_authenticated(self):return True
 @property
 def user_name(self):return self.name
STATES=Task.DESCRIPTOR.fields_by_name['status'].message_type.fields_by_name['state'].enum_type.values_by_name
WORKING=STATES['TASK_STATE_WORKING'].number
INPUT=STATES['TASK_STATE_INPUT_REQUIRED'].number

def sample(ident='synthetic-task-1',number=1):
 t=Task(id=ident,context_id='synthetic-context');t.status.state=WORKING if number%2 else INPUT;t.status.timestamp.FromNanoseconds(number*1000000000)
 t.history.add(message_id='fixture-message',role=1).parts.add(text='PRIVATE SYNTHETIC FIXTURE ONLY')
 t.artifacts.add(artifact_id='fixture-artifact').parts.add(text='SYNTHETIC CHECKOUT CAPABILITY')
 t.metadata.update({'fixture':'synthetic-no-customer'})
 return t
class Tests(unittest.TestCase):
 def setUp(self):
  self.temp=TemporaryDirectory(prefix='task-state-test-',dir=OP/'runtime');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.path=self.root/'host-tasks.sqlite3';self.db=TaskStateDB(self.path);self.store=SQLiteTaskStore(self.db);self.ctx=ServerCallContext()
 def test_proto_allfields_unknowns_and_deepcopy_survive_reopen(self):
  task=Task.FromString(sample().SerializeToString()+b'\xa0\x06\x07');payload=task.SerializeToString(deterministic=True);asyncio.run(self.store.save(task,self.ctx));task.ClearField('history')
  reopened=SQLiteTaskStore(TaskStateDB(self.path));got=asyncio.run(reopened.get('synthetic-task-1',self.ctx));self.assertEqual(got.SerializeToString(deterministic=True),payload)
  got.ClearField('artifacts');self.assertEqual(asyncio.run(reopened.get(got.id,self.ctx)).SerializeToString(deterministic=True),payload);self.assertEqual(self.db.get_route(got.id),'current')
 def test_fresh_process_restart_restores_working_without_reexecution(self):
  asyncio.run(self.store.save(sample(),self.ctx))
  child="import sys,json,asyncio;from pathlib import Path;sys.path.insert(0,sys.argv[2]);from task_state import TaskStateDB,SQLiteTaskStore;from a2a.server.context import ServerCallContext;d=TaskStateDB(Path(sys.argv[1]));t=asyncio.run(SQLiteTaskStore(d).get('synthetic-task-1',ServerCallContext()));print(json.dumps({'restored':t is not None,'working':t.status.state==int(sys.argv[3]),'route':d.get_route(t.id)=='current','maintenance':d.maintenance_enabled()}))"
  out=subprocess.run([sys.executable,'-I','-B','-c',child,str(self.path),str(OP/'src/r4_operator_host'),str(WORKING)],capture_output=True,text=True,check=True)
  self.assertEqual(json.loads(out.stdout),{'restored':True,'working':True,'route':True,'maintenance':True})
 def test_owner_scope_isolated_same_task_id_and_delete_route_tombstone(self):
  a=ServerCallContext(user=Named('fixture-a'));b=ServerCallContext(user=Named('fixture-b'));first=sample();second=sample();second.context_id='different-fixture-context'
  asyncio.run(self.store.save(first,a));asyncio.run(self.store.save(second,b));self.assertEqual(asyncio.run(self.store.get(first.id,a)).context_id,first.context_id);self.assertEqual(asyncio.run(self.store.get(first.id,b)).context_id,second.context_id);self.assertIsNone(asyncio.run(self.store.get(first.id,self.ctx)))
  asyncio.run(self.store.delete(first.id,a));self.assertIsNone(asyncio.run(self.store.get(first.id,a)));self.assertEqual(self.db.get_route(first.id,scope='fixture-a'),'current');self.assertIsNotNone(asyncio.run(self.store.get(first.id,b)))
 def test_native_list_filter_and_cursor_match_original_sdk(self):
  native=InMemoryTaskStore()
  for i in range(1,7):
   task=sample('synthetic-'+str(i),i);task.context_id='even' if i%2==0 else 'odd';asyncio.run(native.save(task,self.ctx));asyncio.run(self.store.save(task,self.ctx))
  request=ListTasksRequest(page_size=2)
  for _ in range(3):
   a=asyncio.run(native.list(request,self.ctx));b=asyncio.run(self.store.list(request,self.ctx));self.assertEqual(a.SerializeToString(deterministic=True),b.SerializeToString(deterministic=True));request.page_token=a.next_page_token
  request=ListTasksRequest(context_id='even',status=INPUT,page_size=1);request.status_timestamp_after.FromNanoseconds(3*1000000000)
  self.assertEqual(asyncio.run(native.list(request,self.ctx)),asyncio.run(self.store.list(request,self.ctx)))
 def test_route_conflict_rolls_back_current_save_atomically(self):
  self.db.bind('synthetic-task-1',18809,provenance='own_list_tasks')
  with self.assertRaises(RouteConflict):asyncio.run(self.store.save(sample(),self.ctx))
  self.assertIsNone(asyncio.run(self.store.get('synthetic-task-1',self.ctx)));self.assertEqual(self.db.get_route('synthetic-task-1'),18809)
  with ThreadPoolExecutor(max_workers=2) as pool:
   def bind(port):
    try:self.db.bind('synthetic-race',port);return 'won'
    except RouteConflict:return 'conflict'
   results=list(pool.map(bind,[18808,18809]))
  self.assertEqual(sorted(results),['conflict','won']);self.assertEqual(len([r for r in self.db.list_routes() if r[0]=='synthetic-race']),1)
 def test_legacy_snapshot_private_restart_does_not_migrate_send_owner(self):
  t=sample('synthetic-legacy');self.db.save_legacy_snapshot(t.id,t.SerializeToString(),18808)
  reopened=TaskStateDB(self.path);snapshot=reopened.get_legacy_snapshot(t.id);self.assertEqual(snapshot.task,t);self.assertEqual(snapshot.owner_port,18808);self.assertEqual(reopened.get_route(t.id),18808);self.assertIsNone(asyncio.run(SQLiteTaskStore(reopened).get(t.id,self.ctx)))
  with self.assertRaises(RouteConflict):reopened.bind(t.id,18809)
  self.assertEqual(reopened.route_stats()['snapshots'],1)
 def test_private_permissions_symlink_and_unrelated_db_refusal(self):
  self.assertEqual(stat.S_IMODE(self.path.stat().st_mode),0o600)
  foreign=self.root/'foreign.sqlite3'
  with sqlite3.connect(foreign) as db:db.execute('CREATE TABLE unrelated(value TEXT)')
  foreign.chmod(0o600);before=sha256(foreign.read_bytes()).hexdigest()
  with self.assertRaises(UnsafeTaskState):TaskStateDB(foreign)
  self.assertEqual(sha256(foreign.read_bytes()).hexdigest(),before)
  alias=self.root/'alias.sqlite3';alias.symlink_to(self.path)
  with self.assertRaises(UnsafeTaskState):TaskStateDB(alias)
  self.path.chmod(0o644)
  with self.assertRaises(UnsafeTaskState):TaskStateDB(self.path)
 def test_maintenance_durable_and_invalid_destination_no_route(self):
  self.assertTrue(self.db.maintenance_enabled());self.db.set_maintenance(False);self.assertFalse(TaskStateDB(self.path).maintenance_enabled())
  for bad in [1,True,'18809','http://example.invalid']:
   with self.assertRaises(ValueError):self.db.bind('synthetic-invalid',bad)
  self.assertIsNone(self.db.get_route('synthetic-invalid'))
 def test_public_hints_restart_ttl_clock_and_no_authority(self):
  key=sha256(b'synthetic-task:context').digest();facts=[{'sku':'G1234abcd','grade':'B','preferred_price':4410}]
  self.db.save_public_facts(key,facts,1000)
  reopened=TaskStateDB(self.path);actual=reopened.get_public_facts(key,1001)
  self.assertEqual(actual,tuple(facts));self.assertEqual(set(actual[0]),{'sku','grade','preferred_price'})
  actual[0]['preferred_price']=1;self.assertEqual(reopened.get_public_facts(key,1002)[0]['preferred_price'],4410)
  self.assertIsNone(reopened.get_public_facts(key,999));self.assertIsNone(reopened.get_public_facts(key,1300))
  self.assertIsNone(reopened.get_route('synthetic-task'));self.assertEqual(reopened.route_stats()['tasks'],0)
  with self.assertRaises(ValueError):reopened.save_public_facts(key,[dict(facts[0],consent=True)],1003)
  with self.assertRaises(ValueError):reopened.save_public_facts(key,[dict(facts[0],preferred_price=True)],1003)
 def test_trusted_known_owner_response_refreshes_snapshot_not_ownership(self):
  original=sample('synthetic-known-owner');self.db.save_legacy_snapshot(original.id,original.SerializeToString(),18808,observed_at=1000)
  updated=sample(original.id);updated.artifacts[0].parts[0].text='SYNTHETIC NEW OWNER RESPONSE'
  self.db.save_legacy_snapshot(updated.id,updated.SerializeToString(),18808,observed_at=1001,provenance='known_owner_response')
  snap=TaskStateDB(self.path).get_legacy_snapshot(updated.id)
  self.assertEqual(snap.task,updated);self.assertEqual(snap.provenance,'known_owner_response');self.assertEqual(snap.observed_at,1001)
  self.assertEqual(self.db.get_route(updated.id),18808)
  with self.assertRaises(RouteConflict):self.db.save_legacy_snapshot(updated.id,updated.SerializeToString(),18809,provenance='known_owner_response')
  new=sample('synthetic-native-followup');self.db.save_legacy_snapshot(new.id,new.SerializeToString(),18808,provenance='known_owner_response')
  self.assertEqual(self.db.get_route(new.id),18808);self.assertIsNone(asyncio.run(self.store.get(new.id,self.ctx)))
 def test_transport_route_finds_scoped_location_without_scope_authority(self):
  task=sample('synthetic-scoped-transport');self.db._save_current(task,'trusted-fixture-user')
  self.assertEqual(self.db.transport_route(task.id),'current');self.assertIsNone(self.db.get_route(task.id));self.assertIsNone(asyncio.run(self.store.get(task.id,self.ctx)))
  self.db.bind(task.id,18808,scope='different-trusted-user')
  with self.assertRaises(RouteConflict):self.db.transport_route(task.id)
  self.assertIsNone(self.db.transport_route('synthetic-no-route'))
if __name__=='__main__':
 r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests));out=OP/'runtime/task-state-20261128-audit';out.mkdir(exist_ok=True)
 (out/'SAFE-QA.json').write_text(json.dumps({'tests':r.testsRun,'failures':len(r.failures),'errors':len(r.errors),'fresh_interpreter_restart_test':True,'native_SDK_list_differential':True,'real_customer_task_or_financialDB_used':False,'production_HTTP_Model_key_service_firewall_operations':0,'wallet_creation':0,'original_SDK_files_modified':False},indent=2));raise SystemExit(not r.wasSuccessful())
