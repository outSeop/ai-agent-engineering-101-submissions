"""Prepare/one-shot GET-only genuine SDK canary; no Model, POST or wallet keys.
Explicit CLI paths; all native execution uses a private minimized clone DB.
"""
import argparse,ast,json,os,sqlite3,stat,sys,time,shutil,importlib.util
from pathlib import Path
from hashlib import sha256
from contextlib import chdir,redirect_stdout,redirect_stderr

def original_schema(path):
 for node in ast.parse(path.read_bytes()).body:
  if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SCHEMA' for t in node.targets):return ast.literal_eval(node.value)
 raise ValueError('original schema missing')
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--operator',type=Path,required=True);ap.add_argument('--source',type=Path,required=True);ap.add_argument('--dependency-dir',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--logic-sha',required=True);ap.add_argument('--allow-read-only-market',action='store_true');ap.add_argument('--verify-coverage',action='store_true');a=ap.parse_args()
 op=a.operator.resolve(strict=True);prod=op.parent/'round-4';src=a.source.resolve(strict=True);deps=a.dependency_dir.resolve(strict=True);out=a.output.resolve();out.relative_to(op/'runtime');assert a.allow_read_only_market
 os.umask(0o077);out.mkdir(mode=0o700);root=out/'isolated-root';root.mkdir(mode=0o700);code=root/'codex-r4';code.mkdir(mode=0o700);tool=root/'tools/forum_marketing';tool.mkdir(mode=0o700,parents=True);state=root/'state/r4-benefits';state.mkdir(mode=0o700,parents=True)
 pins={n:sha256((src/n).read_bytes()).hexdigest() for n in ['logic.py','test.py','permission.yml','forge.json']};assert pins['logic.py']==a.logic_sha;forge=json.loads((src/'forge.json').read_bytes());assert forge['tool']=='forum_marketing' and forge['sha256']=={n:h for n,h in pins.items() if n!='forge.json'}
 for n in pins:shutil.copyfile(src/n,tool/n);(tool/n).chmod(0o400)
 copied={}
 for path in deps.iterdir():
  if path.is_file() and (path.name in ['forum.py','dispatcher.py','broker.py','price_policy.py'] or path.name.startswith('forum_marketing') and path.suffix=='.py'):
   shutil.copyfile(path,code/path.name);copied[path.name]=sha256(path.read_bytes()).hexdigest()
 for name in ['forum.py','dispatcher.py','broker.py','price_policy.py']:
  if not (code/name).is_file():shutil.copyfile(prod/'codex-r4'/name,code/name);copied[name]=sha256((code/name).read_bytes()).hexdigest()
  assert (code/name).is_file()
 shutil.copyfile(prod/'codex-r4/launch-price-policy.json',code/'launch-price-policy.json')
 # Minimal read-only projection only; no customer accounts/rights/real sale or payment data copied.
 production_db=prod/'state/r4-benefits/benefits.sqlite3';db_stat=production_db.stat();projection_at=time.time()
 with sqlite3.connect(production_db.resolve().as_uri()+'?mode=ro',uri=True,timeout=3) as original:
  original.row_factory=sqlite3.Row;original.execute('PRAGMA query_only=ON');original.execute('BEGIN');identity=dict(original.execute('SELECT shop,wallet FROM identity WHERE singleton=1').fetchone());reserved=[r[0] for r in original.execute('SELECT DISTINCT unit FROM sale')];pubsql=original.execute("SELECT sql FROM sqlite_master WHERE name='forum_publication' AND type='table'").fetchone()[0];publications=[dict(r) for r in original.execute('SELECT * FROM forum_publication WHERE shop=? AND round=4',(identity['shop'],))];original.rollback()
 assert identity['shop']=='outseop-r4'
 clone=state/'benefits.sqlite3'
 with sqlite3.connect(clone) as db:
  db.executescript(original_schema(code/'dispatcher.py'));db.execute(pubsql);db.execute('INSERT INTO identity VALUES(1,?,?)',(identity['shop'],identity['wallet']))
  columns=['id','owner','unit','sku','base','cost','price','discount','spent','ticket','shop_url','wallet','created','digest','jwt','expected_wei','fee_wei','gas_cap_wei','fee_wallet','grade','status']
  for i,unit in enumerate(reserved):
   values=[f'synthetic-pinned-{i}','synthetic-not-customer',unit,'G00000000',1,0,1,0,0,None,'https://isolated-readonly.invalid',identity['wallet'],projection_at,f'{i+1:064x}','synthetic-no-checkout','1','0','0',identity['wallet'],'A','issued'];db.execute('INSERT INTO sale ('+','.join(columns)+') VALUES ('+','.join('?' for _ in values)+')',values)
  for row in publications:
   columns=list(row);db.execute('INSERT INTO forum_publication ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')',[row[n] for n in columns])
 clone.chmod(0o600);generation='a'*64;(state/'marketing-owner-policy.json').write_text(json.dumps({'schema':'outseop-r4.marketing-owner.v1','active':True,'generation':generation,'token':'b'*64}));(state/'marketing-owner-policy.json').chmod(0o600)
 credential=prod/'.kit/worker-token';info=credential.lstat();assert stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and stat.S_IMODE(info.st_mode)==0o600 and info.st_nlink==1;token=credential.read_text().strip();assert token
 sys.path.insert(0,str(op/'kit'));import agent_kit as sdk
 class NoWallet:
  def grant(self,name,permission,timeout):
   assert permission.get('pay_limit',0)==0 and not any(permission.get(k) for k in ['wallet','exec','handles']);assert permission.get('identity')==['shop'];assert set(permission.get('network') or [])=={'market.ourolabs.ai','127.0.0.1'} and permission.get('write')==['state/r4-benefits'] and permission.get('timeout')==150;return None
 coverage_result={};coverage_seconds=None;before=sha256(clone.read_bytes()).hexdigest();slate_after=None;context={'name':'outseop-r4','market':'https://market.ourolabs.ai','shop_url':'https://isolated-readonly.invalid','tokens':{'shop':token},'addresses':{'shop':identity['wallet']},'signer':NoWallet()}
 with (out/'SDK-console-private.log').open('w') as log,redirect_stdout(log),redirect_stderr(log):
  sdk.mk.LOG_FILE=out/'SDK-private.log';box=sdk.Toolbox(root,context);start=time.monotonic();started_at=time.time();response=box.run('forum_marketing','call',{'action':'slate_context','scheduler_generation':generation,'operation_timeout':30});elapsed=time.monotonic()-start;finished_at=time.time();(out/'SDK-envelope-private.json').write_text(json.dumps(response,ensure_ascii=False));slate_after=sha256(clone.read_bytes()).hexdigest()
  if a.verify_coverage:
   t=time.monotonic();coverage_response=box.run('forum_marketing','call',{'action':'context','scheduler_generation':generation,'operation_timeout':30});coverage_seconds=time.monotonic()-t;(out/'coverage-envelope-private.json').write_text(json.dumps(coverage_response,ensure_ascii=False));coverage_result=coverage_response.get('result',{}) if coverage_response.get('ok') else {}
 data=response.get('result',{}) if response.get('ok') else {};source=data.get('source',{});(out/'native-source-private.json').write_text(json.dumps(data,ensure_ascii=False));source_items=source.get('items',[])
 # Independent fresh GET after the SDK call checks that returned public facts still match original core pricing.
 import httpx
 verification_started=time.monotonic();inputs={}
 with httpx.Client(timeout=4,trust_env=False) as client:
  for path,auth in [('/api/inventory',True),('/api/chain',False)]:
   r=client.get('https://market.ourolabs.ai'+path,headers={'authorization':'Bearer '+token} if auth else None);r.raise_for_status();inputs[path]=r.json();(out/(path.rsplit('/',1)[-1]+'-verification-private.json')).write_bytes(r.content)
 token=None;context['tokens'].clear()
 sys.path.insert(0,str(code));spec=importlib.util.spec_from_file_location('original_forum_validation',code/'forum.py');parent=importlib.util.module_from_spec(spec)
 with chdir(root):
  spec.loader.exec_module(parent)
  class PublicKit:
   name='outseop-r4';market='https://market.ourolabs.ai';shop_url='https://isolated-readonly.invalid'
   def address(self,role):return identity['wallet']
  class CachedPublicMarket(parent.Market):
   def get(self,path,**kwargs):return inputs[path]
  with sqlite3.connect(clone.resolve().as_uri()+'?mode=ro',uri=True) as db:
   db.row_factory=sqlite3.Row;db.execute('PRAGMA query_only=ON');offers=parent.stock_offers(db,CachedPublicMarket(PublicKit()),time.time())
 current={(x['sku'],x['grade']):x for x in offers};fields=['sku','grade','name','price','category','expiry','certificate'];facts_equal=all((row['sku'],row['grade']) in current and all(row[k]==current[(row['sku'],row['grade'])][k] for k in fields) for row in source_items);end=time.time();urgent=[r for r in source_items if r['grade']=='C' and r.get('expiry') is not None and 1200<=r['expiry']-end<=21600 and r['spotlight_eligible'] is True]
 safe={'schema':'r4-genuine-forum-liveGET-ordinary-SDK-canary.v1','tool_version':forge['version'],'source4_sha256':pins,'dependency_sha256':copied,'ordinary_SDK_call':True,'kit_testing_false_by_ordinary_mode':True,'SDK_ok':response.get('ok',False),'native_status':data.get('status'),'SDK_real_GET_plus_CPU_seconds':round(elapsed,4),'within30':elapsed<=30,'started_at':started_at,'finished_at':finished_at,'projection_at':projection_at,'actual_inventory_units_after':len(inputs['/api/inventory']['units']),'returned_reply_options':len(source.get('reply_options',[])),'returned_items':len(source_items),'urgent_C_currently_eligible':len(urgent),'returned_facts_match_independent_fresh_GET_original_core':facts_equal,'independent_verification_GET_seconds':round(time.monotonic()-verification_started,4),'independent_verification_GET_count':2,'context_TTL_valid_at_SDK_finish':finished_at<source.get('valid_until',0),'clone_DB_byte_unchanged_by_slate_context':slate_after==before,'clone_context_initializer_may_add_schema_only':bool(a.verify_coverage),'coverage_probe_requested':bool(a.verify_coverage),'coverage_context_seconds':round(coverage_seconds,4) if coverage_seconds is not None else None,'ordinary_context_request_coverage':coverage_result.get('request_coverage'),'coverage_context_status':coverage_result.get('status'),'production_DB_inode_unchanged':production_db.stat().st_ino==db_stat.st_ino,'wallet_key_or_identity_files_read_or_copied':0,'worker_credential_private_GET_only':True,'real_Model_POST_financial_calls':0,'GET_count_inside_native_not_instrumented':True,'native_fixed_action_and_source_audit':'Only marked slate_context; original source branch performs GETs and RO clone SELECTs. No dispatch to publish/reconcile/Model. No HTTP method interceptor or native source edit was installed.','scope_note':'Real network+CPU ordinary SDK with NoWallet and synthetic clone policy, no live publication or production-owner activation claim. Independent post-call GET facts may detect concurrent changes.'}
 safe['passed']=bool(safe['SDK_ok'] and safe['native_status']=='options' and safe['within30'] and safe['returned_reply_options']>=1 and facts_equal and safe['context_TTL_valid_at_SDK_finish'] and safe['clone_DB_byte_unchanged_by_slate_context']);safe['passed']=safe['passed'] and (not a.verify_coverage or bool(coverage_result.get('request_coverage',{}).get('complete') is True and coverage_seconds<=30));(out/'safe-result.json').write_text(json.dumps(safe,indent=2));print('R4_MARKETING_RESULT '+json.dumps(safe),flush=True)
if __name__=='__main__':main()
