"""Root-review helper. Default inspect only; exact one-rule apply/rollback opt-ins."""
import argparse,hashlib,json,os,shutil,stat,subprocess,time,urllib.request,sqlite3
from pathlib import Path
OP=Path('/home/seop/.local/share/ourolabs-r4-checkout/submissions/26510122/r4-operator')
COMMENT='codex-r4-front-edge-v1'
SPEC=['-p','tcp','-s','127.0.0.1/32','-d','127.0.0.1/32','--dport','18805','-m','owner','--uid-owner','1000','-m','comment','--comment',COMMENT,'-j','REDIRECT','--to-ports','18806']
def run(args,**kwargs):return subprocess.run(args,capture_output=True,text=True,**kwargs)
def iptables():
 for path in ['/usr/sbin/iptables','/sbin/iptables']:
  if Path(path).is_file():return path
 raise ValueError('iptables unavailable; installation is a separate root approval action')
def verify_package(pin):
 if OP.stat().st_uid!=1000:raise ValueError('registered owner differs from fixed UID selector')
 folder=Path(__file__).resolve().parent;raw=(folder/'MANIFEST.json').read_bytes()
 if hashlib.sha256(raw).hexdigest()!=pin:raise ValueError('unreviewed route package')
 for name,digest in json.loads(raw)['files'].items():
  p=folder/Path(name)
  if Path(name).is_absolute() or '..' in Path(name).parts or p.resolve()!=p or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:raise ValueError('route package drift')
def exists(binary):
 r=run([binary,'-t','nat','-C','OUTPUT',*SPEC])
 if r.returncode not in (0,1):raise ValueError('cannot inspect exact rule')
 return r.returncode==0
def idle10():
 start=None;end=time.monotonic()+40;samples=0
 while time.monotonic()<end:
  r=run(['ss','-Htn','( sport = :18805 or dport = :18805 )'])
  if r.returncode:raise ValueError('socket inspection unavailable')
  rows=[x for x in r.stdout.splitlines() if x.strip()];samples+=1
  if rows:start=None
  elif start is None:start=time.monotonic()
  elif time.monotonic()-start>=10:return samples
  time.sleep(.5)
 raise ValueError('continuous10second origin idle not observed')
def card(url):
 opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
 with opener.open(url,timeout=12) as r:return json.loads(r.read()),dict((k.lower(),v) for k,v in r.headers.items())
def service_pid():
 env=dict(os.environ,XDG_RUNTIME_DIR='/run/user/1000',DBUS_SESSION_BUS_ADDRESS='unix:path=/run/user/1000/bus')
 r=run(['systemctl','--user','show','ourolabs-market-r4.service','-p','MainPID','--value'],env=env)
 # Inspect only the explicit original user's bus; never operate on root's own user manager.
 if r.returncode or not r.stdout.strip().isdigit():raise ValueError('original user service PID unavailable; use preserved user bus environment')
 return int(r.stdout.strip())
def pending_matches(url):
 path=OP.parent/'round-4/state/r4-benefits/benefits.sqlite3'
 with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=3) as db:
  db.execute('PRAGMA query_only=ON')
  rows=db.execute("SELECT shop_url FROM sale WHERE status IN ('issued','cancel_requested','paid','missing')").fetchall()
 return all(row[0].rstrip('/')==url.rstrip('/') for row in rows)
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--package-manifest-sha',required=True);p.add_argument('--expected-main-pid',type=int,required=True);p.add_argument('--expected-public-url',required=True);mode=p.add_mutually_exclusive_group();mode.add_argument('--apply',action='store_true');mode.add_argument('--rollback',action='store_true');a=p.parse_args();verify_package(a.package_manifest_sha)
 if os.geteuid()!=0:raise ValueError('root inspection/action required')
 binary=iptables()
 if a.rollback:
  if exists(binary):
   r=run([binary,'-t','nat','-D','OUTPUT',*SPEC])
   if r.returncode:raise ValueError('exact rollback failed')
  print(json.dumps({'status':'rolled_back_exact_rule','rule_absent':not exists(binary),'process_or_registry_changes':0}));return
 if service_pid()!=a.expected_main_pid:raise ValueError('original main PID changed')
 old,oldh=card('http://127.0.0.1:18805/.well-known/agent-card.json');edge,edgeh=card('http://127.0.0.1:18806/.well-known/agent-card.json')
 if old.get('name')!='outseop-r4' or any(old.get(k)!=edge.get(k) for k in ['name','description','roles','wallets','supportedInterfaces']) or edgeh.get('x-r4-edge')!='r4-front-v1':raise ValueError('direct edge/current card mismatch')
 interface=(old.get('supportedInterfaces') or [{}])[0].get('url','').rstrip('/')
 if interface!=a.expected_public_url.rstrip('/'):raise ValueError('original public URL changed')
 if not pending_matches(a.expected_public_url):raise ValueError('pending original checkout URL mismatch')
 rule=exists(binary)
 if not a.apply:print(json.dumps({'status':'inspected_only','exact_rule_present':rule,'same_old_edge_card':True,'Model_join_process_registry_changes':0}));return
 if rule:print(json.dumps({'status':'already_installed_exact_rule'}));return
 current=run([binary,'-t','nat','-S','OUTPUT'])
 if current.returncode:raise ValueError('cannot inspect existing OUTPUT rules')
 if any('--dport 18805' in line and COMMENT not in line for line in current.stdout.splitlines()):raise ValueError('another rule addresses original port')
 samples=idle10()
 if service_pid()!=a.expected_main_pid:raise ValueError('original PID changed during drain')
 r=run([binary,'-t','nat','-I','OUTPUT','1',*SPEC])
 if r.returncode:raise ValueError('exact rule insertion failed')
 try:
  actual,headers=card(a.expected_public_url.rstrip('/')+'/.well-known/agent-card.json')
  if not pending_matches(a.expected_public_url):raise ValueError('pending URL changed during transition')
  if headers.get('x-r4-edge')!='r4-front-v1' or any(actual.get(k)!=old.get(k) for k in ['name','roles','wallets']):raise ValueError('public edge path unverified')
 except Exception:
  run([binary,'-t','nat','-D','OUTPUT',*SPEC]);raise
 print(json.dumps({'status':'applied_exact_rule_public_marker_verified','origin_idle_samples':samples,'old_main_PID_unchanged':service_pid()==a.expected_main_pid,'one_exact_rule_present':exists(binary),'process_registry_DB_wallet_changes':0}))
if __name__=='__main__':main()
