from pathlib import Path
from copy import deepcopy
import json,hashlib,sys,tempfile,time,os,math,fcntl
ROOT=Path(__file__).resolve().parent;OP=ROOT.parents[1]
sys.path.insert(0,str(OP/'kit'));import agent_kit as official
APPLY='apply_staged_card';STAGE='stage_representative_card'
checks=[];scopes=[]
def sha(b):return hashlib.sha256(b).hexdigest()
def raw(x):return (json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
def check(case,ok,group='contract',observed=None):checks.append({'case':case,'passed':bool(ok),'group':group,'observed':observed})
class Fixture:
 def __enter__(self):
  self.tmp=tempfile.TemporaryDirectory(dir=ROOT,prefix='fake-host-only-');self.root=Path(self.tmp.name)
  for tool,origin in [(APPLY,ROOT/'tools'/APPLY),(STAGE,ROOT/'tools'/STAGE),('publish_shop_info',ROOT/'tools/publish_shop_info')]:
   p=self.root/'tools'/tool;p.mkdir(parents=True)
   for name in ['logic.py','test.py','permission.yml','forge.json']:(p/name).write_bytes((origin/name).read_bytes())
  archive=self.root/'.deprecated/apply_staged_card@1';archive.mkdir(parents=True)
  for item in (ROOT/'.deprecated/apply_staged_card@1').iterdir():
   if item.is_file():(archive/item.name).write_bytes(item.read_bytes())
  for rel in ['logs','host_inputs/card_offer_original','host_inputs/card_offer_fresh','card_update_stage','card_publication']:(self.root/rel).mkdir(parents=True)
  (self.root/'card_publication/lock').touch()
  self.policies={'mileage':'기존 마일리지 정책은 보존합니다.','wait':'기존 대기권 정책은 보존합니다.','refund':'기존 환불 정책은 보존합니다.'}
  self.old='이전 대표상품';self.card={'name':'outseop-r4','description':self.old+'\n'+'\n'.join(self.policies.values()),'skills':[{'id':'sales'},{'id':'benefits'},{'id':'refund'}],'x-retain':'synthetic-public-only'}
  self.t=int(time.time());self.init()
  signer=official.Signer({},self.root);self.tb=official.Toolbox(self.root,{'market':'https://market.ourolabs.ai','name':'outseop-r4','tokens':{},'addresses':{},'signer':signer});self.calls=[]
  return self
 def __exit__(self,*x):self.tmp.cleanup()
 def init(self):
  self.before=raw(self.card);(self.root/'card.json').write_bytes(self.before)
  rows=[{'sku':'G'+str(i).zfill(8),'name':'합성'+str(i),'category_path':['합성'],'state':'available','grade':'C','price_credits':100,'standard_fee_credits':3,'valid_until':self.t+100,'expires_at':self.t+120} for i in range(1,9)]
  self.view={'schema':'outseop-r4.card-offers.v1','shop':'outseop-r4','observed_at':self.t-5,'valid_until':self.t+110,'card_sha256':sha(self.before),'replace_text':self.old,'offers':rows,'market':None}
 def call(self,tool,args):
  self.calls.append((tool,args));o=self.tb.call(tool,args);assert o.get('ok') is True,o;return o['result']
 def stage(self,skus=None):
  b=raw(self.view);self.source=sha(b);(self.root/'host_inputs/card_offer_context.json').write_bytes(b);(self.root/'host_inputs/card_offer_original'/ (self.source+'.json')).write_bytes(b)
  compared=self.call(STAGE,{'op':'compare'});assert compared['status']=='ready',compared
  staged=self.call(STAGE,{'op':'stage','skus':skus or ['G00000001'],'view_sha256':compared['view_sha256']});assert staged['status']=='staged',staged
  self.record=staged['record_id'];self.stagepath=self.root/'card_update_stage'/(self.record+'.json');self.staged=json.loads(self.stagepath.read_text());self.after=self.staged['after_card_json'].encode();return staged
 def fresh_and_grant(self,changes=None):
  # Host Fake independently rereads synthetic source; no actual marketplace/credentials.
  completed=max(int(time.time()),math.ceil(self.stagepath.stat().st_mtime_ns/1e9));delay=completed-time.time()
  if delay>0:time.sleep(delay+0.005)
  fresh=deepcopy(self.view);fresh['observed_at']=completed
  if changes:changes(fresh)
  b=raw(fresh);freshid=sha(b);(self.root/'host_inputs/card_offer_fresh'/(freshid+'.json')).write_bytes(b);self.freshid=freshid
  stageenv={};exec(compile((ROOT/'tools/stage_representative_card/logic.py').read_bytes(),'pinned_stage_render','exec'),stageenv)
  bysku={x['sku']:x for x in self.view['offers']}
  replacement=stageenv['render']([bysku[k] for k in self.staged['skus']],self.view['observed_at'])
  self.auth={'schema':'outseop-r4.card-publication-authority.v1','shop':'outseop-r4','owner':'native','op':'apply','record_id':self.record,'head':None,'before_sha256':sha(self.before),'after_sha256':sha(self.after),'issued_at':completed,'valid_until':completed+30,'details':{'fresh_view_sha256':freshid,'replacement_sha256':sha(replacement.encode()),'policies':self.policies}}
  self.writeauth();return fresh
 def writeauth(self):(self.root/'host_inputs/card_publication_authority.json').write_bytes(raw(self.auth))
 def apply(self):return self.call(APPLY,{'op':'apply','record_id':self.record})
 def rollback(self,event):
  self.auth.update(op='rollback',record_id=event,head=event,before_sha256=sha(self.after),after_sha256=sha(self.before),issued_at=int(time.time()),valid_until=int(time.time())+30,details={});self.writeauth()
  return self.call(APPLY,{'op':'rollback','record_id':event})

with Fixture() as f:
 f.stage();check('stage_not_live_apply',f.root.joinpath('card.json').read_bytes()==f.before)
 check('missing_authority_waits',f.apply()=={'status':'waiting','reason':'required_host_file_missing'})
 f.fresh_and_grant();out=f.apply();check('genuine_stage_to_ordinary_apply_success',out['status']=='applied',observed=out)
 f.event=out['event'];eventpath=f.root/'card_publication'/(f.event+'.json');saved=eventpath.read_bytes();entry=json.loads(saved)
 check('apply_hash_name_skills_preserved',out['card_sha256']==sha(f.after) and json.loads(f.after)['name']=='outseop-r4' and json.loads(f.after)['skills']==f.card['skills'])
 check('immutable_original_backup_and_event_hash',sha(saved)==f.event and entry['before_card_json'].encode()==f.before and entry['after_card_json'].encode()==f.after)
 check('guard_metadata_available',all(k in entry for k in ['parent','previous_active','offer_until','block','prior_block','before_sha256','after_sha256','view_sha256','fresh_view_sha256']))
 check('idempotent_apply',f.apply()['status']=='already_applied' and eventpath.read_bytes()==saved)
 # Recreate each exact persisted crash checkpoint using synthetic state only.
 headpath=f.root/'card_publication/head.json';headpath.write_bytes(raw({'event':None,'pending':f.event}));check('recover_after_replace_before_head_commit',f.apply()['status']=='already_applied' and json.loads(headpath.read_text())=={'event':f.event,'pending':None})
 headpath.write_bytes(raw({'event':None,'pending':f.event}));(f.root/'card.json').write_bytes(f.before);retry=f.apply();check('recover_before_replace_keeps_backup',retry['status']=='applied' and eventpath.read_bytes()==saved)
 f.event=retry['event'];f.after=(f.root/'card.json').read_bytes()
 (f.root/'card.json').write_bytes(f.after+b' ');out=f.rollback(f.event);check('rollback_conflict_preserves_intervening_card',out.get('reason')=='current_card_hash_conflict' and (f.root/'card.json').read_bytes()==f.after+b' ')
 (f.root/'card.json').write_bytes(f.after);out=f.rollback(f.event);check('rollback_restores_exact_original',out['status']=='rolled_back' and (f.root/'card.json').read_bytes()==f.before)
 check('idempotent_rollback',f.call(APPLY,{'op':'rollback','record_id':f.event})['status']=='already_rolled_back')
for label,mutation,reason in [
 ('price',lambda v:v['offers'][0].update(price_credits=1),'selected_offer_terms_changed'),
 ('grade',lambda v:v['offers'][0].update(grade='A'),'selected_offer_terms_changed'),
 ('reserved',lambda v:v['offers'][0].update(state='reserved'),'selected_offer_unavailable'),
 ('sold_out',lambda v:v['offers'][0].update(state='sold_out'),'selected_offer_unavailable'),
 ('expired',lambda v:v['offers'][0].update(expires_at=int(time.time())),'selected_offer_expired'),
 ('different_name_same_sku',lambda v:v['offers'][0].update(name='다른 합성상품'),'selected_offer_terms_changed'),
 ('deadline_changed',lambda v:v['offers'][0].update(valid_until=v['offers'][0]['valid_until']-1),'selected_offer_terms_changed'),
 ('stale',lambda v:v.update(valid_until=int(time.time())),'stale_or_future_view')]:
 with Fixture() as f:
  f.stage();f.fresh_and_grant(mutation);o=f.apply();check('reject_fresh_'+label,o.get('reason')==reason and (f.root/'card.json').read_bytes()==f.before,observed=o)
with Fixture() as f:
 f.stage();f.fresh_and_grant();f.auth['details']['fresh_view_sha256']=f.source;f.writeauth();check('original_is_not_fresh',f.apply().get('reason')=='independent_fresh_view_required')
with Fixture() as f:
 f.stage();f.fresh_and_grant();f.auth['valid_until']=f.auth['issued_at'];f.writeauth();check('expired_authority_rejected',f.apply().get('reason')=='stale_or_future_authority')
with Fixture() as f:
 f.stage();f.fresh_and_grant();check('caller_price_approval_extra_rejected',f.call(APPLY,{'op':'apply','record_id':f.record,'price':1,'approved':True}).get('reason')=='invalid_request_fields')
 check('arbitrary_record_not_authorized',f.call(APPLY,{'op':'apply','record_id':'0'*64}).get('reason')=='publication_authority_conflict')
 with (f.root/'card_publication/lock').open('rb') as h:
  fcntl.flock(h,fcntl.LOCK_EX|fcntl.LOCK_NB);check('concurrent_writer_waits',f.apply()=={'status':'waiting','reason':'publisher_busy'})
 check('concurrent_wait_preserved_card',f.root.joinpath('card.json').read_bytes()==f.before)
with Fixture() as f:
 f.stage(['G00000001','G00000002','G00000003','G00000004']);f.fresh_and_grant();check('max_three_enforced',f.apply().get('reason')=='select_one_to_three_unique_skus')
with Fixture() as f:
 for row in f.view['offers']:row['name']='합성 '+'긴상품명'*25
 f.stage(['G'+str(i).zfill(8) for i in range(1,9)]);f.fresh_and_grant();check('description_max_1000_enforced',f.apply().get('reason')=='description_over_1000')
result={'ordinary_real_Toolbox_call_used':True,'kit_testing_flag_set_manually':False,'synthetic_Fake_source_only':True,'checks':checks,'totals':{g:{'passed':sum(x['passed'] for x in checks if x['group']==g),'failed':sum(not x['passed'] for x in checks if x['group']==g)} for g in sorted({x['group'] for x in checks})},'live_card_write':False,'market_calls':0,'model_calls':0,'keys_tokens_or_customer_data_loaded':False,'partial_IO_scope':'Exact pending-before/after-card persisted checkpoints are replayed; not a universal real filesystem fault-injection proof.'}
(ROOT/'ordinary-toolbox-qa-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'totals':result['totals'],'failed':[x for x in checks if not x['passed']]},ensure_ascii=False))
