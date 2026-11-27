"""Distinct safer deployment: requested product-interest recording on the EXISTING cache timer.
No new service/timer/loop. Previous standalone observer activation was rejected and is not retried.
User request: record incoming product requests and use them for profitable future purchasing.
This script ONLY installs a no-wallet recorder and bounded ignore-failure post-hook; no purchases/Model/policy.
"""
from pathlib import Path
from hashlib import sha256
import json,os,shutil,subprocess,time,argparse,sqlite3,re,shlex
OP=Path('/home/seop/.local/share/ourolabs-r4-checkout/submissions/26510122/r4-operator');ROOT=OP.parent/'round-4';STATE=Path(__file__).parent
REC=OP/'deploy/request_feedback_native_v4';RECPIN='c64c8dcc8420942e70ef262b69f4965f5b1dbfcf228fd5ab6c19aca013482174';FORGEPIN='17efbe8ee7e91a02b021937c4ee24924c2ec51de2bfbc71dbe19eb11220a5bf0'
HOST=OP/'deploy/procurement_demand_once_host_v4';HOSTPIN='5f6682139d791d4b475e85891460b5ff0a9285cd0b75a520ab7b62cb6ed95774'
CACHE='ourolabs-market-r4-customer-context.service';TIMER='ourolabs-market-r4-customer-context.timer';DROP=Path.home()/'.config/systemd/user'/f'{CACHE}.d/95-request-feedback-once.conf'
EXPECTED_ARGV=[str(OP/'.venv/bin/python'),'-I','-B',str(OP/'deploy/price_context_runtime_v8a/price_context_bootstrap.py'),'catalogue','--','--operator',str(OP),'--manifest-sha256','ffa36c8557ecea6f53a7e9ac7271fa598565fd898f1f5d966444bc34a3f808cc','--publish-cache']
def static_command(value):
 paths=re.findall(r'path=([^;]+)',value);commands=re.findall(r'argv\[\]=([^;]+)',value)
 if len(paths)!=1 or len(commands)!=1:raise ValueError('ambiguous cache executable')
 return paths[0].strip(),shlex.split(commands[0])
def verify(folder,pin):
 raw=(folder/'MANIFEST.json').read_bytes()
 if sha256(raw).hexdigest()!=pin:raise ValueError('package manifest drift')
 for n,h in json.loads(raw)['files'].items():
  rel=Path(n);q=folder/rel
  if rel.is_absolute() or '..' in rel.parts or q.resolve()!=q or sha256(q.read_bytes()).hexdigest()!=h:raise ValueError('package source drift')
def ctl(*a):return subprocess.check_output(['systemctl','--user',*a],text=True).strip()
def property(name):return ctl('show',CACHE,'-p',name,'--value')
def snapshots(names):return {n:ctl('show',n,'--property=MainPID,NRestarts,ActiveState') for n in names}
def native(folder):
 raw=(folder/'forge.json').read_bytes()
 if sha256(raw).hexdigest()!=FORGEPIN:raise ValueError('native source not reviewed')
 for n,h in json.loads(raw)['sha256'].items():
  if sha256((folder/n).read_bytes()).hexdigest()!=h:raise ValueError('native files drift')
def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--apply-existing-timer',action='store_true');args=parser.parse_args();os.umask(0o077)
 if os.getuid()!=1000:raise ValueError('registered local user only')
 verify(REC,RECPIN);verify(HOST,HOSTPIN);b=json.loads((STATE/'before-private.json').read_text());before=snapshots(b['services'])
 if before!=b['services']:raise ValueError('original services changed')
 if sha256((ROOT/'tools/stock_procurement/logic.py').read_bytes()).hexdigest()!=b['stock8']['logic.py']['sha256']:raise ValueError('stock8 changed')
 for n,v in b['wallets'].items():
  q=ROOT/n;st=q.stat()
  if (st.st_dev,st.st_ino,sha256(q.read_bytes()).hexdigest())!=(v['device'],v['inode'],v['sha256']):raise ValueError('wallet changed')
 with sqlite3.connect((ROOT/'state/r4-benefits/benefits.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
  db.row_factory=sqlite3.Row;db.execute('pragma query_only=on');pending=[dict(x) for x in db.execute("select * from sale where status not in ('settled','cancelled','refunded','expired')")]
  if pending!=b['pending']:raise ValueError('pending sale changed')
 start=property('ExecStart')
 if static_command(start)!=(EXPECTED_ARGV[0],EXPECTED_ARGV) or property('Type')!='oneshot' or TIMER not in property('TriggeredBy'):raise ValueError('existing cache unit drift')
 if ctl('is-active',TIMER)!='active':raise ValueError('existing timer inactive')
 text=(HOST/'cache-observer-once.conf.template').read_text()
 for k,v in {'@OBSERVER_BUNDLE@':str(HOST),'@OBSERVER_SHA@':HOSTPIN,'@RECORDER_FORGE_SHA@':FORGEPIN}.items():text=text.replace(k,v)
 if '@' in text or 'ExecStart=' in text or '--run' in text:raise ValueError('unexpected posthook')
 if DROP.is_symlink() or (DROP.exists() and DROP.read_text()!=text):raise ValueError('different preexisting drop-in')
 post=property('ExecStartPost')
 if post and (not DROP.exists() or str(HOST/'run_observer.py') not in post):raise ValueError('unreviewed existing posthook')
 target=ROOT/'tools/record_stock_request'
 if target.exists():native(target)
 plan={'status':'verified_only','new_daemon_service_timer_or_autonomous_loop':False,'original_cache_ExecStart_unchanged':True,'bounded_post_seconds':20,'post_kill_grace_seconds':1,'post_failure_ignored':True,'aggregate_unit_timeout_seconds':55,'original_five_services_wallet_pending_stock8_preserved':True,'Model_calls':0,'financial_actions':0,'campaign_policy_written':False}
 if not args.apply_existing_timer:print(json.dumps(plan));return
 folder=ROOT/'state/r4-demand'
 if folder.is_symlink() or (folder.exists() and folder.resolve()!=folder):raise ValueError('untrusted demand directory')
 folder.mkdir(exist_ok=True,mode=0o700)
 if folder.stat().st_uid!=os.getuid() or folder.stat().st_mode&0o077:raise ValueError('demand directory not private')
 if not target.exists():
  stage=ROOT/'tools'/('.record-stock-request-'+str(time.time_ns()));shutil.copytree(REC/'tools/record_stock_request',stage);native(stage);stage.rename(target)
 native(target)
 subprocess.run([str(OP/'.venv/bin/python'),'-I','-B',str(HOST/'run_observer.py'),'--package-manifest-sha',HOSTPIN,'--recorder-forge-sha',FORGEPIN],check=True)
 if not DROP.exists():
  DROP.parent.mkdir(exist_ok=True,mode=0o755)
  with DROP.open('x') as f:f.write(text)
  DROP.chmod(0o644)
 # Reload definitions only. Never start/restart any service or timer here.
 ctl('daemon-reload')
 if static_command(property('ExecStart'))!=static_command(start) or str(HOST/'run_observer.py') not in property('ExecStartPost') or property('TimeoutStartUSec')!='55s':raise ValueError('unexpected effective cache unit')
 if snapshots(b['services'])!=before:raise ValueError('original service changed')
 out=dict(plan,status='installed_existing_timer_posthook',at=time.time(),native_version=4,native_forge_sha256=FORGEPIN,host_sha256=HOSTPIN,new_service_units=0,new_timers=0,services_started_or_restarted=0,will_run_on_next_existing_timer_tick=True)
 path=STATE/('request-existing-timer-install-safe-'+str(time.time_ns())+'.json');path.write_text(json.dumps(out,indent=2));print(json.dumps(out))
if __name__=='__main__':main()
