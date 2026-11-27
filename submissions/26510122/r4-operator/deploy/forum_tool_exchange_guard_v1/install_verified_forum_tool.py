"""HOST guard for explicit user-authorized advertising update; no service restart.
Only swaps exact genuine forum_marketing source. Cached candidate scope is NOT reloaded.
Default verifies staging. No Model, HTTP, posts, payments, policy activation or DB mutation.
"""
from pathlib import Path
from hashlib import sha256
import argparse,json,os,subprocess,sqlite3,time,fcntl,shutil,ctypes,uuid,sys
OP=Path('/home/seop/.local/share/ourolabs-r4-checkout/submissions/26510122/r4-operator')
ROOT=OP.parent/'round-4';BASE=Path(__file__).parent/'before-private.json';TARGET=ROOT/'tools/forum_marketing'
def fp(p):
 s=p.stat();return {'device':s.st_dev,'inode':s.st_ino,'sha256':sha256(p.read_bytes()).hexdigest()}
def service_view(names):return {n:subprocess.check_output(['systemctl','--user','show',n,'--property=MainPID,NRestarts,ActiveState'],text=True).strip() for n in names}
def workers():
 out=[]
 for p in Path('/proc').iterdir():
  if not p.name.isdigit() or int(p.name)==os.getpid():continue
  try:
   if str(TARGET).encode() in (p/'cmdline').read_bytes().split(b'\0') and (p/'cwd').resolve()==ROOT:out.append(int(p.name))
  except OSError:pass
 return out
def check_bundle(bundle,pin):
 if bundle.resolve(strict=True)!=bundle or bundle.parent!=OP/'deploy':raise ValueError('untrusted staged bundle')
 raw=(bundle/'MANIFEST.json').read_bytes()
 if sha256(raw).hexdigest()!=pin:raise ValueError('unreviewed bundle')
 m=json.loads(raw)
 for n,h in m['files'].items():
  q=bundle/n;r=Path(n)
  if r.is_absolute() or '..' in r.parts or q.resolve(strict=True)!=q or sha256(q.read_bytes()).hexdigest()!=h:raise ValueError('bundle drift')
 source=bundle/'tools/forum_marketing';f=json.loads((source/'forge.json').read_text())
 if f.get('tool')!='forum_marketing':raise ValueError('wrong tool')
 for n,h in f['sha256'].items():
  if sha256((source/n).read_bytes()).hexdigest()!=h:raise ValueError('forge mismatch')
 # Use the unchanged official permission parser. No toolbox, wallet, token or capability is created.
 sys.path.insert(0,str(OP/'kit'));import agent_kit as official;forge_runner=official.forge_runner
 perm=forge_runner.parse_permission((source/'permission.yml').read_text()).get('permission') or {}
 if set(perm)-{'network','write','identity','timeout','wallet','pay_limit','exec','handles'}:raise ValueError('unrecognized authority')
 if perm.get('network')!=['market.ourolabs.ai'] or perm.get('write')!=['state/r4-benefits'] or perm.get('identity')!=['shop']:raise ValueError('authority must match original')
 if any(perm.get(k) for k in ('wallet','pay_limit','exec','handles')) or type(perm.get('timeout')) is not int or not 5<=perm['timeout']<=40:raise ValueError('unsafe authority or timeout')
 proof=json.loads((bundle/'FINAL-VERIFICATION-SAFE.json').read_text())
 if proof.get('independent_QA_pass') is not True or proof.get('source_sha256')!=f['sha256']['logic.py']:raise ValueError('independent QA missing or wrong source')
 return source,f

def main():
 a=argparse.ArgumentParser(description=__doc__);a.add_argument('--bundle',type=Path,required=True);a.add_argument('--manifest-sha256',required=True);a.add_argument('--apply',action='store_true');args=a.parse_args();os.umask(0o077)
 with (BASE.parent/'forum-install.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);source,forge=check_bundle(args.bundle,args.manifest_sha256);b=json.loads(BASE.read_text());before=service_view(b['services'])
  if before!=b['services']:raise ValueError('original service changed; review rather than restart')
  for n,v in b['wallets'].items():
   if fp(ROOT/n)!=v:raise ValueError('wallet identity changed')
  for n,v in b['source'].items():
   if fp(ROOT/'codex-r4'/n)!=v:raise ValueError('shared source changed')
  for n,v in b['stock4'].items():
   if fp(ROOT/'tools/stock_procurement'/n)!=v:raise ValueError('existing stock tool changed')
  if fp(ROOT/'codex-r4/launch-price-policy.json')!=b['price_policy'] or fp(ROOT/'state/r4-benefits/first-purchase-bonus-policy.json')!=b['bonus_policy']:raise ValueError('price/bonus policy changed')
  dbp=ROOT/'state/r4-benefits/benefits.sqlite3';st=dbp.stat()
  if {'device':st.st_dev,'inode':st.st_ino}!=b['DB_identity']:raise ValueError('database replaced')
  with sqlite3.connect(dbp.as_uri()+'?mode=ro',uri=True,timeout=5) as db:
   db.row_factory=sqlite3.Row;db.execute('pragma query_only=on')
   pending=[dict(r) for r in db.execute("select * from sale where status not in ('settled','refunded')")]
   if pending!=b['pending']:raise ValueError('existing pending sale changed')
   if db.execute("select count(*) from forum_publication where status in ('sending','unknown')").fetchone()[0]:raise ValueError('unresolved publication; reconcile instead of replacing')
  old=all(fp(TARGET/n)==v for n,v in b['original_forum4'].items())
  new=sha256((TARGET/'forge.json').read_bytes()).hexdigest()==sha256((source/'forge.json').read_bytes()).hexdigest()
  if not old and not new:raise ValueError('unreviewed current tool source')
  report={'verified':True,'live':False,'original_services_wallets_DB_stock_price_policy_preserved':True,'Model_HTTP_payment_or_post_calls':0,'cached_candidate_scope_reloaded':False,'hot_swap_effect':'new final publisher/render only; expanded request context remains staged until separately reviewed process transition','new_tool_version':forge['version']}
  if not args.apply:print(json.dumps(report));return
  if workers():raise ValueError('forum tool subprocess active; wait existing tick to finish')
  if not new:
   stage=ROOT/'tools'/('.forum-reviewed-'+uuid.uuid4().hex);shutil.copytree(source,stage)
   for n in ('logic.py','test.py','forge.json','permission.yml'):
    if sha256((stage/n).read_bytes()).hexdigest()!=sha256((source/n).read_bytes()).hexdigest():raise ValueError('stage copy changed')
   if workers():raise ValueError('worker appeared; keep stage and retry after reconciliation')
   fn=ctypes.CDLL(None,use_errno=True).renameat2;fn.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint];fn.restype=ctypes.c_int
   if fn(-100,os.fsencode(stage),-100,os.fsencode(TARGET),2)!=0:raise OSError(ctypes.get_errno(),'atomic tool exchange failed')
   archive=ROOT/'tools/.deprecated';archive.mkdir(exist_ok=True);stage.rename(archive/('forum_marketing-before-demand-'+str(time.time_ns())))
  if service_view(b['services'])!=before:raise ValueError('service changed during source transition')
  report.update(live=True,at=time.time(),tool_source_sha256=forge['sha256']['logic.py'],main_restarts=0,source_scope='final publisher only')
  (BASE.parent/('forum-activation-safe-'+str(time.time_ns())+'.json')).write_text(json.dumps(report,indent=2));print(json.dumps(report))
if __name__=='__main__':main()
