"""Guarded proposal for explicit user approval. Default is read-only.
Uses the existing seller coordinator; no new Model/trading loop or service restart.
Apply installs exact genuine15 and opens one finite6h campaign; prior live approvals were rejected.
"""
from pathlib import Path
from hashlib import sha256
import argparse,json,os,shutil,subprocess,time,sqlite3,ctypes,fcntl,uuid
OP=Path('/home/seop/.local/share/ourolabs-r4-checkout/submissions/26510122/r4-operator');ROOT=OP.parent/'round-4';STATE=Path(__file__).parent
BUNDLE=OP/'deploy/profitable_stock_native_v15';PIN='46c7128c893309a9e58fd3955956931d4291af1f86149e0ca32179991cb72d80';FORGE='a031d81c045b2de39d48c82fdce7fd5eface083b0d9c35ba72f92ae54f604dcf';PARENT='675bdaa2942f7bdf3d119d10c6e1176f790ae0bacbb22a32cf77ae82de0628c6'
TARGET=ROOT/'tools/stock_procurement';POLICY=ROOT/'host_inputs/stock-campaign-policy.json';RECEIPT=STATE/'campaign-config-private.json'
def fingerprint(p):
 x=p.stat();return {'device':x.st_dev,'inode':x.st_ino,'sha256':sha256(p.read_bytes()).hexdigest()}
def ctl(*args):return subprocess.check_output(['systemctl','--user',*args],text=True).strip()
def verify_bundle():
 raw=(BUNDLE/'release-manifest.json').read_bytes()
 if sha256(raw).hexdigest()!=PIN:raise ValueError('unreviewed release')
 m=json.loads(raw)
 for n,h in m['sha256'].items():
  rel=Path(n);p=BUNDLE/rel
  if rel.is_absolute() or '..' in rel.parts or p.resolve()!=p or sha256(p.read_bytes()).hexdigest()!=h:raise ValueError('release source drift')
 for n,h in m['validation_files'].items():
  if sha256((BUNDLE/'validation'/n).read_bytes()).hexdigest()!=h:raise ValueError('release evidence drift')
 return m
def verify_tool(folder):
 raw=(folder/'forge.json').read_bytes()
 if sha256(raw).hexdigest()!=FORGE:raise ValueError('not reviewed native15')
 for n,h in json.loads(raw)['sha256'].items():
  if sha256((folder/n).read_bytes()).hexdigest()!=h:raise ValueError('native files drift')
def active_tool_workers():
 found=[]
 for p in Path('/proc').iterdir():
  if not p.name.isdigit() or int(p.name)==os.getpid():continue
  try:
   args=(p/'cmdline').read_bytes().split(b'\0')
   if str(TARGET).encode() in args and (p/'cwd').resolve()==ROOT:found.append(int(p.name))
  except (OSError,PermissionError):pass
 return found
def source_ready(now):
 states={}
 for name in ('stock-demand-signals.json','stock-public-catalog.json','stock-demand-exclusions.json'):
  p=ROOT/'host_inputs'/name
  try:
   d=json.loads(p.read_text());states[name]=d.get('round')==4 and d.get('observed_at',now+1)<=now<d.get('valid_until',0)
   if name=='stock-demand-signals.json':states[name]&=d.get('coverage',{}).get('complete') is True
  except (OSError,ValueError):states[name]=False
 return states
def main():
 a=argparse.ArgumentParser(description=__doc__);a.add_argument('--apply-after-user-approval',action='store_true');args=a.parse_args();os.umask(0o077)
 if os.getuid()!=1000:raise ValueError('registered local user only')
 with (STATE/'stock-install.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);m=verify_bundle();b=json.loads((STATE/'before-private.json').read_text());services={n:ctl('show',n,'--property=MainPID,NRestarts,ActiveState') for n in b['services']}
  if services!=b['services']:raise ValueError('original service state changed')
  for n,v in b['wallets'].items():
   if fingerprint(ROOT/n)!=v:raise ValueError('original wallet changed')
  for n,v in b['source'].items():
   if fingerprint(ROOT/'codex-r4'/n)!=v:raise ValueError('original shared source changed')
  if fingerprint(Path(b['policy_path']))!=b['policy']:raise ValueError('original sales price policy changed')
  current=sha256((TARGET/'logic.py').read_bytes()).hexdigest();new=m['sha256']['tools/stock_procurement/logic.py']
  if current not in (PARENT,new):raise ValueError('unrecognized current stock tool')
  dbp=ROOT/'state/r4-benefits/benefits.sqlite3'
  with sqlite3.connect(dbp.as_uri()+'?mode=ro',uri=True,timeout=5) as db:
   db.row_factory=sqlite3.Row;db.execute('pragma query_only=on');pending=[dict(x) for x in db.execute("select * from sale where status not in ('settled','cancelled','refunded','expired')")]
   if pending!=b['pending']:raise ValueError('pending customer sale changed')
   unresolved=db.execute("select count(*) from stock_intent where state in ('reserved','sending','unknown','paid','accepted')").fetchone()[0]
   ready=db.execute("select count(*) from stock_plan where status='ready' and expires>?",(time.time(),)).fetchone()[0]
  readiness=source_ready(time.time());tool4=ROOT/'tools/record_stock_request/forge.json';recorder_ready=tool4.exists() and sha256(tool4.read_bytes()).hexdigest()=='17efbe8ee7e91a02b021937c4ee24924c2ec51de2bfbc71dbe19eb11220a5bf0'
  out={'status':'verified_staged_only','original_services_wallets_DB_pending_pricefloor_preserved':True,'new_stock_tool_version':15,'old_stock8_still_active':current==PARENT,'unresolved_procurement':unresolved,'unexpired_ready_plans':ready,'live_source_ready':readiness,'recorder4_installed':recorder_ready,'requested_window_max_new_SKUs':5,'units_per_SKU':1,'finite_campaign_hours':6,'postpayment_inventory_limit_pct':85,'new_risk_credit_ceiling':100000,'also_limited_by_equity_pct':5,'existing_dues_paid_and_reported_separately':True,'new_services_or_loops':0,'policy_enabled_by_dryrun':False,'Model_or_financial_calls':0}
  if not args.apply_after_user_approval:print(json.dumps(out));return
  if unresolved or ready or active_tool_workers():raise ValueError('existing financial phase not idle')
  if not recorder_ready or not all(readiness.values()):raise ValueError('approved request/source hookup not ready; wait existing timer')
  if POLICY.exists() and (not RECEIPT.exists() or json.loads(POLICY.read_text())!=json.loads(RECEIPT.read_text())):raise ValueError('do not overwrite existing campaign')
  parent=ROOT/'host_inputs/legacy-stock8.py'
  if parent.exists():
   if sha256(parent.read_bytes()).hexdigest()!=PARENT:raise ValueError('parent source mismatch')
  else:
   with parent.open('xb') as f:f.write((BUNDLE/'host_inputs/legacy-stock8.py').read_bytes())
   parent.chmod(0o400)
  if current==PARENT:
   stage=ROOT/'tools'/('.stock-demand-candidate-'+uuid.uuid4().hex);shutil.copytree(BUNDLE/'tools/stock_procurement',stage);verify_tool(stage)
   if active_tool_workers():raise ValueError('tool worker appeared; preserve staged candidate and retry safely')
   libc=ctypes.CDLL(None,use_errno=True);fn=libc.renameat2;fn.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint];fn.restype=ctypes.c_int
   if fn(-100,os.fsencode(stage),-100,os.fsencode(TARGET),2)!=0:raise OSError(ctypes.get_errno(),'atomic exact tool exchange failed')
   archive=ROOT/'tools/.deprecated';archive.mkdir(exist_ok=True);backup=archive/('stock_procurement@8-before-demand-'+str(time.time_ns()));stage.rename(backup)
  verify_tool(TARGET)
  if not POLICY.exists():
   start=int(time.time());config={'campaign_id':'market-demand-'+uuid.uuid4().hex[:16],'starts_at':start,'ends_at':start+21600};RECEIPT.write_text(json.dumps(config));RECEIPT.chmod(0o600)
   temporary=POLICY.with_name('.stock-campaign-'+uuid.uuid4().hex);temporary.write_text(json.dumps(config));temporary.chmod(0o400);temporary.rename(POLICY)
  else:config=json.loads(POLICY.read_text())
  after={n:ctl('show',n,'--property=MainPID,NRestarts,ActiveState') for n in b['services']}
  if after!=services:raise ValueError('original service changed during apply')
  out.update(status='genuine15_installed_finite_campaign_enabled',at=time.time(),campaign=config,original_services_unchanged=True,manual_pay_or_Model_calls=0)
  (STATE/('stock15-activation-safe-'+str(time.time_ns())+'.json')).write_text(json.dumps(out,indent=2));print(json.dumps(out))
if __name__=='__main__':main()
