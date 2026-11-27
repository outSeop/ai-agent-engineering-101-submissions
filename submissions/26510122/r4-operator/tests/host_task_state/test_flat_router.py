"""Flat routing integration with real private SQLite and fake loopback peers."""
from pathlib import Path
import asyncio,json,sys,tempfile,unittest
from types import SimpleNamespace
OP=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(OP/'src/r4_operator_host/front'),str(OP/'src/r4_operator_host')]
from task_state import TaskStateDB,SQLiteTaskStore
from flat_router import FlatRouter,Reply
from a2a.types import Task,TaskStatus,TaskState
from a2a.server.context import ServerCallContext
from google.protobuf.json_format import MessageToDict

def task(ident):return Task(id=ident,context_id='fixture-context',status=TaskStatus(state=TaskState.TASK_STATE_INPUT_REQUIRED))
def rpc(method,ident=None):
    params={'id':ident} if method=='GetTask' else {'message':{'messageId':'fixture-msg','role':'ROLE_USER','parts':[{'text':'fixture public request'}],**({'taskId':ident} if ident else {})}}
    return {'jsonrpc':'2.0','id':'fixture','method':method,'params':params}
def scope():return {'type':'http','method':'POST','path':'/','query_string':b'','headers':[(b'a2a-version',b'1.0')]}
class Client:
    def __init__(self,db):self.db=db;self.calls=[];self.down=set();self.inventory={};self.tasks={};self.created=0
    async def request(self,port,request,body,**kwargs):
        obj=json.loads(body);method=obj['method'];self.calls.append((port,method))
        if port in self.down:return Reply(503,[],b'{"error":"unavailable"}')
        if method=='ListTasks':result={'tasks':[MessageToDict(t) for t in self.inventory.get(port,[])]}
        elif method=='SendMessage':
            self.created+=1;t=task('current-created-task');await SQLiteTaskStore(self.db).save(t,ServerCallContext());result={'task':MessageToDict(t)}
        else:
            ident=obj['params']['id'];t=(await SQLiteTaskStore(self.db).get(ident,ServerCallContext())) if port==18812 else self.tasks.get((port,ident))
            if t is None:return Reply(200,[],b'{"jsonrpc":"2.0","id":"fixture","error":{"code":-32001,"message":"Task not found"}}')
            result=MessageToDict(t)
        return Reply(200,[(b'content-type',b'application/json')],json.dumps({'jsonrpc':'2.0','id':obj['id'],'result':result}).encode())

class FlatRoutingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='r4-flat-router-only-');self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'state.sqlite3';self.db=TaskStateDB(self.path);self.client=Client(self.db)
        self.router=FlatRouter(self.db,worker_port=18812,legacy_ports=range(18805,18811),client=self.client)
    async def call(self,obj,router=None):return await (router or self.router).dispatch(scope(),json.dumps(obj).encode(),obj)
    async def test_known_lower_owner_bypasses_dead_middle_and_mapping_survives_restart(self):
        t=task('legacy-lower-task');self.db.save_legacy_snapshot(t.id,t.SerializeToString(),18805);self.client.tasks[18805,t.id]=t;self.client.down.add(18806)
        result=await self.call(rpc('GetTask',t.id));self.assertEqual(result.status,200);self.assertEqual(self.client.calls,[(18805,'GetTask')])
        reopened=TaskStateDB(self.path);client=Client(reopened);client.tasks[18805,t.id]=t;client.down.add(18806)
        other=FlatRouter(reopened,worker_port=18812,legacy_ports=range(18805,18811),client=client)
        result=await self.call(rpc('GetTask',t.id),other);self.assertEqual(result.status,200);self.assertEqual(client.calls,[(18805,'GetTask')])
    async def test_new_task_is_atomically_owned_and_reopened_sdk_store_recovers(self):
        self.db.set_maintenance(False);result=await self.call(rpc('SendMessage'));self.assertEqual(result.status,200)
        reopened=TaskStateDB(self.path);self.assertEqual(reopened.get_route('current-created-task'),'current')
        client=Client(reopened);other=FlatRouter(reopened,worker_port=18812,legacy_ports=range(18805,18811),client=client)
        result=await self.call(rpc('GetTask','current-created-task'),other);self.assertEqual(result.status,200);self.assertEqual(client.calls,[(18812,'GetTask')]);self.assertEqual(client.created,0)
    async def test_unknown_owner_failure_is_not_notfound_and_never_replays_message(self):
        self.db.set_maintenance(False);self.client.down.add(18806)
        with self.assertRaisesRegex(RuntimeError,'unavailable|uncertain'):
            await self.call(rpc('SendMessage','unknown-task'))
        self.assertEqual(self.client.created,0);self.assertIsNone(self.db.get_route('unknown-task'))
    async def test_own_store_listing_proves_owner_once_not_proxy_success(self):
        t=task('discovered-own-task');self.client.inventory[18807]=[t];self.client.tasks[18807,t.id]=t
        result=await self.call(rpc('GetTask',t.id));self.assertEqual(result.status,200);self.assertEqual(self.db.get_route(t.id),18807)
        self.assertEqual(self.client.calls[-1],(18807,'GetTask'));self.assertEqual(sum(m=='ListTasks' for _,m in self.client.calls),6)
        self.client.calls=[];await self.call(rpc('GetTask',t.id));self.assertEqual(self.client.calls,[(18807,'GetTask')])
    async def test_discovered_owner_is_independent_of_failed_intermediate_peer(self):
        t=task('independent-owner-task');self.client.inventory[18805]=[t];self.client.tasks[18805,t.id]=t
        self.client.down.add(18806)
        result=await self.call(rpc('GetTask',t.id));self.assertEqual(result.status,200)
        self.assertEqual(self.db.get_route(t.id),18805);self.assertEqual(self.client.calls[-1],(18805,'GetTask'))
    async def test_trace_failure_does_not_lose_a_completed_task_response(self):
        t=task('legacy-log-outage');self.db.save_legacy_snapshot(t.id,t.SerializeToString(),18805);self.client.tasks[18805,t.id]=t
        self.router.trace=Path(self.tmp.name) # directory is deliberately not a log file
        obj=rpc('GetTask',t.id);messages=[]
        async def receive():return {'type':'http.request','body':json.dumps(obj).encode(),'more_body':False}
        async def send(message):messages.append(message)
        await self.router(scope(),receive,send)
        self.assertEqual(messages[0]['status'],200);self.assertTrue(self.router.trace_unavailable)
    async def test_unknown_method_is_not_copied_into_metadata_trace(self):
        path=Path(self.tmp.name)/'trace.jsonl';self.router.trace=path
        obj={'jsonrpc':'2.0','id':'fixture','method':'UNTRUSTED_PRIVATE_LOOKING_TEXT','params':{'id':'unknown'}};messages=[]
        async def receive():return {'type':'http.request','body':json.dumps(obj).encode(),'more_body':False}
        async def send(message):messages.append(message)
        await self.router(scope(),receive,send)
        text=path.read_text();self.assertNotIn(obj['method'],text)
        self.assertEqual(json.loads(text.splitlines()[-1])['method'],'unknown_rpc')
    async def test_maintenance_blocks_current_writes_but_not_reads_or_legacy(self):
        self.assertTrue(self.db.maintenance_enabled());result=await self.call(rpc('SendMessage'));self.assertEqual(result.status,503);self.assertEqual(self.client.calls,[])
        t=task('current-read');await SQLiteTaskStore(self.db).save(t,ServerCallContext());result=await self.call(rpc('GetTask',t.id));self.assertEqual(result.status,200)
        legacy=task('legacy-write');self.db.save_legacy_snapshot(legacy.id,legacy.SerializeToString(),18805);self.client.tasks[18805,legacy.id]=legacy
        result=await self.call(rpc('GetTask',legacy.id));self.assertEqual(result.status,200)

if __name__=='__main__':unittest.main(verbosity=2)
