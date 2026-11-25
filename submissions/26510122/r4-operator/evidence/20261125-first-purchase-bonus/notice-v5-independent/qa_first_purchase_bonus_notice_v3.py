"""Known-case independent notice-v3 QA. Original legacy DDL, no real network."""
from first_purchase_bonus_qa_support import *
from types import SimpleNamespace
import importlib.util,httpx,traceback
OUT=Path(__file__).parent/'validation/first-purchase-bonus-notice-v3-independent-20261125-second';OUT.mkdir(mode=0o700)
STAGE=WORK.parent/'validation/first_purchase_bonus_notice_v3_candidate';assert sha256((STAGE/'MANIFEST.json').read_bytes()).hexdigest()=='e527f2472f7385e8fbd5472a5b05eda3df7ee46b0b319ddbc89cf036e6ec9b88'
spec=importlib.util.spec_from_file_location('notice_independent',STAGE/'tools/first_purchase_bonus_notice/logic.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
for n,d in json.loads((STAGE/'MANIFEST.json').read_text())['files_sha256'].items():assert sha256((STAGE/n).read_bytes()).hexdigest()==d
class Case:
 def __init__(self,name):
  self.root=OUT/name;self.root.mkdir(mode=0o700);self.f=Fixture(self.root,run=legacy.run);self.f.db_path=self.root/'state/r4-benefits/benefits.sqlite3';self.f.db_path.parent.mkdir(parents=True,mode=0o700);self.now=float(time.time());self.post=[];self.rows=[self.row(1,'market','market',self.now-400)];self.timeout=False;self.after_token=None
  with closing(self.f.open()) as db:
   for source in [PROD/'procurement.py',OP.parent/'round-4/tools/forum_marketing/logic.py']:
    for n in ast.parse(source.read_text()).body:
     if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SCHEMA' for t in n.targets):db.executescript(ast.literal_eval(n.value))
   db.execute('UPDATE identity SET wallet=?',(m.WALLET,));db.commit()
  self.policy={'enabled':True,'id':'synthetic-notice','start':self.now-20,'end':self.now-20+72*3600,'lifetime_budget':50000};self.write_policy();self.approval(None)
  self.kit=SimpleNamespace(name=m.SHOP,market=m.MARKET,shop_url='https://synthetic-notice.trycloudflare.com',address=lambda role:m.WALLET,token=self.token)
  self.client=httpx.Client(transport=httpx.MockTransport(self.handle))
 def row(self,id,author,role,ts,text='synthetic public record'):return {'id':id,'ts':int(ts),'round':4,'author':author,'role':role,'owner':None,'thread':None,'text':text,'refs':[],'likes':0,'dislikes':0,'score':0.0}
 def write_policy(self):
  self.raw=canonical(self.policy);(self.f.db_path.parent/m.POLICY).write_bytes(self.raw)
 def approval(self,fp,**extra):
  a={'shop':m.SHOP,'round':4,'wallet':m.WALLET,'shop_url':'https://synthetic-notice.trycloudflare.com','card_url':'https://synthetic-notice.trycloudflare.com/.well-known/agent-card.json','observed_at':self.now-1,'valid_until':self.now+149,'policy_sha256':sha256(self.raw).hexdigest(),'approved_fingerprint':fp};a.update(extra);(self.f.db_path.parent/m.APPROVAL).write_bytes(canonical(a))
 def token(self,role):
  if self.after_token:self.after_token()
  return 'synthetic-test-token'
 def handle(self,r):
  if r.method=='GET':
   if r.url.path=='/api/shops':v={'round':4,'shops':[{'name':m.SHOP,'url':self.kit.shop_url,'pubkey':m.WALLET}]}
   elif r.url.path=='/api/agents':v={'round':4,'agents':[{'name':m.SHOP,'roles':['buyer','shop'],'card':self.kit.shop_url+m.CARD_SUFFIX}]}
   else:assert r.url.path=='/api/forum';v=self.rows
   return httpx.Response(200,json=v)
  assert r.method=='POST' and r.url.path=='/api/forum';self.post.append(json.loads(r.content)['text'])
  with closing(sqlite3.connect(self.f.db_path)) as db:assert db.execute("SELECT COUNT(*) FROM forum_publication WHERE status='sending'").fetchone()[0]==1
  if self.timeout:raise httpx.ReadTimeout('synthetic',request=r)
  return httpx.Response(200,json={'post':9})
 def call(self,mode):
  old=Path.cwd();os.chdir(self.root)
  try:return m.execute(mode,self.kit,Path('state/r4-benefits'),self.client,lambda:self.now)
  except m.Stop as e:return {'status':'blocked','reason':str(e)}
  finally:os.chdir(old)
 def q(self,s,args=()):
  with closing(sqlite3.connect(self.f.db_path)) as db:r=db.execute(s,args).fetchall();db.commit();return r
RESULT=[]
def check(name,fn):
 try:fn();RESULT.append({'case':name,'passed':True})
 except Exception as e:traceback.print_exc();RESULT.append({'case':name,'passed':False,'error_type':type(e).__name__})
def preview():
 c=Case('preview');before=sha256(c.f.db_path.read_bytes()).hexdigest();r=c.call('preview');assert r['lane']=='eligible' and not c.post;assert sha256(c.f.db_path.read_bytes()).hexdigest()==before;c.q("SELECT COUNT(*) FROM sale WHERE status='settled'");assert not c.q("SELECT name FROM sqlite_master WHERE name='welcome_award'");assert c.call('dispatch')['reason']=='dispatch_unapproved' and not c.post
 global TEXT;TEXT=r['text']
def disabled_expired():
 for variant in ['disabled','expired','tamper']:
  c=Case(variant);fp=c.call('preview')['fingerprint'];c.approval(fp)
  if variant=='disabled':c.policy['enabled']=False;c.write_policy()
  elif variant=='expired':c.now+=72*3600
  else:c.after_token=lambda:(c.f.db_path.parent/m.POLICY).write_bytes(c.raw+b' ')
  assert c.call('dispatch')['status']=='blocked' and not c.post
 def unused():pass

def budget():
 c=Case('budget');fp=c.call('preview')['fingerprint'];c.approval(fp);core=WORK.parent/'host/validation/first-purchase-bonus-v4-independent-20261125/source/logic.py';d={};exec(core.read_text(),d);c.q(d['AWARD_SCHEMA'])
 for i in range(10):c.q('INSERT INTO welcome_award VALUES(?,?,?,?,?)',(wallet(i+1),'synthetic-'+str(i),5000,int(c.now),i))
 assert c.call('preview')['lane']=='budget_exhausted';assert c.call('dispatch')['reason']=='budget_exhausted' and not c.post

def approved():
 c=Case('approved');fp=c.call('preview')['fingerprint'];c.approval(fp);assert c.call('dispatch')['status']=='posted' and len(c.post)==1;assert c.call('dispatch')['reason']=='campaign_already_attempted' and len(c.post)==1

def cooldown():
 c=Case('cooldown');fp=c.call('preview')['fingerprint'];c.approval(fp)
 c.q('INSERT INTO forum_publication VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',('old',m.SHOP,4,None,'other','synthetic',0,'posted',None,c.now-329,3,0));assert c.call('dispatch')['reason']=='cooldown' and not c.post
 c.q('DELETE FROM forum_publication');c.rows.append(c.row(2,m.SHOP,'shop',c.now-329));assert c.call('dispatch')['reason']=='cooldown' and not c.post

def unknown_reconcile():
 c=Case('unknown');fp=c.call('preview')['fingerprint'];c.approval(fp);c.timeout=True;assert c.call('dispatch')['status']=='unknown';assert c.call('dispatch')['reason']=='journal_busy' and len(c.post)==1
 s=OP.parent/'round-4/tools/forum_marketing/logic.py';spec=importlib.util.spec_from_file_location('legacy_forum_independent',s);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
 c.now+=331;rows=[c.row(9,m.SHOP,'shop',c.now-331,c.post[0])]
 with closing(sqlite3.connect(c.f.db_path)) as db:
  db.row_factory=sqlite3.Row;r=mod.forum_reconcile(db,SimpleNamespace(forum=lambda since:rows),c.now)
 assert r['status']=='reconciled' and c.q('SELECT status FROM forum_publication')[0][0]=='posted' and len(c.post)==1

def permission():
 p=(STAGE/'tools/first_purchase_bonus_notice/permission.yml').read_text();assert 'identity: [shop]' in p and 'network: [market.ourolabs.ai]' in p and 'write: [state/r4-benefits]' in p and 'pay_limit: 0' in p and 'wallet:' not in p and 'exec:' not in p

if __name__=='__main__':
 from contextlib import redirect_stdout,redirect_stderr
 with (OUT/'private-console.log').open('w') as log,redirect_stdout(log),redirect_stderr(log):
  for name,fn in [('actual-list-multitable-zero-preview-nullfp',preview),('disabled-tampered-expired-noPOST',disabled_expired),('budget-exhausted-noPOST',budget),('approved-exactfp-onePOST',approved),('shared330-cooldown-noPOST',cooldown),('unknown-no-retry-legacy-reconcile',unknown_reconcile),('permissions-keyless-no-pay',permission)]:check(name,fn)
 safe={'total':len(RESULT),'passed':sum(r['passed'] for r in RESULT),'cases':RESULT,'source_manifest_sha256':sha256((STAGE/'MANIFEST.json').read_bytes()).hexdigest(),'actual_Model_HTTP_POST_service_changes':0,'method':'Independent direct genuine execute with httpx.MockTransport and original tracked dispatcher/procurement/forum DDL; no kit.testing spoof or ordinary SDK run readiness claim.','wording_review':{'baseline1_extra5_after_settlement_wallet_once_caps5000_50000_window72h_nextpurchase_refund_no_reaward':True,'expiry_wording_matches_core':False,'gap':'Notice says 7 days from issuance, core expiry is original settled+604800; delayed award can have shorter remaining life.'}}
 (OUT/'safe-result.json').write_text(json.dumps(safe,indent=2));print(json.dumps(safe))
