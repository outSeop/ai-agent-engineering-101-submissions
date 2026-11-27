"""Independent router review: full ASGI, trusted SDK owner scopes and lock deadline.
Real SQLite is temporary; every peer is fake. No live HTTP, wallet, ledger or Model.
"""
from pathlib import Path
import asyncio,json,sys,tempfile,unittest
from unittest.mock import patch
OPERATOR=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(OPERATOR/'src/r4_operator_host/front'),str(OPERATOR/'src/r4_operator_host')]
import flat_router as router
from task_state import TaskStateDB,SQLiteTaskStore
from a2a.types import Task,TaskStatus,TaskState
from a2a.server.context import ServerCallContext
from google.protobuf.json_format import MessageToDict

def scope(auth=b'synthetic-valid-owner-a'):
 return {'type':'http','method':'POST','path':'/','query_string':b'','headers':[(b'a2a-version',b'1.0'),(b'authorization',auth)]}
def rpc(method,ident=None):
 return {'jsonrpc':'2.0','id':'synthetic-rpc','method':method,'params':{'id':ident} if method=='GetTask' else {'message':{'messageId':'synthetic-message','role':'ROLE_USER','metadata':{'from':'untrusted-claim-owner-a'},'parts':[{'text':'synthetic public inquiry'}]}}}
class Peer:
 def __init__(self,db):self.db=db;self.calls=[]
 async def request(self,port,request,body,**kwargs):
  value=json.loads(body);self.calls.append((port,value.get('method')))
  # Test-only validated principals. Production authority is still the native backend.
  principal='trusted-a' if dict(request['headers']).get(b'authorization')==b'synthetic-valid-owner-a' else 'trusted-b'
  store=SQLiteTaskStore(self.db,owner_resolver=lambda context:principal)
  if value['method']=='SendMessage':
   t=Task(id='synthetic-scoped-task',context_id='synthetic-context',status=TaskStatus(state=TaskState.TASK_STATE_INPUT_REQUIRED));await store.save(t,ServerCallContext());result={'task':MessageToDict(t)}
  elif value['method']=='GetTask':
   t=await store.get(value['params']['id'],ServerCallContext())
   if t is None:return router.Reply(200,[],json.dumps({'jsonrpc':'2.0','id':value['id'],'error':{'code':-32001,'message':'Task not found'}}).encode())
   result=MessageToDict(t)
  else:raise AssertionError('unexpected fake peer operation')
  return router.Reply(200,[(b'content-type',b'application/json')],json.dumps({'jsonrpc':'2.0','id':value['id'],'result':result}).encode())
class RouterReviewTests(unittest.IsolatedAsyncioTestCase):
 def setUp(self):
  temporary=tempfile.TemporaryDirectory(prefix='router-independent-review-');self.addCleanup(temporary.cleanup);self.db=TaskStateDB(Path(temporary.name)/'tasks.sqlite3');self.peer=Peer(self.db);self.app=router.FlatRouter(self.db,worker_port=18812,legacy_ports=[18805,18806],client=self.peer)
 async def asgi(self,payload):
  messages=[]
  async def receive():return {'type':'http.request','body':json.dumps(payload).encode(),'more_body':False}
  async def send(message):messages.append(message)
  await self.app(scope(),receive,send)
  response=next(m for m in messages if m['type']=='http.response.start');body=b''.join(m.get('body',b'') for m in messages if m['type']=='http.response.body');return response['status'],json.loads(body)
 async def test_malformed_method_full_ASGI_returns400_without_dispatch(self):
  for method in [[],{},42,True,None]:
   with self.subTest(method_type=type(method).__name__):
    status,body=await self.asgi({'jsonrpc':'2.0','id':'synthetic-rpc','method':method,'params':{}})
    self.assertEqual(status,400);self.assertEqual(body['error']['code'],-32600)
  self.assertEqual(self.peer.calls,[])
 async def test_scoped_current_route_preserves_backend_authority(self):
  self.db.set_maintenance(False);created=rpc('SendMessage');response=await self.app.dispatch(scope(),json.dumps(created).encode(),created)
  self.assertEqual(response.status,200);self.assertEqual(self.db.transport_route('synthetic-scoped-task'),'current')
  self.assertEqual(self.db.get_route('synthetic-scoped-task','trusted-a'),'current');self.assertIsNone(self.db.get_route('synthetic-scoped-task','trusted-b'))
  read=rpc('GetTask','synthetic-scoped-task');allowed=await self.app.dispatch(scope(),json.dumps(read).encode(),read);self.assertNotIn('error',json.loads(allowed.body))
  denied=await self.app.dispatch(scope(b'synthetic-valid-owner-b'),json.dumps(read).encode(),read);self.assertEqual(json.loads(denied.body)['error']['code'],-32001)
  # Routing is global location knowledge, not permission to read another user's task.
  self.assertTrue(all(port==18812 for port,method in self.peer.calls));self.assertEqual(len(self.peer.calls),3)
 async def test_owner_discovery_deadline_includes_lock_queue(self):
  await self.app.resolve_lock.acquire();original=asyncio.wait_for;timeouts=[]
  async def shortened(awaitable,timeout):
   timeouts.append(timeout);self.assertEqual(timeout,8);return await original(awaitable,timeout=.025)
  try:
   with patch.object(router.asyncio,'wait_for',shortened):
    with self.assertRaisesRegex(router.OwnerUnavailable,'deadline'):await self.app.resolve('synthetic-unresolved-task',scope())
  finally:self.app.resolve_lock.release()
  self.assertEqual(timeouts,[8]);self.assertEqual(self.peer.calls,[])
if __name__=='__main__':unittest.main(verbosity=2)
