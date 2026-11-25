"""One bounded classroom-model marketing tick over the existing pinned forum tool.
External host wiring; no new business tool, trading, wallet transfer or daemon.
"""
import argparse
from contextlib import redirect_stdout, redirect_stderr
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from forum_official_mind_canary import verify_source, NoWallet, PIN


class PublicationBoundary:
    def __init__(self, execute, allow_post):
        self.execute=execute
        self.allow_post=allow_post
        self.attempted=False
        self.calls=[]
    def __call__(self, request):
        if (type(request) is not dict or type(request.get('action')) is not str
            or request['action'] not in {'reconcile','context','publish'}):
            return {'status':'host_action_rejected'}
        if request['action']=='publish':
            if self.attempted:
                return {'status':'host_attempt_limit'}
            self.attempted=True
            if not self.allow_post:
                result={'status':'dry_selection','decision':request.get('decision')}
                self.calls.append({'action':'publish','result':result})
                return result
        result=self.execute(request)
        self.calls.append({'action':request['action'],'result':result})
        return result


def verify_kit(operator):
    metadata=json.loads((operator/'sources/upstream.json').read_text(encoding='utf-8'))
    entries=metadata.get('files')
    if type(entries) is not list or len(entries)!=7:
        raise RuntimeError('official kit manifest requires exactly seven inputs')
    names=[]
    for entry in entries:
        if type(entry) is not dict:
            raise RuntimeError('invalid official kit manifest entry')
        name=entry.get('name');expected=entry.get('upstream_git_blob_sha')
        if (type(name) is not str or Path(name).name!=name or name in ('', '.', '..')
            or name in names or type(expected) is not str):
            raise RuntimeError('invalid official kit manifest entry')
        names.append(name)
        data=(operator/'kit'/name).read_bytes()
        import hashlib
        actual=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        if actual!=expected:
            raise RuntimeError('official kit integrity mismatch: '+name)
    return 7


def active_customer(root):
    pending=set()
    path=root/'.kit/transport-metrics.jsonl'
    if not path.exists():
        return True
    since=time.time()-120
    for line in path.read_text().splitlines():
        row=json.loads(line)
        if row.get('at',0)<since:
            continue
        if row.get('event')=='request_start':pending.add(row['internal_ref'])
        elif row.get('event')=='request_end':pending.discard(row['internal_ref'])
    return bool(pending)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--operator',type=Path,required=True)
    parser.add_argument('--session',type=Path,required=True)
    parser.add_argument('--allow-one-post',action='store_true')
    args=parser.parse_args();op=args.operator.resolve(strict=True);root=op.parent/'round-4';session=args.session.resolve()
    if session.parent!=(op/'runtime').resolve() or not session.name.startswith('forum-campaign-') or session.exists():
        parser.error('fresh direct runtime/forum-campaign-* session required')
    os.umask(0o077);session.mkdir(mode=0o700);(session/'logs').mkdir(mode=0o700)
    import fcntl
    with (op/'runtime/forum-campaign.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({'status':'already_running'}));return 0
        with (session/'logs/console-private.log').open('x') as log,redirect_stdout(log),redirect_stderr(log):
            sdk_verified=verify_kit(op)
            verify_source(root)
            state=subprocess.check_output(['systemctl','--user','is-active','ourolabs-market-r4.service'],text=True).strip()
            if state!='active':raise RuntimeError('shop is not active')
            sys.path[:0]=[str(op/'kit'),str(root/'codex-r4')]
            import agent_kit as official
            import worker_bootstrap
            from marketing_runtime import MarketingCoordinator
            official.mk.LOG_FILE=session/'logs/agent-kit-private.log'
            for key in ('AGENT_LLM_BASE','AGENT_LLM_MODEL','AGENT_LLM_KEY'):os.environ.pop(key,None)
            registered=worker_bootstrap.validated_kit(root);token=registered.token('shop')
            ctx={'name':registered.name,'market':registered.market,'shop_url':registered.shop_url,
                 'tokens':{'shop':token},'addresses':{'shop':registered.address('shop')},'signer':NoWallet()}
            toolbox=official.Toolbox(root,ctx)
            def execute(request):
                verify_source(root)
                envelope=toolbox.run('forum_marketing','call',{**request,'preset':'aggressive'},d=root/'tools/forum_marketing')
                if not isinstance(envelope,dict) or envelope.get('ok') is not True or not isinstance(envelope.get('result'),dict):
                    return {'status':'authoritative_check_unavailable'}
                return envelope['result']
            boundary=PublicationBoundary(execute,args.allow_one_post)
            config={'llm':{'base':'market'}};model=official.Model(config,registered.market,{'tokens':{'shop':token}})
            class BoundedClassModel:
                def __init__(self):
                    self.safe_error=None
                def complete(self,messages):
                    try:
                        return model.complete(messages,timeout=35,max_tokens=500)
                    except Exception as error:
                        kind=type(error).__name__
                        public_kind=kind if len(kind)<=80 and kind.isascii() and kind.replace('_','').isalnum() else 'ModelError'
                        self.safe_error={'error_type':public_kind,'reason':'model_call_failed'}
                        status=getattr(getattr(error,'response',None),'status_code',None)
                        if type(status) is int and 100<=status<=599:
                            self.safe_error.update(http_status=status,reason='http_status_error')
                        elif 'timeout' in public_kind.lower():
                            self.safe_error['reason']='model_timeout'
                        # Error text may contain HTTP response details: keep it only in the private session.
                        try:
                            with (session/'model-error-private.json').open('x',encoding='utf-8') as diagnostic:
                                json.dump({'error_type':kind,'message':str(error)},diagnostic,ensure_ascii=False,indent=2)
                                diagnostic.write('\n')
                        except OSError:
                            self.safe_error['private_diagnostic_unavailable']=True
                        raise
            bounded_model=BoundedClassModel()
            coordinator=MarketingCoordinator(boundary,bounded_model,customer_active=lambda:active_customer(root))
            result=coordinator.tick()
            (session/'tool-results-private.json').write_text(json.dumps(boundary.calls,ensure_ascii=False,indent=2)+'\n')
            summary={'at':time.time(),'status':result.get('status','invalid_result'),'live_post_enabled':args.allow_one_post,
                     'publication_attempts':int(boundary.attempted),'official_kit_files_verified':sdk_verified,'class_model':'market','tool_authorship':'reused external legacy forum_marketing v5',
                     'entrypoint':'existing MarketingCoordinator.tick, official Model and Toolbox','tool_pins':PIN,'wallet_transfer_allowed':False}
            if bounded_model.safe_error is not None:
                summary['model_error']=bounded_model.safe_error
            for key in ('post','sku','grade'):
                if key in result:summary[key]=result[key]
            if result.get('status')=='posted':
                import httpx
                post=result.get('post');r=httpx.get(registered.market+'/api/forum',params={'since':max(0,post-1),'limit':20},timeout=12,trust_env=False);r.raise_for_status()
                actual=next((p for p in r.json() if p.get('id')==post and p.get('author')=='outseop-r4' and p.get('role')=='shop' and p.get('round')==4),None)
                summary['public_post_verified']=actual is not None
                if actual is not None:(session/'public-post.json').write_text(json.dumps(actual,ensure_ascii=False,indent=2)+'\n')
            (session/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(summary,ensure_ascii=False));return 0


if __name__=='__main__':raise SystemExit(main())
