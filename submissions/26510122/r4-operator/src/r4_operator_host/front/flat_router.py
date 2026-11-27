"""One stable transport router: exact task owner lookup, never a release proxy chain.

Only trusted fixed loopback peers are used. No Model, wallet, ledger or business
execution. Unknown owners are learned from each peer's native own-store ListTasks;
network failure is uncertainty, not a TaskNotFound or a reason to retry a message.
"""
import asyncio
from collections import OrderedDict,deque
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import sqlite3
from task_state import RouteConflict,UnsafeTaskState
import tempfile
import time
import httpx
from google.protobuf.json_format import ParseDict
from a2a.types import Task

HOP={b'connection',b'keep-alive',b'proxy-authenticate',b'proxy-authorization',b'te',b'trailer',b'transfer-encoding',b'upgrade',b'content-length',b'content-encoding'}
SEND={'SendMessage','message/send','SendStreamingMessage','message/stream'}
GET={'GetTask','tasks/get'}
WRITE=SEND|{'CancelTask','tasks/cancel'}
MAX_BODY=65536
MAX_RESPONSE=8*1024*1024

class OwnerUnavailable(RuntimeError):pass
class InvalidRequest(ValueError):pass

@dataclass
class Reply:
    status:int
    headers:list
    body:bytes

def unique(pairs):
    obj={}
    for key,value in pairs:
        if key in obj:raise InvalidRequest('duplicate JSON key')
        obj[key]=value
    return obj

def decode(raw):
    return json.loads(raw,object_pairs_hook=unique)

def task_reference(payload):
    if not isinstance(payload,dict):return None
    params=payload.get('params',{})
    if not isinstance(params,dict):return None
    method=payload.get('method')
    if not isinstance(method,str):raise InvalidRequest('JSON-RPC method must be text')
    if method in SEND:
        message=params.get('message',{})
        if not isinstance(message,dict):return None
        value=message.get('taskId',message.get('task_id'))
    elif method in GET|{'CancelTask','tasks/cancel'}:
        value=params.get('id',params.get('taskId',params.get('task_id')))
    else:return None
    if value in (None,''):return None
    if not isinstance(value,str) or len(value)>256 or '\x00' in value:
        raise InvalidRequest('invalid task reference')
    return value

def native_task(payload):
    if not isinstance(payload,dict) or 'error' in payload:return None
    result=payload.get('result')
    if not isinstance(result,dict):return None
    value=result.get('task',result)
    if not isinstance(value,dict) or not isinstance(value.get('id'),str) or 'status' not in value:return None
    return ParseDict(value,Task())

class FixedLoopbackClient:
    def __init__(self,ports):self.ports=frozenset(ports)
    async def request(self,port,scope,body,*,timeout=155):
        if type(port) is not int or port not in self.ports:raise ValueError('peer outside pinned topology')
        headers=[(k.decode('latin1'),v.decode('latin1')) for k,v in scope.get('headers',[]) if k.lower() not in HOP and k.lower()!=b'host']
        transport=httpx.AsyncHTTPTransport(local_address='127.0.0.2',retries=0)
        async with httpx.AsyncClient(transport=transport,trust_env=False,follow_redirects=False,timeout=timeout) as client:
            url=httpx.URL('http://127.0.0.1:'+str(port)+scope['path']).copy_with(query=scope.get('query_string',b''))
            result=await client.request(scope['method'],url,headers=headers,content=body)
        if len(result.content)>MAX_RESPONSE:raise OwnerUnavailable('bounded peer response exceeded')
        headers=[(k.encode('latin1'),v.encode('latin1')) for k,v in result.headers.multi_items() if k.lower().encode() not in HOP]
        return Reply(result.status_code,headers,result.content)

class FlatRouter:
    def __init__(self,state_db,*,worker_port,legacy_ports,marker='r4-flat-router-v1',client=None,trace=None,status_file=None,clock=time.monotonic):
        ports=tuple(legacy_ports)
        if not ports or len(set(ports))!=len(ports) or worker_port in ports:
            raise ValueError('distinct fixed topology required')
        if any(type(port) is not int or not 1<=port<=65535 for port in (*ports,worker_port)):
            raise ValueError('invalid loopback port')
        self.db=state_db;self.worker=worker_port;self.legacy=ports
        self.marker=marker.encode('ascii');self.client=client or FixedLoopbackClient((*ports,worker_port))
        self.trace=trace;self.status_file=status_file;self.clock=clock
        self.resolve_lock=asyncio.Lock();self.misses=OrderedDict();self.discovery=deque()
        self.active_current=0;self.started_at=time.time();self.write_status()
    def record(self,event,**details):
        try:self._record(event,**details)
        except (OSError,ValueError):self.trace_unavailable=True
    def _record(self,event,**details):
        if self.trace is None:return
        path=Path(self.trace);fd=os.open(path,os.O_WRONLY|os.O_APPEND|os.O_CREAT|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as stream:
            info=os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1 or stat.S_IMODE(info.st_mode)!=0o600:
                raise ValueError('unsafe router trace')
            stream.write(json.dumps({'at':time.time(),'event':event,**details})+'\n')
    def write_status(self):
        if self.status_file is None:return
        path=Path(self.status_file)
        if path.parent.resolve()!=path.parent or stat.S_IMODE(path.parent.stat().st_mode)!=0o700 or path.parent.stat().st_uid!=os.getuid():
            raise ValueError('unsafe router status directory')
        fd,name=tempfile.mkstemp(prefix='.router-status-',dir=path.parent)
        try:
            with os.fdopen(fd,'w') as stream:
                json.dump({'pid':os.getpid(),'started_at':self.started_at,'at':time.time(),'active_current':self.active_current},stream)
                stream.flush();os.fsync(stream.fileno())
            os.chmod(name,0o600);os.replace(name,path)
        finally:
            if os.path.exists(name):os.unlink(name)
    def publish_status(self):
        try:self.write_status()
        except (OSError,ValueError):self.status_unavailable=True
    @staticmethod
    def error(code,message,rpc_id=None,status=503):
        return Reply(status,[(b'content-type',b'application/json')],json.dumps({'jsonrpc':'2.0','id':rpc_id,'error':{'code':code,'message':message}}).encode())
    async def own_inventory(self,port,scope,*,deadline):
        cursor='';rows=[];pages=0
        while True:
            left=deadline-self.clock()
            if left<=0:raise OwnerUnavailable('owner discovery deadline')
            params={'pageSize':100,'includeArtifacts':True}
            if cursor:params['pageToken']=cursor
            request={'jsonrpc':'2.0','id':'host-read-only-owner-inventory','method':'ListTasks','params':params}
            inner={**scope,'method':'POST','path':'/','query_string':b'','headers':[(b'a2a-version',b'1.0'),*[(k,v) for k,v in scope.get('headers',[]) if k.lower() not in HOP|{b'a2a-version',b'host'}]]}
            result=await self.client.request(port,inner,json.dumps(request).encode(),timeout=min(2,left))
            if result.status!=200:raise OwnerUnavailable('legacy own-store inventory unavailable')
            value=decode(result.body)
            if not isinstance(value,dict) or 'error' in value or not isinstance(value.get('result'),dict):
                raise OwnerUnavailable('legacy own-store inventory not authoritative')
            page=value['result'];tasks=page.get('tasks',[])
            if not isinstance(tasks,list):raise OwnerUnavailable('invalid legacy inventory')
            rows.extend(ParseDict(row,Task()) for row in tasks);pages+=1
            if len(rows)>3000 or pages>30:raise OwnerUnavailable('legacy inventory capacity exceeded')
            cursor=page.get('nextPageToken','')
            if not cursor:return rows
            if not isinstance(cursor,str):raise OwnerUnavailable('invalid inventory cursor')
    def miss_key(self,task_id,scope):
        # Transport scope stays anonymous like the original SDK endpoint. Backend
        # TaskStore remains the authority for context.user; metadata.from is ignored.
        headers=b'\0'.join(k.lower()+b':'+v for k,v in scope.get('headers',[]) if k.lower() in {b'authorization',b'cookie'})
        return task_id,sha256(headers).digest()
    async def resolve(self,task_id,scope):
        # Includes queueing behind discovery and all peer reads, not just socket IO.
        try:return await asyncio.wait_for(self._resolve(task_id,scope),timeout=8)
        except asyncio.TimeoutError:raise OwnerUnavailable('owner discovery total deadline') from None
    async def _resolve(self,task_id,scope):
        known=await asyncio.to_thread(self.db.transport_route,task_id)
        if known is not None:return known
        key=self.miss_key(task_id,scope);now=self.clock()
        if self.misses.get(key,0)>now:return None
        async with self.resolve_lock:
            known=await asyncio.to_thread(self.db.transport_route,task_id)
            if known is not None:return known
            now=self.clock()
            while self.discovery and self.discovery[0]<now-60:self.discovery.popleft()
            if len(self.discovery)>=12:raise OwnerUnavailable('bounded owner discovery busy')
            self.discovery.append(now)
            # All current tasks are atomically indexed by SQLiteTaskStore.save.
            # Legacy lookup uses own ListTasks, never a proxy GetTask success.
            found=[];uncertain=False;deadline=now+8
            for port in self.legacy:
                try:tasks=await self.own_inventory(port,scope,deadline=deadline)
                except (OwnerUnavailable,httpx.HTTPError,OSError,ValueError):
                    uncertain=True
                    continue
                found.extend((port,task) for task in tasks if task.id==task_id)
            if len(found)>1:raise OwnerUnavailable('duplicate legacy ownership')
            if found:
                port,task=found[0]
                # Own-store evidence is independent of any failed intermediate peer.
                # SDK task IDs are globally unique; later conflicting evidence is refused.
                await asyncio.to_thread(self.db.save_legacy_snapshot,task_id,task.SerializeToString(),port,'',None,'own_list_tasks')
                return port
            if uncertain:raise OwnerUnavailable('legacy ownership uncertain')
            self.misses[key]=self.clock()+10;self.misses.move_to_end(key)
            while len(self.misses)>256:self.misses.popitem(last=False)
            return None
    async def dispatch(self,scope,body,payload):
        method=payload.get('method') if isinstance(payload,dict) else None
        rpc_id=payload.get('id') if isinstance(payload,dict) else None
        if scope['method']=='POST' and (not isinstance(payload,dict) or not isinstance(method,str)):
            return self.error(-32600,'Invalid JSON-RPC request',rpc_id,status=400)
        task=task_reference(payload)
        if scope['method']=='GET' and scope['path']=='/.well-known/agent-card.json':
            return await self.client.request(18805,scope,body,timeout=10)
        owner=await self.resolve(task,scope) if task else 'current'
        if owner is None:
            # Let the current original SDK issue its native TaskNotFound/protocol
            # response. A SendMessage is never replayed or retargeted as a new task.
            if method in SEND:return self.error(-32001,'Task not found',rpc_id,status=404)
            owner='current'
        if owner=='current' and method in WRITE and await asyncio.to_thread(self.db.maintenance_enabled):
            return self.error(-32000,'Shop request engine is briefly in maintenance; existing tasks are retained.',rpc_id)
        port=self.worker if owner=='current' else owner
        if owner=='current':self.active_current+=1;self.publish_status()
        try:
            response=await self.client.request(port,scope,body)
            if response.status==200 and scope['method']=='POST':
                try:task_result=native_task(decode(response.body))
                except (ValueError,TypeError):task_result=None
                if task_result is not None:
                    if owner=='current':
                        # save() must already have atomically established this route.
                        existing=await asyncio.to_thread(self.db.transport_route,task_result.id)
                        if existing!='current':raise OwnerUnavailable('current task missing durable owner')
                    else:
                        await asyncio.to_thread(self.db.save_legacy_snapshot,task_result.id,task_result.SerializeToString(),port,'',None,'known_owner_response')
            return response
        finally:
            if owner=='current':self.active_current-=1;self.publish_status()
    async def __call__(self,scope,receive,send):
        if scope['type']=='lifespan':
            while True:
                message=await receive()
                if message['type']=='lifespan.startup':await send({'type':'lifespan.startup.complete'})
                elif message['type']=='lifespan.shutdown':await send({'type':'lifespan.shutdown.complete'});return
        if scope['type']!='http':return
        body=b'';started=self.clock();payload=None
        if scope['method']=='POST':
            while True:
                message=await receive()
                if message['type']=='http.disconnect':return
                body+=message.get('body',b'')
                if len(body)>MAX_BODY:
                    response=self.error(-32600,'Request too large',status=413);break
                if not message.get('more_body',False):
                    try:payload=decode(body)
                    except (ValueError,TypeError):response=self.error(-32700,'Invalid JSON',status=400)
                    else:response=None
                    break
        else:response=None
        try:
            if response is None:response=await self.dispatch(scope,body,payload)
        except (OwnerUnavailable,httpx.HTTPError,OSError,ValueError,sqlite3.Error,RouteConflict,UnsafeTaskState) as error:
            self.record('peer_or_state_unavailable',error_type=type(error).__name__)
            response=self.error(-32000,'Task owner is temporarily unavailable; the request was not retried.',payload.get('id') if isinstance(payload,dict) else None)
        headers=[(k,v) for k,v in response.headers if k.lower() not in HOP|{b'x-r4-edge'}]
        headers.append((b'x-r4-edge',self.marker))
        await send({'type':'http.response.start','status':response.status,'headers':headers})
        await send({'type':'http.response.body','body':response.body})
        try:has_task=task_reference(payload) is not None if isinstance(payload,dict) else False
        except InvalidRequest:has_task=False
        method=payload.get('method') if isinstance(payload,dict) else None
        label=method if isinstance(method,str) and method in WRITE|GET|{'ListTasks','tasks/list'} else 'unknown_rpc'
        self.record('request_finished',status=response.status,method=label,has_task=has_task,seconds=round(self.clock()-started,4))
