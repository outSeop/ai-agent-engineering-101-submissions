"""Host plumbing for genuine card apply v2. Not installed; no live CLI.

The root installs exact native bundles separately. A reviewed controller calls
apply_verified_stage with its live StageOrigin; persisted JSON cannot resume it.
No rendering, pricing, SKU selection, wallet loading, DB access or Model calls.
"""
from contextlib import contextmanager
from hashlib import sha256
import fcntl,json,os,re,stat,tempfile,time
from pathlib import Path

from card_apply_authority_host import StageOrigin,read_regular
from card_apply_v2_inputs import make_authority

FILES=('permission.yml','logic.py','test.py','forge.json')
PINS={
 'tools/apply_staged_card':('apply_staged_card',2,{
 'permission.yml':'546d5da9e2db2b565ca6420610b1686ca371da9ac4a21d7417e44cf54e0b7a52','logic.py':'4fecb5a59aba74173e10f88a3c79171daa8f729c6ac37b2f037aa7d4ced05c90','test.py':'306e81b3f42c1afe924cb61e16e58e0f91e4bf0affa9f62e44400199e9a426dc','forge.json':'483a67d74084732a1e752c41c18e6bfa0594e2e4e35167762bf368eaf757ace4'}),
 'tools/.deprecated/apply_staged_card@1':('apply_staged_card',1,{
 'permission.yml':'a856de475325229ff7e7745d5912c53dbf7e931ed8d7fa1909b751291901b673','logic.py':'14143d58859493f56b3b736dab10fe384211d8c0c8b58a1b3db59a50a9d5500f','test.py':'c96e43d06d9d30a2548d35e59a2628d0552b2a36978fba2b8d67d715d5041e55','forge.json':'f11267a0efd3c9c995083c53515083f858ebdbe8daf222b0b3be3509c5b72e05'}),
 'tools/stage_representative_card':('stage_representative_card',1,{
 'permission.yml':'a607c48ed5f23a28a6402edcf1445ccc07e8af067888cae1d93803299659b20d','logic.py':'e883b594583e1abf8587a963154d58020a0f0e214451dee1fa3c771d11514fbb','test.py':'65f4378e3a301b871c1a54348d116800eb6aeaa74b86125f162b211a048b8b5e','forge.json':'f4c5bffe5c1804910632a210ffa49187705273dc2485f2bfd057f8fad13b9e98'}),
 'tools/publish_shop_info':('publish_shop_info',1,{
 'permission.yml':'599f987876a750c3349e57b754e2b5c2085a1a9b21e9f290f58ec5ab10e5821b','logic.py':'cb3c5a6e5c6ca36fb329e4b2279c2b718a304386665707ecaf9a7e21eb887dc2','test.py':'bde98d730b945e0adc85c7802f36eb3155521ac79ff7c63f2d2b7234c536e60c','forge.json':'f31f1604abc3157116ecbd284688d04662694be694c787ab8b560918a5236004'})}


def sha(raw):return sha256(raw).hexdigest()
def encode(value):return (json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()

def protected(path,directory=False):
    path=Path(path);info=path.lstat()
    if (path.resolve()!=path or info.st_uid!=os.getuid() or info.st_mode&0o022 or
        not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)) or
        (not directory and info.st_nlink!=1)):
        raise ValueError('unprotected host path')
    return info

def read(path):
    protected(path)
    data,_=read_regular(path)
    if len(data)>24*1024*1024:raise ValueError('oversized host artifact')
    return data

def verify_bundles(root):
    root=Path(root);protected(root,True)
    summary={}
    for relative,(name,version,pins) in PINS.items():
        directory=root/relative;protected(directory,True)
        data={file:read(directory/file) for file in FILES}
        if any(sha(data[file])!=pin for file,pin in pins.items()):raise ValueError('native bundle bytes changed')
        manifest=json.loads(data['forge.json'])
        if (manifest.get('tool'),manifest.get('version'),manifest.get('sha256'))!=(name,version,{k:v for k,v in pins.items() if k!='forge.json'}):raise ValueError('native manifest changed')
        summary[relative]=dict(pins)
    return summary

class NoWallet:
    def grant(self,name,permission,timeout):
        if name not in ('apply_staged_card','publish_shop_info','stage_representative_card') or any(permission.get(k) for k in ('wallet','identity','network','exec','handles')):
            raise PermissionError('card canary has no wallet, token or network capability')
        return None

def toolbox(root,official):
    verify_bundles(root)
    return official.Toolbox(root,{'name':'outseop-r4','market':'https://market.ourolabs.ai','tokens':{},'addresses':{},'signer':NoWallet()})

@contextmanager
def exclusive(root):
    pub=root/'card_publication';protected(pub,True);path=pub/'lock';before=protected(path)
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW),'rb') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if os.fstat(stream.fileno()).st_ino!=path.stat().st_ino:raise ValueError('publication lock substituted')
        yield pub
        if path.stat().st_ino!=before.st_ino:raise ValueError('publication lock substituted')

def atomic_host(path,raw):
    protected(path.parent,True)
    if path.exists():protected(path)
    fd,name=tempfile.mkstemp(prefix='.card-canary-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
        os.chmod(name,0o400);os.replace(name,path)
        d=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(d)
        finally:os.close(d)
    finally:Path(name).unlink(missing_ok=True)

def immutable(path,raw,mtime_ns=None):
    if not path.parent.exists():path.parent.mkdir(mode=0o700)
    protected(path.parent,True)
    if path.exists():
        if read(path)!=raw or (mtime_ns is not None and path.stat().st_mtime_ns!=mtime_ns):raise ValueError('host immutable artifact conflict')
        return
    atomic_host(path,raw)
    if mtime_ns is not None:
        os.utime(path,ns=(mtime_ns,mtime_ns),follow_symlinks=False)
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
        try:os.fsync(fd)
        finally:os.close(fd)

def head(root):
    path=root/'card_publication/head.json'
    if not path.exists():return None
    body=json.loads(read(path))
    if set(body)!= {'event','pending'} or body['pending'] is not None:raise ValueError('pending or invalid publication head')
    event_id=body['event']
    if event_id is not None and not re.fullmatch('[a-f0-9]{64}',event_id):raise ValueError('invalid event id')
    return event_id

def committed(root,expected_event=None):
    event_id=head(root)
    if event_id is None or (expected_event is not None and event_id!=expected_event):raise ValueError('expected committed event missing')
    raw=read(root/'card_publication'/(event_id+'.json'))
    if sha(raw)!=event_id:raise ValueError('committed event changed')
    event=json.loads(raw);card=read(root/'card.json')
    if event['shop']!='outseop-r4' or event['after_sha256']!=sha(card) or event['after_card_json'].encode()!=card:raise ValueError('committed card mismatch')
    return event_id,event

def handoff_locked(root,event_id,event):
    now=int(time.time());until=min(now+300,event['offer_until']) if event['offer_until'] is not None else now+300
    if not event['recorded_at']<=now<until:raise ValueError('handoff would be stale')
    body={'schema':'outseop-r4.card-publication-handoff.v1','shop':'outseop-r4','owner':'native','event':event_id,'card_sha256':event['after_sha256'],'issued_at':now,'valid_until':until}
    atomic_host(root/'host_inputs/card_publication_handoff.json',encode(body))

def finish(root,official,envelope,status):
    if not isinstance(envelope,dict) or envelope.get('ok') is not True or envelope.get('result',{}).get('status') not in status:raise RuntimeError('native call did not commit; inspect journal, never restore legacy publisher')
    result=envelope['result']
    with exclusive(root):
        event_id,event=committed(root,result['event'])
        if result['card_sha256']!=event['after_sha256']:raise ValueError('native result hash mismatch')
        handoff_locked(root,event_id,event)
    guard=toolbox(root,official).call('publish_shop_info',{})
    if guard.get('ok') is not True or guard.get('result',{}).get('status')!='skipped' or guard['result'].get('event')!=event_id:raise RuntimeError('guard handoff not confirmed; keep native fence')
    return {'status':result['status'],'event':event_id,'card_sha256':result['card_sha256'],'guard':'skipped','wallet_loaded':False,'served_publicly_verified':False}

def apply_verified_stage(*,root,official,stage_directory,origin,original_view_raw,fresh_view_raw,before_card_raw,policy_anchors,allow_apply=False):
    root=Path(root);verify_bundles(root)
    if not isinstance(origin,StageOrigin):raise ValueError('live same-run StageOrigin required')
    raw,mtime=read_regular(Path(stage_directory)/(origin.record_id+'.json'))
    if raw!=origin.record_raw or mtime!=origin.mtime_ns:raise ValueError('same-run stage changed')
    if read(root/'card.json')!=before_card_raw:raise ValueError('current card changed')
    current=head(root)
    if current is not None:raise ValueError('first-apply canary requires no committed head')
    authority=make_authority(origin,original_view_raw,fresh_view_raw,before_card_raw,policy_anchors,current,int(time.time()))
    if not allow_apply:return {'status':'dry','record_id':origin.record_id,'authority_lifetime_seconds':authority['valid_until']-authority['issued_at'],'writes_performed':False}
    with exclusive(root):
        if head(root)!=current or read(root/'card.json')!=before_card_raw:raise ValueError('baseline changed before authority')
        inputs=root/'host_inputs';protected(inputs,True)
        immutable(root/'card_update_stage'/(origin.record_id+'.json'),origin.record_raw,origin.mtime_ns)
        immutable(inputs/'card_offer_original'/(sha(original_view_raw)+'.json'),original_view_raw)
        immutable(inputs/'card_offer_fresh'/(sha(fresh_view_raw)+'.json'),fresh_view_raw)
        # Recompute only the existing host binding/TTL helper at issuance time.
        authority=make_authority(origin,original_view_raw,fresh_view_raw,before_card_raw,policy_anchors,current,int(time.time()))
        atomic_host(inputs/'card_publication_authority.json',encode(authority))
    # Ordinary call honestly updates its own usage index; no index is invented.
    return finish(root,official,toolbox(root,official).call('apply_staged_card',{'op':'apply','record_id':origin.record_id}),{'applied','already_applied'})

def rollback_current(*,root,official,event_id,allow_rollback=False):
    root=Path(root);verify_bundles(root)
    with exclusive(root):
        current,event=committed(root,event_id)
        if event['op']!='apply' or event['previous_active'] is not None:raise ValueError('only reviewed first-apply rollback is allowed')
        backup=event['before_card_json'].encode()
        if sha(backup)!=event['before_sha256']:raise ValueError('rollback backup mismatch')
        now=int(time.time())
        authority={'schema':'outseop-r4.card-publication-authority.v1','shop':'outseop-r4','owner':'native','op':'rollback','record_id':event_id,'head':current,'before_sha256':event['after_sha256'],'after_sha256':event['before_sha256'],'issued_at':now,'valid_until':now+30,'details':{}}
        if not allow_rollback:return {'status':'dry_rollback','event':current,'backup_sha256':sha(backup),'writes_performed':False}
        atomic_host(root/'host_inputs/card_publication_authority.json',encode(authority))
    return finish(root,official,toolbox(root,official).call('apply_staged_card',{'op':'rollback','record_id':event_id}),{'rolled_back','already_rolled_back'})
