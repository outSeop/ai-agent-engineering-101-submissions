"""External optional official-Mind tick; original coordinator loop/cadence unchanged."""
from pathlib import Path
from copy import deepcopy
from hashlib import sha256
import importlib.util,json,os,re,tempfile,time

class OfficialForumModelFailure(RuntimeError):pass

def private_json(path,value):
    raw=(json.dumps(value,ensure_ascii=False,default=str)+"\n").encode()
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(raw)

def load_campaign(operator):
    path=operator/'deploy/forum_campaign_operator.py'
    if path.resolve()!=path or sha256(path.read_bytes()).hexdigest()!='65d4a1e390e2fcac0f424d459562673bd06097105eeefbfa28e8acba17a83c54':raise ValueError('campaign host source drift')
    import sys
    if str(path.parent) not in sys.path:sys.path.insert(0,str(path.parent))
    spec=importlib.util.spec_from_file_location('_reviewed_campaign_for_background',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

class RecordingModel:
    def __init__(self,inner,folder,secrets,seconds=35):
        self.inner,self.folder,self.secrets=inner,folder,[v for v in secrets if isinstance(v,str) and v]
        self.deadline=time.monotonic()+seconds;self.calls=0;self.safe_error=None
    def clean(self,value):
        if isinstance(value,dict):return {k:self.clean(v) for k,v in value.items()}
        if isinstance(value,list):return [self.clean(v) for v in value]
        if not isinstance(value,str):return value
        for secret in self.secrets:value=value.replace(secret,'[REDACTED_TOKEN]')
        return re.sub(r'eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|(?:gh[pousr]_|sk-)[A-Za-z0-9_-]{15,}','[REDACTED_TOKEN]',value)
    def complete(self,messages,**kwargs):
        left=self.deadline-time.monotonic()
        if left<=0:raise OfficialForumModelFailure('bounded model budget exhausted')
        self.calls+=1;number=self.calls;started=time.time();options=dict(kwargs);options['timeout']=min(35,left,float(options.get('timeout',35)))
        private_json(self.folder/f'model-request-{number}.json',self.clean({'at':started,'messages':messages,'kwargs':options}))
        try:raw=self.inner.complete(messages,**options)
        except Exception as error:
            kind=type(error).__name__;status=getattr(getattr(error,'response',None),'status_code',None)
            self.safe_error={'error_type':kind if re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,79}',kind) else 'ModelError'}
            if type(status) is int and 100<=status<=599:self.safe_error['http_status']=status
            private_json(self.folder/f'model-error-{number}-private.json',self.clean({'at':time.time(),'error_type':kind,'message':str(error)}))
            raise OfficialForumModelFailure('official forum model failed') from error
        private_json(self.folder/f'model-response-{number}-private.json',self.clean({'at':time.time(),'response':raw}))
        return raw

class BackgroundTick:
    def __init__(self,official,coordinator,operator,root,agent,model,ctx,*,campaign=None,now=time.time):
        self.official,self.coordinator,self.operator,self.root=official,coordinator,Path(operator),Path(root)
        self.agent,self.model,self.ctx=deepcopy(agent),model,ctx
        self.campaign=campaign or load_campaign(self.operator);self.now=now;self.session=None;self.last_summary=None
    def audit(self,phase,payload):
        if self.session is None:return
        if phase not in ('native_input','native_result','context'):raise ValueError('unknown native audit phase')
        name=f'{phase}-{time.time_ns()}.json';private_json(self.session/name,{'at':self.now(),'data':payload})
    def tick(self):
        c=self.coordinator
        if c.customer_active() or self.now()<c.next_poll:return {'status':'postponed'}
        c.next_poll=self.now()+120
        parent=self.operator/'runtime/forum-background-official';parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        if parent.is_symlink() or parent.stat().st_uid!=os.getuid() or parent.stat().st_mode&0o077:raise ValueError('unsafe forum audit directory')
        self.session=Path(tempfile.mkdtemp(prefix='tick-',dir=parent));os.chmod(self.session,0o700)
        summary={'started_at':self.now(),'status':'unavailable','model_calls':0,'publication_attempts':0,'official_run_once_inherited':True,'external_host_hook':True};bounded=None;gate=None
        try:
            # SDK sets shop_url and shop token only after constructing Mind, before loop starts.
            if not self.ctx.get('shop_url') or not self.ctx.get('tokens',{}).get('shop'):
                summary['status']='registration_not_ready';return self.finish(summary)
            recovery=c.execute({'action':'reconcile'});private_json(self.session/'reconcile-private.json',recovery)
            if recovery.get('status')!='nothing_to_reconcile':summary['status']=recovery.get('status','invalid_reconcile');return self.finish(summary)
            view=c.execute({'action':'context'});private_json(self.session/'context-private.json',view)
            if view.get('status')!='options' or not view.get('items') or not (view.get('spotlight_allowed') or view.get('reply_options')):
                summary['status']=view.get('status','invalid_context');return self.finish(summary)
            if c.customer_active():summary['status']='postponed';return self.finish(summary)
            c.next_poll=self.now()+330
            campaign=self.campaign
            class EligibilityFacade(campaign.ForumFacade):
                def call(gate,name,args):
                    decision=args.get('decision',{}) if isinstance(args,dict) else {}
                    if decision.get('action')=='spotlight' and any((row.get('sku'),row.get('grade'))==(decision.get('sku'),decision.get('grade')) and row.get('spotlight_eligible') is False for row in gate.context.get('items',[])):
                        return {'status':'choice_not_eligible','reason':'native_spotlight_closed','guidance':'Choose a displayed spotlight_eligible true item or an eligible buyer reply; do not repeat the closed choice.'}
                    return super().call(name,args)
            gate=EligibilityFacade(c.execute,view,True,c.customer_active)
            # No original business rules: follow native eligibility and selection_policy only.
            agent=deepcopy(self.agent);agent.update(llm={'base':'market'},max_steps=5,run_minutes=2,persona='outseop-r4의 정확한 공개 포럼 홍보 담당자',goal='원본 공개 후보를 보고 실제 관련 구매 요청 reply를 우선 검토한다. spotlight는 spotlight_eligible=true인 표시된 후보만 선택하고 native selection_policy/preferred pool 안내를 존중한다. C로 닫힌 후보를 반복하지 않는다. 포장 구분 unknown이면 수량을 추정하지 않는다. 선택은 forum_marketing publish의 정확한 action,sku,grade,reply일 때 thread만 사용한다. 본문·가격·링크는 원도구가 작성한다. 한 번 게시 시도 후 sleep. 근거가 없으면 sleep. 도구생성·도구읽기·메모·고객메시지전송은 하지 않는다.')
            bounded=RecordingModel(self.model,self.session,list(self.ctx.get('tokens',{}).values()))
            model_ctx={'name':self.ctx['name'],'market':self.ctx['market'],'shop_url':None,'tokens':{},'addresses':{}}
            mind=campaign.make_campaign_mind(self.official,self.session,agent,bounded,gate,model_ctx)
            raw=json.dumps(view,ensure_ascii=False).encode();summary.update(original_view_sha256=sha256(raw).hexdigest(),original_view_utf8_bytes=len(raw),full_original_view_in_untrusted_user_context=True)
            mind.run_once([])
            summary.update(status=gate.result.get('status','no_selection'),publication_attempts=int(gate.boundary.attempted))
            for k in ('post','sku','grade'):
                if k in gate.result:summary[k]=gate.result[k]
        except Exception as error:
            summary['status']='model_unavailable' if bounded and bounded.safe_error else 'background_tick_unavailable';summary['error_type']=type(error).__name__
            private_json(self.session/'tick-error-private.json',{'at':self.now(),'error_type':type(error).__name__})
        finally:
            if gate is not None:
                summary['publication_attempts']=int(gate.boundary.attempted)
                private_json(self.session/'publication-outcome-private.json',{'result':gate.result,'calls':gate.boundary.calls})
            if bounded:
                summary['model_calls']=bounded.calls
                if bounded.safe_error:summary['model_error']=bounded.safe_error
        return self.finish(summary)
    def finish(self,summary):
        summary['finished_at']=self.now();private_json(self.session/'summary.json',summary);self.last_summary=summary;self.session=None;return summary

def install_tick(official,coordinator,operator,root,agent,model,ctx,*,campaign=None,stock=None):
    hook=BackgroundTick(official,coordinator,operator,root,agent,model,ctx,campaign=campaign)
    coordinator.tick=hook.tick
    if stock is not None:
        original=stock.tick
        def observed_stock_tick(*args,**kwargs):
            result=original(*args,**kwargs)
            try:
                view=result[1] if len(result)>1 else {};opens=view.get('opens_at');delta=opens-time.time() if type(opens) in (int,float) else None
                folder=Path(operator)/'runtime/forum-background-official';folder.mkdir(mode=0o700,parents=True,exist_ok=True)
                if folder.is_symlink() or folder.stat().st_uid!=os.getuid() or folder.stat().st_mode&0o077:raise ValueError('unsafe audit directory')
                row={'at':time.time(),'stock_status':view.get('status'),'opens_delta_seconds':delta,'marketing_idle_by_original_rule':view.get('status')=='waiting' and delta is not None and delta>300,'next_marketing_poll':coordinator.next_poll}
                fd=os.open(folder/'scheduler-observations-private.jsonl',os.O_WRONLY|os.O_CREAT|os.O_APPEND|os.O_NOFOLLOW,0o600)
                with os.fdopen(fd,'w') as stream:stream.write(json.dumps(row)+'\n')
            except (OSError,ValueError,TypeError,KeyError):pass
            return result
        stock.tick=observed_stock_tick
    return hook
