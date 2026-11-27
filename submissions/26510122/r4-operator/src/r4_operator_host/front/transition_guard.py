"""Root-only fixed old-edge to semantic-edge transition. Default inspect; never starts/stops services."""
import argparse,hashlib,json,os,pwd,shlex,sqlite3,subprocess,time
from pathlib import Path
import httpx
from config import OP
OWNER_UID=OP.stat().st_uid
OWNER_NAME=pwd.getpwuid(OWNER_UID).pw_name
COMMENT='codex-r4-front-edge-v1'
BASE=['-s','127.0.0.1/32','-d','127.0.0.1/32','-p','tcp','-m','tcp','--dport','18805','-m','owner','--uid-owner',str(OWNER_UID),'-m','comment','--comment',COMMENT,'-j','REDIRECT','--to-ports']
CFG=None
OWN_MANIFEST_SHA=None
def configure(config,manifest_sha):
 global CFG,OWN_MANIFEST_SHA,OLD_PORT,NEW_PORT,OLD_MARKER,NEW_MARKER,OP,OWNER_UID,OWNER_NAME
 OP=config.operator_root or OP;OWNER_UID=OP.stat().st_uid;OWNER_NAME=pwd.getpwuid(OWNER_UID).pw_name
 BASE[BASE.index('--uid-owner')+1]=str(OWNER_UID)
 CFG=config;OWN_MANIFEST_SHA=manifest_sha;OLD_PORT=str(config.old_proxy_port);NEW_PORT=str(config.new_port);OLD_MARKER=config.old_marker;NEW_MARKER=config.marker
IPTABLES='/usr/sbin/iptables'
def run(args,**kw):return subprocess.run(args,capture_output=True,text=True,**kw)
def verify_package(pin):
 folder=Path(__file__).resolve().parent;raw=(folder/'MANIFEST.json').read_bytes()
 if hashlib.sha256(raw).hexdigest()!=pin:raise ValueError('unreviewed transition package')
 for n,h in json.loads(raw)['files'].items():
  p=folder/Path(n)
  if Path(n).is_absolute() or '..' in Path(n).parts or p.resolve()!=p or hashlib.sha256(p.read_bytes()).hexdigest()!=h:raise ValueError('transition package drift')
def verify_preserved_fronts():
 for edge in CFG.edges:
  folder=edge.manifest_path.parent;content=edge.manifest_path.read_bytes()
  if edge.manifest_path.resolve()!=edge.manifest_path or hashlib.sha256(content).hexdigest()!=edge.manifest_sha256:raise ValueError('preserved front manifest drift')
  for name,pin in json.loads(content)['files'].items():
   path=folder/Path(name)
   if Path(name).is_absolute() or '..' in Path(name).parts or path.resolve()!=path or hashlib.sha256(path.read_bytes()).hexdigest()!=pin:raise ValueError('preserved front source drift')
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
 return p.exists() and p.stat().st_uid==OWNER_UID

def service_pid(unit):
 if CFG is None or unit not in CFG.services:raise ValueError('unexpected preserved unit')
 r=run(['/usr/sbin/runuser','-u',OWNER_NAME,'--','env','XDG_RUNTIME_DIR=/run/user/'+str(OWNER_UID),'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/'+str(OWNER_UID)+'/bus','systemctl','--user','show',unit,'-p','MainPID','--value'])
 if r.returncode or not r.stdout.strip().isdigit():raise ValueError('original user service PID unavailable')
 return int(r.stdout.strip())
def preserve_processes(new_edge_pid):
 roles=(CFG.main,CFG.worker,*CFG.edges)
 if any(service_pid(role.service)!=role.pid_hint or not pid_alive(role.pid_hint) for role in roles) or service_pid(CFG.service)!=new_edge_pid or not pid_alive(new_edge_pid) or not pid_alive(CFG.cf_pid_hint):raise ValueError('preserved process changed')
 for edge in CFG.edges:
  command=(Path('/proc')/str(edge.pid_hint)/'cmdline').read_bytes().split(b'\0')
  if str(edge.launcher).encode() not in command:raise ValueError('old exact launcher changed')
  if b'--port' in command:
   if command[command.index(b'--port')+1]!=str(edge.port).encode():raise ValueError('old port changed')
  else:
   metadata=json.loads(edge.manifest_path.read_bytes());path=edge.launcher.parent/'RUNTIME-BINDING.json'
   if hashlib.sha256(path.read_bytes()).hexdigest()!=metadata['files'].get('RUNTIME-BINDING.json') or json.loads(path.read_bytes()).get('new_port')!=edge.port:raise ValueError('old manifest-bound port changed')
 new_command=(Path('/proc')/str(new_edge_pid)/'cmdline').read_bytes().split(b'\0');launcher=Path(__file__).resolve().parent/'run_front_edge.py'
 if str(launcher).encode() not in new_command or b'--edge-manifest-sha' not in new_command or new_command[new_command.index(b'--edge-manifest-sha')+1]!=OWN_MANIFEST_SHA.encode():raise ValueError('new exact launcher/manifest changed')
 cf=(Path('/proc')/str(CFG.cf_pid_hint)/'cmdline').read_bytes().split(b'\0')
 if b'cloudflared' not in cf[0].split(b'/') or b'http://127.0.0.1:18805' not in cf:raise ValueError('original quick tunnel changed')
def admission():
 import importlib.util
 path=Path(__file__).resolve().parent/'admission_gate.py';spec=importlib.util.spec_from_file_location('verified_front_admission',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 return m.AdmissionGate(OP/CFG.state_dir/'admission.json')
def pending_matches(url):
 p=OP.parent/'round-4/state/r4-benefits/benefits.sqlite3'
 with sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=3) as db:
  db.execute('PRAGMA query_only=ON');rows=db.execute("SELECT shop_url FROM sale WHERE status IN ('issued','cancel_requested','paid','missing')").fetchall()
 return all(r[0].rstrip('/')==url.rstrip('/') for r in rows)
def card(url,*,timeout=10):
 local=any(url.startswith('http://127.0.0.1:'+str(port)+'/') for port in CFG.card_ports)
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
 origin,_=read(18805);observed=[]
 for edge in CFG.edges:
  old,headers=read(edge.port);observed.append(old)
  if headers.get('x-r4-edge')!=edge.marker:raise ValueError('preserved local marker changed')
 if include_new:
  new,headers=read(CFG.new_port);observed.append(new)
  if headers.get('x-r4-edge')!=NEW_MARKER:raise ValueError('new_local_marker_mismatch')
 if origin.get('name')!='outseop-r4' or any(not equal_identity(origin,x) for x in observed):raise ValueError('local_identity_mismatch')
 interfaces=origin.get('supportedInterfaces')
 if not isinstance(interfaces,list) or len(interfaces)!=1 or interfaces[0].get('url','').rstrip('/')!=url.rstrip('/'):raise ValueError('original_public_URL_drift')
 if not pending_matches(url):raise ValueError('pending_checkout_URL_drift')
 if deadline is not None and time.monotonic()>=deadline:raise ValueError('public_postcheck_deadline')
 if any(not equal_card(origin,x) for x in observed):raise CardDescriptionChanged('local_card_description_changed')
 return origin

def idle10():
 start=None;deadline=time.monotonic()+40;samples=0
 while time.monotonic()<deadline:
  r=run(['ss','-Htn','( '+' or '.join('sport = :'+str(port)+' or dport = :'+str(port) for port in CFG.idle_ports)+' )'])
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

def guarded_apply(url,preserve,gate):
 gate.require_pristine_closed();preserve();origin=identities(url)
 samples=idle10();preserve();origin=identities(url)
 replace(OLD_PORT,NEW_PORT)
 try:
  postcheck=public_matches(url,origin,NEW_MARKER);preserve();gate.open_if_pristine()
 except Exception:
  gate.require_pristine_closed();replace(NEW_PORT,OLD_PORT);raise
 return {'status':'exact_new_rule_verified_and_first_task_gate_open','idle_samples':samples,'postcheck':postcheck,'process_changes':0}
def guarded_rollback(url,preserve,gate):
 preserve();gate.close();gate.require_pristine_closed();origin=identities(url,include_new=False)
 replace(NEW_PORT,OLD_PORT);public_matches(url,origin,OLD_MARKER)
 return {'status':'reversed_exact_rule_with_zero_new_task_admissions','new_task_gate_closed':True,'process_changes':0}
def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--package-manifest-sha',required=True);p.add_argument('--sources-only',action='store_true');p.add_argument('--expected-new-edge-pid',type=int);p.add_argument('--expected-public-url');mode=p.add_mutually_exclusive_group();mode.add_argument('--apply',action='store_true');mode.add_argument('--rollback',action='store_true');a=p.parse_args(argv)
 verify_package(a.package_manifest_sha)
 import importlib.util,sys
 folder=Path(__file__).resolve().parent;spec=importlib.util.spec_from_file_location('verified_front_config',folder/'config.py');module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
 meta=json.loads((folder/'MANIFEST.json').read_bytes());config=module.load_pinned(folder,meta);configure(config,a.package_manifest_sha);verify_preserved_fronts()
 if a.sources_only:
  if a.apply or a.rollback:raise ValueError('sources-only forbids operations')
  print(json.dumps({'status':'sources_verified_only','service_rule_gate_wallet_actions':0}));return
 if meta.get('sources_only'):raise ValueError('preliminary package cannot activate')
 if os.geteuid()!=0 or OP.stat().st_uid!=OWNER_UID or type(a.expected_new_edge_pid) is not int or a.expected_new_edge_pid<=0 or not a.expected_public_url or not a.expected_public_url.startswith('https://'):raise ValueError('fixed root/owner/new PID/HTTPS required')
 preserve=lambda:preserve_processes(a.expected_new_edge_pid)
 preserve();port=chain();gate=admission()
 if a.rollback:
  if port==OLD_PORT:gate.close();gate.require_pristine_closed();print(json.dumps({'status':'already_old_rule_and_pristine_gate','process_changes':0}));return
  print(json.dumps(guarded_rollback(a.expected_public_url,preserve,gate)));return
 origin=identities(a.expected_public_url)
 if not a.apply:
  state=gate.read();print(json.dumps({'status':'inspected_only','rule_target':int(port),'gate_open':state['open'],'new_task_admissions':state['admissions'],'process_changes':0}));return
 if port==NEW_PORT:
  state=gate.read()
  if not state['open']:raise ValueError('existing new rule closed; explicit forward recovery required')
  public_matches(a.expected_public_url,origin,NEW_MARKER);print(json.dumps({'status':'already_new_rule_open','process_changes':0}));return
 print(json.dumps(guarded_apply(a.expected_public_url,preserve,gate)))
if __name__=='__main__':main()
