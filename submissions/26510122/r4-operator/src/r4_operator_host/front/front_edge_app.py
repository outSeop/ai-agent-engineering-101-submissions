"""Host-only SDK task routing. No join, Model policy, ledger mutation or background loop."""
import asyncio,json,os,time,stat
from contextvars import ContextVar
from pathlib import Path
from threading import Lock
import httpx

_CAPTURE_LOCK=Lock()
_REQUEST_BUDGET=ContextVar('front_edge_request_model_budget',default=None)
class EdgeModelBudgetExceeded(RuntimeError):pass
class OneDecisionModel:
    def __init__(self,original):self.original=original
    def complete(self,messages,**kwargs):
        state=_REQUEST_BUDGET.get()
        if state is None or state['calls']>=1:raise EdgeModelBudgetExceeded('one request decision allowed')
        left=state['deadline']-time.monotonic()
        if left<=5:raise EdgeModelBudgetExceeded('request budget exhausted')
        state['calls']+=1;options=dict(kwargs);options['timeout']=min(30,left-5,float(options.get('timeout',30)));options['max_tokens']=800
        return self.original.complete(messages,**options)
HOP={b'connection',b'keep-alive',b'proxy-authenticate',b'proxy-authorization',b'te',b'trailer',b'transfer-encoding',b'upgrade',b'content-length',b'content-encoding'}

def capture_sdk_app(app_factory,*args,task_store=None):
    # Original agent_app imports its task store constructor on invocation.
    # Capture the native instance only during single-threaded assembly, then restore.
    import a2a.server.tasks as tasks
    with _CAPTURE_LOCK:
        original=tasks.InMemoryTaskStore
        if task_store is not None and not isinstance(task_store,tasks.TaskStore):raise TypeError('native TaskStore required')
        store=original() if task_store is None else task_store
        tasks.InMemoryTaskStore=lambda:store
        try:app=app_factory(*args)
        finally:tasks.InMemoryTaskStore=original
    return app,store

def referenced_task(payload):
    if not isinstance(payload,dict):return None
    method=payload.get('method');params=payload.get('params')
    if not isinstance(params,dict):return None
    if method in ('SendMessage','message/send'):
        message=params.get('message')
        value=(message.get('taskId') or message.get('task_id')) if isinstance(message,dict) else None
    elif method in ('GetTask','tasks/get','CancelTask','tasks/cancel'):
        value=params.get('id') or params.get('taskId') or params.get('task_id')
    else:value=None
    return value if isinstance(value,str) and 0<len(value)<=256 else None

class FrontEdge:
    def __init__(self,app,store,*,trace=None,old_request=None,config=None,before_new=None,admission=None,persistent_engine=False,state_db=None):
        self.app,self.store,self.trace,self.old_request=app,store,trace,old_request
        if config is None:raise ValueError('reviewed front configuration required')
        if type(persistent_engine) is not bool or (persistent_engine and state_db is None):raise ValueError('persistent engine requires private HOST state')
        self.config=config;self.marker=config.marker.encode('ascii');self.before_new=before_new;self.admission=admission
        self.persistent_engine,self.state_db=persistent_engine,state_db
    def record(self,**row):
        if self.trace is None:return
        try:
            row={'at':time.time(),**row};fd=os.open(self.trace,os.O_WRONLY|os.O_APPEND|os.O_CREAT|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'w') as f:
                item=os.fstat(f.fileno())
                if not stat.S_ISREG(item.st_mode) or item.st_uid!=os.getuid() or item.st_nlink!=1 or stat.S_IMODE(item.st_mode)!=0o600:raise ValueError('unprotected edge trace')
                f.write(json.dumps(row)+'\n')
        except (OSError,ValueError):self.trace_unavailable=True
    async def proxy(self,scope,body):
        # Fixed destination; source exception keeps this out of the proposed source=.1 rule.
        if self.old_request is not None:return await self.old_request(scope,body)
        headers=[(k.decode('latin1'),v.decode('latin1')) for k,v in scope.get('headers',[]) if k.lower() not in HOP and k.lower()!=b'host']
        transport=httpx.AsyncHTTPTransport(local_address='127.0.0.2',retries=0)
        async with httpx.AsyncClient(transport=transport,trust_env=False,follow_redirects=False,timeout=155) as client:
            url=httpx.URL('http://127.0.0.1:'+str(self.config.old_proxy_port)+scope['path']).copy_with(query=scope.get('query_string',b''))
            r=await client.request(scope['method'],url,headers=headers,content=body)
        headers=[(k.encode('latin1'),v.encode('latin1')) for k,v in r.headers.multi_items() if k.lower().encode() not in HOP]
        return r.status_code,headers,r.content
    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        began=time.monotonic();body=b'';messages=[]
        if scope['method']=='POST' and scope['path']=='/':
            while True:
                message=await receive();messages.append(message)
                if message['type']!='http.request':break
                body+=message.get('body',b'')
                if len(body)>65536:
                    await send({'type':'http.response.start','status':413,'headers':[(b'x-r4-edge',self.marker)]});await send({'type':'http.response.body','body':b'request too large'});self.record(route='rejected_size',status=413);return
                if not message.get('more_body'):break
        task=None;payload=None
        if body:
            try:payload=json.loads(body);task=referenced_task(payload)
            except (ValueError,TypeError):pass
        proxy_card=scope['method']=='GET' and scope['path']=='/.well-known/agent-card.json'
        from a2a.server.context import ServerCallContext
        old_task=(not self.persistent_engine) and bool(task) and await self.store.get(task,ServerCallContext()) is None
        route='old_card' if proxy_card else 'old_task' if old_task else 'new_sdk'
        method=payload.get('method') if isinstance(payload,dict) else None
        write_request=isinstance(method,str) and method in {'SendMessage','message/send','SendStreamingMessage','message/stream','CancelTask','tasks/cancel'}
        if scope['method']=='POST' and self.before_new is not None and (not self.persistent_engine or write_request):
            try:
                checked=await asyncio.to_thread(self.before_new)
                if hasattr(checked,'__await__'):await checked
            except Exception as error:
                self.record(route='identity_unavailable',error_type=type(error).__name__,Model_calls=0)
                await send({'type':'http.response.start','status':503,'headers':[(b'x-r4-edge',self.marker),(b'content-type',b'application/json')]})
                await send({'type':'http.response.body','body':b'{"error":"original shop identity temporarily unavailable"}'});return
        if proxy_card or old_task:
            try:status,headers,answer=await self.proxy(scope,body)
            except (httpx.HTTPError,OSError,ValueError) as error:
                self.record(route=route,status=502,error_type=type(error).__name__,has_task=bool(task),seconds=round(time.monotonic()-began,4))
                await send({'type':'http.response.start','status':502,'headers':[(b'x-r4-edge',self.marker),(b'content-type',b'application/json')]});await send({'type':'http.response.body','body':b'{"error":"original endpoint temporarily unavailable"}'});return
            headers=[(k,v) for k,v in headers if k.lower()!=b'x-r4-edge'];headers.append((b'x-r4-edge',self.marker));await send({'type':'http.response.start','status':status,'headers':headers});await send({'type':'http.response.body','body':answer});self.record(route=route,status=status,has_task=bool(task),seconds=round(time.monotonic()-began,4));return
        if self.persistent_engine and scope['method']=='POST' and isinstance(payload,dict) and payload.get('method') in {'SendMessage','message/send','SendStreamingMessage','SendMessageStream','message/stream','message/sendStream','CancelTask','tasks/cancel'}:
            try:maintenance=self.state_db.maintenance_enabled()
            except Exception:maintenance=True
            if maintenance:
                self.record(route='engine_maintenance',Model_calls=0)
                await send({'type':'http.response.start','status':503,'headers':[(b'x-r4-edge',self.marker),(b'content-type',b'application/json')]})
                await send({'type':'http.response.body','body':b'{"error":"shop engine temporarily in maintenance"}'});return
        # Only a first local task admission is gated. Own continuations and all old task/card proxies stay available.
        if not self.persistent_engine and scope['method']=='POST' and scope['path']=='/' and task is None:
            try:allowed=self.admission is not None and self.admission.admit()
            except Exception:allowed=False
            if not allowed:
                self.record(route='new_task_gate_closed',Model_calls=0)
                await send({'type':'http.response.start','status':503,'headers':[(b'x-r4-edge',self.marker),(b'content-type',b'application/json')]})
                await send({'type':'http.response.body','body':b'{"error":"shop request upgrade in progress; continue an existing task or retry shortly"}'});return
        async def replay():return messages.pop(0) if messages else await receive()
        async def observed(message):
            if message['type']=='http.response.start':
                message={**message,'headers':[*message.get('headers',[]),(b'x-r4-edge',self.marker)]};self.record(route=route,status=message['status'],has_task=bool(task),seconds=round(time.monotonic()-began,4))
            await send(message)
        state={'deadline':began+40,'calls':0};token=_REQUEST_BUDGET.set(state)
        try:
            return await self.app(scope,replay,observed)
        finally:
            self.record(route='new_request_finished',Model_calls=state['calls'],seconds=round(time.monotonic()-began,4));_REQUEST_BUDGET.reset(token)
