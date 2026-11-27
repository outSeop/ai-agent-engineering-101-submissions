"""Root-only fixed old-edge to semantic-edge transition. Default inspect; never starts/stops services."""
import argparse,hashlib,json,os,shlex,sqlite3,subprocess,time
from pathlib import Path
import httpx
OP=Path('/home/seop/.local/share/ourolabs-r4-checkout/submissions/26510122/r4-operator')
COMMENT='codex-r4-front-edge-v1'
BASE=['-s','127.0.0.1/32','-d','127.0.0.1/32','-p','tcp','-m','tcp','--dport','18805','-m','owner','--uid-owner','1000','-m','comment','--comment',COMMENT,'-j','REDIRECT','--to-ports']
OLD_PORT='18807';NEW_PORT='18808';OLD_MARKER='r4-semantic-front-v1';NEW_MARKER='r4-semantic3-front-v1'
IPTABLES='/usr/sbin/iptables'
def run(args,**kw):return subprocess.run(args,capture_output=True,text=True,**kw)
def verify_package(pin):
 folder=Path(__file__).resolve().parent;raw=(folder/'MANIFEST.json').read_bytes()
 if hashlib.sha256(raw).hexdigest()!=pin:raise ValueError('unreviewed transition package')
 for n,h in json.loads(raw)['files'].items():
  p=folder/Path(n)
  if Path(n).is_absolute() or '..' in Path(n).parts or p.resolve()!=p or hashlib.sha256(p.read_bytes()).hexdigest()!=h:raise ValueError('transition package drift')
def verify_original_front():
 folder=OP/'deploy/front_semantic3_edge_runtime_v1';raw=(folder/'MANIFEST.json').read_bytes()
 if hashlib.sha256(raw).hexdigest()!='25d099830f88215ffebc37c41fd9cef8c3a28d0206f411ab9488c646a62980d9':raise ValueError('original_front_manifest_drift')
 for name,digest in json.loads(raw)['files'].items():
  path=folder/Path(name)
  if Path(name).is_absolute() or '..' in Path(name).parts or path.resolve()!=path or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('original_front_source_drift')
def chain():
 r=run([IPTABLES,'-w','3','-t','nat','-S','OUTPUT'])
 if r.returncode:raise ValueError('cannot inspect OUTPUT')
 lines=[shlex.split(x) for x in r.stdout.splitlines() if x.strip()]
 if len(lines)!=2 or lines[0]!=['-P','OUTPUT','ACCEPT']:raise ValueError('OUTPUT must contain exactly the reviewed own rule')
 for port in (OLD_PORT,NEW_PORT):
  if lines[1]==['-A','OUTPUT',*BASE,port]:return port
 raise ValueError('OUTPUT own rule selectors/comment drifted')
def replace(expected,target):
 if expected not in (OLD_PORT,NEW_PORT) or target not in (OLD_PORT,NEW_PORT) or expected==target:raise ValueError('invalid fixed transition')
 if chain()!=expected:raise ValueError('expected old rule changed')
 r=run([IPTABLES,'-w','3','-t','nat','-R','OUTPUT','1',*BASE,target])
 if r.returncode:raise ValueError('exact rule replacement failed')
 if chain()!=target:raise ValueError('post replacement chain differs; inspect without broad rollback')
def pid_alive(pid):
 p=Path('/proc')/str(pid)
 return p.exists() and p.stat().st_uid==1000

def service_pid():
 r=run(['/usr/sbin/runuser','-u','seop','--','env','XDG_RUNTIME_DIR=/run/user/1000','DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus','systemctl','--user','show','ourolabs-market-r4.service','-p','MainPID','--value'])
 if r.returncode or not r.stdout.strip().isdigit():raise ValueError('original user service PID unavailable')
 return int(r.stdout.strip())
def preserve_processes(main_pid,old_edge_pid,legacy_edge_pid):
 if service_pid()!=main_pid or not all(pid_alive(x) for x in (main_pid,old_edge_pid,legacy_edge_pid)):raise ValueError('preserved main/edge PID changed')
 for pid,suffix,port in ((old_edge_pid,b'/front_semantic_edge_runtime_v2/run_front_edge.py',b'18807'),(legacy_edge_pid,b'/front_edge_runtime_v3/run_front_edge.py',b'18806')):
  command=(Path('/proc')/str(pid)/'cmdline').read_bytes().split(b'\0')
  if not any(x.endswith(suffix) for x in command) or port not in command:raise ValueError('preserved edge command mismatch')
def pending_matches(url):
 p=OP.parent/'round-4/state/r4-benefits/benefits.sqlite3'
 with sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=3) as db:
  db.execute('PRAGMA query_only=ON');rows=db.execute("SELECT shop_url FROM sale WHERE status IN ('issued','cancel_requested','paid','missing')").fetchall()
 return all(r[0].rstrip('/')==url.rstrip('/') for r in rows)
def card(url,*,timeout=10):
 local=any(url.startswith('http://127.0.0.1:'+port+'/') for port in ('18805','18806','18807','18808'))
 transport=httpx.HTTPTransport(local_address='127.0.0.2' if local else None,retries=0)
 with httpx.Client(transport=transport,trust_env=False,follow_redirects=False,timeout=timeout) as c:
  r=c.get(url);r.raise_for_status();return r.json(),dict(r.headers)
IDENTITY_KEYS=('name','roles','wallets','supportedInterfaces')
class CardDescriptionChanged(ValueError):pass
def equal_identity(a,b):return all(a.get(k)==b.get(k) for k in IDENTITY_KEYS)
def equal_card(a,b):return equal_identity(a,b) and a.get('description')==b.get('description')
def identities(url,*,include_new=True,deadline=None):
 def read(port):
  timeout=10 if deadline is None else min(3,deadline-time.monotonic())
  if timeout<=0:raise ValueError('public_postcheck_deadline')
  return card('http://127.0.0.1:'+str(port)+'/.well-known/agent-card.json',timeout=timeout)
 origin,_=read(18805);old,oh=read(18807);legacy,lh=read(18806)
 observed=[old,legacy]
 if include_new:
  new,nh=read(18808);observed.append(new)
  if nh.get('x-r4-edge')!=NEW_MARKER:raise ValueError('new_local_marker_mismatch')
 if origin.get('name')!='outseop-r4' or any(not equal_identity(origin,x) for x in observed) or oh.get('x-r4-edge')!=OLD_MARKER or lh.get('x-r4-edge')!='r4-front-v1':raise ValueError('local_identity_or_marker_mismatch')
 interfaces=origin.get('supportedInterfaces')
 if not isinstance(interfaces,list) or len(interfaces)!=1 or interfaces[0].get('url','').rstrip('/')!=url.rstrip('/'):raise ValueError('original_public_URL_drift')
 if not pending_matches(url):raise ValueError('pending_checkout_URL_drift')
 if deadline is not None and time.monotonic()>=deadline:raise ValueError('public_postcheck_deadline')
 if any(not equal_card(origin,x) for x in observed):raise CardDescriptionChanged('local_card_description_changed')
 return origin

def idle10():
 start=None;deadline=time.monotonic()+40;samples=0
 while time.monotonic()<deadline:
  r=run(['ss','-Htn','( sport = :18805 or dport = :18805 or sport = :18806 or dport = :18806 or sport = :18807 or dport = :18807 )'])
  if r.returncode:raise ValueError('cannot observe origin/old-edge sockets')
  samples+=1
  if r.stdout.strip():start=None
  elif start is None:start=time.monotonic()
  elif time.monotonic()-start>=10:return samples
  time.sleep(.5)
 raise ValueError('continuous10second origin and old-edge idle not observed')
def public_matches(url,origin,marker):
 if marker not in (OLD_MARKER,NEW_MARKER):raise ValueError('unknown_expected_marker')
 deadline=time.monotonic()+20;description_refreshes=0;old_marker_waits=0
 for attempt in range(1,4):
  try:current=identities(url,include_new=marker==NEW_MARKER,deadline=deadline)
  except CardDescriptionChanged:
   description_refreshes+=1
   if attempt==3:raise ValueError('local_card_description_unstable') from None
   continue
  if not equal_identity(origin,current):raise ValueError('current_original_identity_changed')
  left=deadline-time.monotonic()
  if left<=0:raise ValueError('public_postcheck_deadline')
  actual,h=card(url.rstrip('/')+'/.well-known/agent-card.json',timeout=min(3,left))
  if time.monotonic()>=deadline:raise ValueError('public_postcheck_deadline')
  if not equal_identity(origin,actual):raise ValueError('public_identity_changed')
  if not pending_matches(url):raise ValueError('pending_checkout_URL_drift')
  if time.monotonic()>=deadline:raise ValueError('public_postcheck_deadline')
  observed=h.get('x-r4-edge')
  if observed!=marker:
   if observed not in (OLD_MARKER,NEW_MARKER):raise ValueError('unexpected_public_marker')
   if attempt==3 or deadline-time.monotonic()<6:raise ValueError('public_marker_not_converged')
   # Never accept the old marker. Allow the original 5s keepalive to become idle.
   old_marker_waits+=1;time.sleep(6);continue
  if equal_card(current,actual):return {'attempts':attempt,'description_refreshes':description_refreshes,'old_marker_waits':old_marker_waits,'current_description_matches':True,'strict_identity_URL_pending_match':True}
  description_refreshes+=1
  if attempt==3:raise ValueError('public_card_description_unstable')
 raise ValueError('public_postcheck_exhausted')

def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--package-manifest-sha',required=True);p.add_argument('--expected-main-pid',type=int,required=True);p.add_argument('--expected-old-edge-pid',type=int,required=True);p.add_argument('--expected-legacy-edge-pid',type=int,required=True);p.add_argument('--expected-public-url',required=True);mode=p.add_mutually_exclusive_group();mode.add_argument('--apply',action='store_true');mode.add_argument('--rollback',action='store_true');a=p.parse_args(argv)
 verify_package(a.package_manifest_sha);verify_original_front()
 if os.geteuid()!=0 or OP.stat().st_uid!=1000:raise ValueError('root and fixed owner required')
 if not a.expected_public_url.startswith('https://'):raise ValueError('HTTPS original URL required')
 preserve_processes(a.expected_main_pid,a.expected_old_edge_pid,a.expected_legacy_edge_pid);port=chain()
 if a.rollback:
  if port==OLD_PORT:print(json.dumps({'status':'already_preserved_semantic2_rule','process_changes':0}));return
  origin,_=card('http://127.0.0.1:18805/.well-known/agent-card.json');old,h=card('http://127.0.0.1:18807/.well-known/agent-card.json')
  if not equal_card(origin,old) or h.get('x-r4-edge')!=OLD_MARKER or not pending_matches(a.expected_public_url) or [x.get('url','').rstrip('/') for x in origin.get('supportedInterfaces',[])]!=[a.expected_public_url.rstrip('/')]:raise ValueError('rollback original identity mismatch')
  replace(NEW_PORT,OLD_PORT);public_matches(a.expected_public_url,origin,OLD_MARKER);print(json.dumps({'status':'rolled_back_to_preserved18807','original_rule_comment_selectors_preserved':True,'process_changes':0}));return
 origin=identities(a.expected_public_url)
 if not a.apply:print(json.dumps({'status':'inspected_only','current_rule_target':int(port),'cards_URL_pending_match':True,'process_changes':0}));return
 if port==NEW_PORT:public_matches(a.expected_public_url,origin,NEW_MARKER);print(json.dumps({'status':'already_semantic_rule'}));return
 samples=idle10();preserve_processes(a.expected_main_pid,a.expected_old_edge_pid,a.expected_legacy_edge_pid);origin=identities(a.expected_public_url)
 replace(OLD_PORT,NEW_PORT)
 try:postcheck=public_matches(a.expected_public_url,origin,NEW_MARKER)
 except Exception:
  # Only reverse the exact still-owned new rule. Never flush/kill/reset connections.
  replace(NEW_PORT,OLD_PORT);raise
 print(json.dumps({'status':'replaced_exact_rule_public_marker_verified','idle_samples':samples,'postcheck':postcheck,'main_and_old_edge_unchanged':True,'same_URL_wallet_pending':True,'original_comment_UID_selectors_preserved':True,'process_registry_DB_wallet_changes':0}))
if __name__=='__main__':main()
