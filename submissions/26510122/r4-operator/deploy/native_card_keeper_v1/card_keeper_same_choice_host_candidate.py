"""Uninstalled same-choice Card keeper. Default plan only; root owns invocation/timer.

Only the existing pinned producer reads live inventory/catalog/ledger. This host
never chooses a SKU, reprices, renders, uses Model inference or loads wallets.
"""
import argparse,fcntl,json,os,re,stat,sys,tempfile,time
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path

HERE=Path(__file__).resolve().parent
HELPERS=HERE.parent/'codex-r4'
if not HELPERS.is_dir():HELPERS=HERE
PIN_FILE=HERE/'card_keeper_native_pins.json'
PIN_FILE_SHA='4602ed931ad01c04b75fce0ea8e7507bbb1f3351a096339ca84b78d938e22cfd'
def sha(raw):return sha256(raw).hexdigest()
pin_info=PIN_FILE.lstat()
if PIN_FILE.resolve()!=PIN_FILE or not stat.S_ISREG(pin_info.st_mode) or pin_info.st_uid!=os.getuid() or pin_info.st_nlink!=1 or pin_info.st_mode&0o022:raise RuntimeError('unprotected keeper pin manifest')
if sha(PIN_FILE.read_bytes())!=PIN_FILE_SHA:raise RuntimeError('keeper pin manifest changed')
PINS=json.loads(PIN_FILE.read_bytes())

def helper_path(record):
    base=HERE if record['location']=='host' else HELPERS
    path=base/record['filename']
    if not path.is_file() and record['location']=='helpers':path=HELPERS.parent/record['filename']
    return path

def verify_helpers():
    for record in PINS['helpers'].values():
        path=helper_path(record)
        info=path.lstat()
        if path.resolve()!=path or not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1 or info.st_mode&0o022 or sha(path.read_bytes())!=record['sha256']:raise RuntimeError('keeper helper source changed')
verify_helpers()
sys.path[:0]=[str(HERE),str(HELPERS),str(HELPERS.parent)]
import card_offer_producer_host as producer
import card_apply_canary_host as files
from card_apply_authority_host import StageOrigin,normalized_fresh
from card_apply_v3_authority_host_candidate import make_refresh_authority

class NoWallet:
    def grant(self,name,permission,timeout):
        if name not in ('refresh_representative_card','apply_staged_card','publish_shop_info') or any(permission.get(k) for k in ('wallet','identity','network','exec','handles')):
            raise PermissionError('keeper has no wallet, token or network capability')
        return None

def verify_sources(root):
    files.protected(root,True)
    for relative,record in PINS['native_bundles'].items():
        directory=root/relative;files.protected(directory,True)
        if {path.name for path in directory.iterdir()}!=set(record['sha256']):raise RuntimeError('native tool directory is not exact four-file bundle')
        raw={name:files.read(directory/name) for name in record['sha256']}
        if any(sha(raw[name])!=pin for name,pin in record['sha256'].items()):raise RuntimeError('native source pin changed')
        manifest=json.loads(raw['forge.json'])
        if manifest['sha256']!={name:pin for name,pin in record['sha256'].items() if name!='forge.json'}:raise RuntimeError('native forge metadata changed')

def make_toolbox(root,official):
    return official.Toolbox(root,{'name':'outseop-r4','market':'https://market.ourolabs.ai','tokens':{},'addresses':{},'signer':NoWallet()})

@contextmanager
def oneshot(operator):
    runtime=operator/'runtime';files.protected(runtime,True)
    state=runtime/'card-keeper-native';state.mkdir(mode=0o700,exist_ok=True);files.protected(state,True)
    path=state/'oneshot.lock';fd=os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        files.protected(path);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if os.fstat(fd).st_ino!=path.stat().st_ino:raise RuntimeError('oneshot lock substituted')
        yield state
    finally:os.close(fd)

def snapshot(root,expected=None):
    with files.exclusive(root):
        event_id,event=files.committed(root)
        card=files.read(root/'card.json');head=files.read(root/'card_publication/head.json')
        eventraw=files.read(root/'card_publication'/(event_id+'.json'))
        viewraw=files.read(root/'host_inputs/card_offer_original'/(event['view_sha256']+'.json'))
        if sha(viewraw)!=event['view_sha256']:raise RuntimeError('active original view changed')
        if not isinstance(event.get('skus'),list) or not 1<=len(event['skus'])<=3:raise RuntimeError('active model selection unavailable')
        if expected is not None and (event_id!=expected['id'] or card!=expected['card']):raise RuntimeError('publication changed during read')
        return {'id':event_id,'event':event,'card':card,'head':head,'eventraw':eventraw,'viewraw':viewraw}

def result_only(envelope):
    if envelope.get('ok') is not True or not isinstance(envelope.get('result'),dict):raise RuntimeError('native tool envelope unavailable')
    return envelope['result']
def safe_reason(value):return value if isinstance(value,str) and re.fullmatch('[a-z][a-z0-9_]{0,100}',value) else 'native_result_unavailable'

def copy_shadow(root,job,active,viewraw):
    for relative,record in PINS['native_bundles'].items():
        directory=job/relative;directory.mkdir(parents=True)
        for name in record['sha256']:files.immutable(directory/name,files.read(root/relative/name))
    for name in ('host_inputs','card_update_stage','card_publication'):(job/name).mkdir(mode=0o700,exist_ok=True)
    (job/'card_publication/lock').touch(mode=0o600)
    files.immutable(job/'card.json',active['card'])
    files.immutable(job/'card_publication/head.json',active['head'])
    files.immutable(job/'card_publication'/(active['id']+'.json'),active['eventraw'])
    files.immutable(job/'host_inputs/card_offer_original'/(active['event']['view_sha256']+'.json'),active['viewraw'])
    files.immutable(job/'host_inputs/card_offer_context.json',viewraw)
    files.immutable(job/'native-source-reuse.json',files.encode({'source':'installed exact genuine bundles','new_forge_created':False,'native_bundles':PINS['native_bundles']}))

def get_policies(root,provided):
    if provided is not None:return dict(provided)
    authority=json.loads(files.read(root/'host_inputs/card_publication_authority.json'))
    # Reuse only previously reviewed wording; never reuse its expired authority.
    policies=authority.get('details',{}).get('policies')
    if not isinstance(policies,dict):raise RuntimeError('reviewed policy anchors unavailable')
    return dict(policies)

def cycle(root,job,official,policies,prepare_only):
    active=snapshot(root)
    _,observed,offers,catalog=producer.acquire(root)  # Existing pinned read-only authority only.
    snapshot(root,active)
    view=producer.produce_view(active['card'],active['event']['block']['text'],offers,catalog,observed)
    raw=files.encode(view);copy_shadow(root,job,active,raw)
    verify_sources(root);verify_helpers()
    started=time.time_ns();envelope=make_toolbox(job,official).call('refresh_representative_card',{'view_sha256':sha(raw)})
    staged=result_only(envelope)
    if staged.get('status')!='staged':
        reason=safe_reason(staged.get('error'))
        status='requires_class_selection' if reason in ('selected_offer_changed','selected_sku_not_sellable') else 'refresh_not_staged'
        return {'status':status,'reason':reason,'stage':'refresh','card_written':False}
    refresh_pin=PINS['native_bundles']['tools/refresh_representative_card']['sha256']['logic.py']
    origin=StageOrigin.capture(job/'card_update_stage',staged,raw,refresh_pin,started,active['event']['skus'])
    limit=time.monotonic()+2
    while int(time.time())*10**9<origin.mtime_ns:
        if time.monotonic()>=limit:raise RuntimeError('clock did not reach post-stage observation window')
        time.sleep(.02)
    fresh_start=time.time_ns();snapshot(root,active)
    _,fresh_observed,fresh_offers,fresh_catalog=producer.acquire(root)
    snapshot(root,active)
    record,mtime=read_stage(job,origin)
    if record!=origin.record_raw or mtime!=origin.mtime_ns:raise RuntimeError('same-run stage changed')
    fresh=producer.produce_view(active['card'],view['replace_text'],fresh_offers,fresh_catalog,fresh_observed)
    try:validated=normalized_fresh(origin,raw,fresh,active['card'],fresh_start)
    except ValueError as error:
        status='requires_class_selection' if str(error) in ('selected SKU unavailable','selected SKU changed') else 'fresh_recheck_rejected'
        return {'status':status,'reason':'fresh_terms_changed' if status=='requires_class_selection' else 'fresh_or_original_expired','stage':'fresh','card_written':False}
    freshraw=files.encode(validated)
    authority=make_refresh_authority(origin,raw,freshraw,active['card'],active['event'],active['id'],policies,int(time.time()))
    files.immutable(job/'host_inputs/card_offer_original'/(sha(raw)+'.json'),raw)
    files.immutable(job/'host_inputs/card_offer_fresh'/(sha(freshraw)+'.json'),freshraw)
    if prepare_only:return {'status':'prepared_only','record_id':origin.record_id,'card_written':False,'source_choice_unchanged':True}
    verify_sources(root);verify_helpers()
    with files.exclusive(root):
        current_id,event=files.committed(root)
        if current_id!=active['id'] or files.read(root/'card.json')!=active['card']:raise RuntimeError('publication changed before authority')
        files.immutable(root/'card_update_stage'/(origin.record_id+'.json'),origin.record_raw,origin.mtime_ns)
        files.immutable(root/'host_inputs/card_offer_original'/(sha(raw)+'.json'),raw)
        files.immutable(root/'host_inputs/card_offer_fresh'/(sha(freshraw)+'.json'),freshraw)
        authority=make_refresh_authority(origin,raw,freshraw,active['card'],active['event'],active['id'],policies,int(time.time()))
        files.atomic_host(root/'host_inputs/card_publication_authority.json',files.encode(authority))
    applied=result_only(make_toolbox(root,official).call('apply_staged_card',{'op':'apply','record_id':origin.record_id}))
    if applied.get('status') not in ('applied','already_applied'):
        return {'status':'native_pending_or_rejected','reason':safe_reason(applied.get('reason')),'stage':'apply','legacy_restore_attempted':False}
    with files.exclusive(root):
        event_id,event=files.committed(root,applied['event'])
        if event['skus']!=active['event']['skus']:raise RuntimeError('native choice changed')
        files.handoff_locked(root,event_id,event)
    guarded=result_only(make_toolbox(root,official).call('publish_shop_info',{}))
    if guarded.get('status')!='skipped' or guarded.get('event')!=event_id:raise RuntimeError('native handoff guard did not confirm')
    return {'status':applied['status'],'event':event_id,'card_sha256':applied['card_sha256'],'guard':'skipped','offer_until':event['offer_until'],
      'ttl_remaining_seconds':max(0,event['offer_until']-int(time.time())),'wallet_loaded':False,'wallet_operations_allowed':False,
      'orders_or_inventory_written':False,'source_choice_unchanged':True,'public_served_verified':False}

def read_stage(job,origin):
    from card_apply_authority_host import read_regular
    return read_regular(job/'card_update_stage'/(origin.record_id+'.json'))

def run_once(*,operator,allow_refresh=False,prepare_only=False,policy_anchors=None,official=None,_production=None):
    if allow_refresh and prepare_only:raise ValueError('choose prepare-only or explicit apply')
    operator=Path(operator).resolve(strict=True);root=operator.parent/'round-4' if _production is None else Path(_production)
    try:
        verify_helpers();verify_sources(root)
        if not allow_refresh and not prepare_only:
            active=snapshot(root)
            return {'status':'dry','event':active['id'],'card_sha256':sha(active['card']),'writes_performed':False,'producer_called':False}
        with oneshot(operator) as state:
            job=Path(tempfile.mkdtemp(prefix='run-',dir=state))
            if official is None:
                sys.path.insert(0,str(operator/'kit'));import agent_kit as official
            try:
                policies=get_policies(root,policy_anchors)
                result=cycle(root,job,official,policies,prepare_only)
            except Exception as error:
                result={'status':'read_or_recheck_unavailable','error_type':type(error).__name__,'legacy_restore_attempted':False,'card_reposted_from_cache':False}
            raw=files.encode(result);files.immutable(job/'receipt.json',raw)
            return dict(result,receipt_sha256=sha(raw))
    except BlockingIOError:return {'status':'busy','overlap_started':False}
    except Exception as error:return {'status':'source_or_publication_unavailable','error_type':type(error).__name__,'legacy_restore_attempted':False}

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--operator',required=True,type=Path)
    group=parser.add_mutually_exclusive_group();group.add_argument('--prepare-only',action='store_true');group.add_argument('--allow-refresh',action='store_true')
    parser.add_argument('--policy-anchors',type=Path)
    args=parser.parse_args(argv)
    anchors=json.loads(files.read(args.policy_anchors.absolute())) if args.policy_anchors else None
    result=run_once(operator=args.operator,allow_refresh=args.allow_refresh,prepare_only=args.prepare_only,policy_anchors=anchors)
    print(json.dumps(result));return result

if __name__=='__main__':main()
