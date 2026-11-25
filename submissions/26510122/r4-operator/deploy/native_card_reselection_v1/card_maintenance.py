"""External maintenance: original same-choice keeper, then bounded class reselection.
Default dry. Root explicitly opts in; no original shared source is replaced.
"""
import argparse,fcntl,importlib.util,json,math,os,re,secrets,stat,sys,time
from hashlib import sha256
from pathlib import Path
HERE=Path(__file__).resolve().parent
CORE_SHA='2f75961bc0f49fd1337aca0b2f54e36e44f8171ae4dc6b34ed4dc60d2769cd4c'
def core_module():
    path=HERE/'card_class_reselection_host.py';raw=path.read_bytes()
    if sha256(raw).hexdigest()!=CORE_SHA:raise ValueError('reviewed reselection host changed')
    spec=importlib.util.spec_from_file_location('_reviewed_card_reselection_host',path);module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module);module.checked(path);module.verify_apply();return module
def atomic(path,value):
    raw=(json.dumps(value,sort_keys=True)+'\n').encode();temp=path.parent/('.state-'+secrets.token_hex(8));fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,path)
    finally:
        if temp.exists():temp.unlink()
def foreground(root):
    p=root/'.kit/transport-metrics.jsonl'
    if not p.is_file() or p.is_symlink() or p.stat().st_size>4*1024*1024:return True
    try:
        pending=set();since=time.time()-300
        raw=p.read_bytes();lines=raw.splitlines()
        if raw and not raw.endswith(b'\n'):lines=lines[:-1]
        for line in lines:
            x=json.loads(line)
            if x.get('at',0)<since:continue
            if x.get('event')=='request_start':pending.add(x['internal_ref'])
            elif x.get('event')=='request_end':pending.discard(x['internal_ref'])
        return bool(pending)
    except (OSError,ValueError,TypeError,KeyError):return True
def maintain(operator,*,allow=False,cooldown=600,_legacy=None,_select=None,_foreground=None,_clock=time.time):
    core=core_module();operator=Path(operator).resolve(strict=True)
    if not allow:return {'status':'dry','class_selection_allowed':False,'card_written':False}
    if type(cooldown) is not int or not 120<=cooldown<=3600:raise ValueError('cooldown outside120..3600')
    if _legacy is None:
        core.verify_sdk(operator);base=core.load_base(operator);legacy=lambda:base.run_once(operator=operator,allow_refresh=True)
    else:legacy=_legacy
    selector=(lambda:core.run(operator,allow_live=True)) if _select is None else _select
    active=(lambda:foreground(operator.parent/'round-4')) if _foreground is None else _foreground
    state_dir=operator/'runtime/card-reselection-control';state_dir.mkdir(mode=0o700,exist_ok=True)
    info=state_dir.lstat()
    if state_dir.resolve()!=state_dir or info.st_uid!=os.getuid() or info.st_mode&0o077:raise ValueError('unprotected control directory')
    lock=state_dir/'maintenance.lock';fd=os.open(lock,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return {'status':'busy','class_selection_invoked':False}
        held=os.fstat(fd);named=lock.lstat()
        if (held.st_dev,held.st_ino)!=(named.st_dev,named.st_ino) or not stat.S_ISREG(held.st_mode) or held.st_uid!=os.getuid() or held.st_nlink!=1 or held.st_mode&0o077:raise ValueError('maintenance lock changed')
        result=legacy();status=result.get('status')
        if status!='requires_class_selection':return {'status':status or 'legacy_unavailable','class_selection_invoked':False,'legacy_receipt':result}
        state_path=state_dir/'state.json';state=json.loads(core.checked(state_path,65536)) if state_path.exists() else {'schema':'outseop-r4.card-reselection-control.v1','attempts':0,'retry_after':0}
        if state.get('schema')!='outseop-r4.card-reselection-control.v1' or type(state.get('attempts')) is not int or type(state.get('retry_after')) not in (int,float) or not math.isfinite(state['retry_after']) or state['retry_after']<0 or state['attempts']<0:raise ValueError('invalid cooldown state')
        now=_clock()
        if now<state['retry_after']:return {'status':'selection_cooldown','class_selection_invoked':False,'retry_after':state['retry_after'],'legacy_status':status}
        if active():return {'status':'selection_postponed_for_customer','class_selection_invoked':False,'legacy_status':status}
        state.update(attempts=state['attempts']+1,last_started=now,retry_after=now+cooldown,last_status='selection_started');atomic(state_path,state)
        try:
            selected=selector();selected_status=selected.get('status','reselection_unavailable')
        except Exception as error:
            selected_status='reselection_unavailable';selected={'status':selected_status,'error_type':type(error).__name__}
            atomic(state_dir/'last-error-private.json',{'error_type':type(error).__name__,'message':str(error)})
        state['last_status']=selected_status if isinstance(selected_status,str) and re.fullmatch('[a-z][a-z0-9_]{0,100}',selected_status) else 'reselection_unavailable'
        state['last_finished']=_clock()
        if selected_status in ('applied','already_applied'):state['retry_after']=0
        atomic(state_path,state)
        return {'status':state['last_status'],'class_selection_invoked':True,'retry_after':state['retry_after'],'result':selected}
    finally:os.close(fd)
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--operator',type=Path,required=True);parser.add_argument('--allow-maintenance',action='store_true');parser.add_argument('--failure-cooldown',type=int,default=600);args=parser.parse_args();os.umask(0o077)
    try:result=maintain(args.operator,allow=args.allow_maintenance,cooldown=args.failure_cooldown)
    except Exception as error:result={'status':'maintenance_unavailable','error_type':type(error).__name__,'class_selection_invoked':False}
    print(json.dumps(result));return 0
if __name__=='__main__':raise SystemExit(main())
