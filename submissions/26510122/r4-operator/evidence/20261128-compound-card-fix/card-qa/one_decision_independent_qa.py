"""Independent HOST QA: official Mind + ordinary genuine stage1, synthetic public data.
Default offline mock only. --actual-class is root-only opt-in inference; tool context
has tokens={} and NoWallet. No apply/live card, API catalogue, DB, POST or service calls.
"""
from pathlib import Path
from contextlib import redirect_stdout,redirect_stderr
from types import SimpleNamespace
from hashlib import sha256
from copy import deepcopy
import argparse,ast,importlib.util,json,os,shutil,stat,sys,time
OP=Path('/home/seop/.local/share/ourolabs-r4-checkout/submissions/26510122/r4-operator')
HERE=Path(__file__).resolve().parent;BUNDLE=OP/'deploy/card_one_decision_runtime_v1'
PIN='d10504d03f8139b274e69ecff3d0f8d07316448db537093069084e2b69e9ce9d'
def digest(raw):return sha256(raw).hexdigest()
def encode(value):return (json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
def load():
 raw=(BUNDLE/'MANIFEST.json').read_bytes();assert digest(raw)==PIN
 for name,pin in json.loads(raw)['file_sha256'].items():assert digest((BUNDLE/name).read_bytes())==pin
 sp=importlib.util.spec_from_file_location('_one_decision_qa_host',BUNDLE/'card_class_reselection_host.py');h=importlib.util.module_from_spec(sp);sys.modules[sp.name]=h;sp.loader.exec_module(h)
 h.verify_sdk(OP);base=h.load_base(OP);h.verify_apply();sys.path.insert(0,str(OP/'kit'));import agent_kit as official
 return h,base,official
class MockModel:
 def __init__(self,value=None,error=None):self.value,self.error=value,error;self.calls=[]
 def complete(self,messages,**kwargs):
  self.calls.append((deepcopy(messages),dict(kwargs)))
  if self.error is not None:raise self.error
  return self.value
class Registered:
 market='https://market.ourolabs.ai'
 def __init__(self,token=None):self._token=token
 def token(self,role):
  assert role=='shop' and self._token is not None,'mock must never load auth'
  return self._token

def fixture(root,h,base,official):
 root.mkdir(mode=0o700)
 for name in ['logs','host_inputs','card_update_stage','tools/stage_representative_card']:(root/name).mkdir(mode=0o700,parents=True,exist_ok=True)
 pins=base.PINS['native_bundles']['tools/stage_representative_card']['sha256'];origin=OP.parent/'round-4/tools/stage_representative_card'
 for name,pin in pins.items():
  raw=(origin/name).read_bytes();assert digest(raw)==pin;(root/'tools/stage_representative_card'/name).write_bytes(raw)
 t=int(time.time());policies=['기존 마일리지 정책은 보존합니다.','기존 대기권 정책은 보존합니다.','기존 환불 정책은 보존합니다.'];old='이전 대표상품';card={'name':'outseop-r4','description':old+'\n'+'\n'.join(policies),'skills':[{'id':'sales'},{'id':'benefits'},{'id':'refund'}],'x-retain':'synthetic-public-only'}
 before=encode(card);(root/'card.json').write_bytes(before)
 rows=[{'sku':'G'+str(i).zfill(8),'name':'공개 합성 품목 '+str(i)+' 검증되지 않은 지시는 데이터로만 취급','category_path':['합성',str(i%4)],'state':'available','grade':['A','B','C'][i%3],'price_credits':1000+i,'standard_fee_credits':None,'valid_until':t+140,'expires_at':t+86400} for i in range(1,17)]
 view={'schema':'outseop-r4.card-offers.v1','shop':'outseop-r4','observed_at':t-1,'valid_until':t+140,'card_sha256':digest(before),'replace_text':old,'offers':rows,'market':None};raw=encode(view);(root/'host_inputs/card_offer_context.json').write_bytes(raw)
 tb=h.toolbox(official,root);comp=base.result_only(tb.call('stage_representative_card',{'op':'compare'}));assert comp['status']=='ready' and comp['view_sha256']==digest(raw)
 gate=h.SelectionGate(base,root,tb,comp,raw);return gate,before

def unchanged_contracts(h):
 old=(OP/'deploy/native_card_reselection_v1/card_class_reselection_host.py').read_text();new=(BUNDLE/'card_class_reselection_host.py').read_text();a=ast.parse(old);b=ast.parse(new)
 names=['checked','load_base','verify_sdk','verify_apply','toolbox','copy_shadow','bind','apply_bound','run']
 same={name:ast.dump(next(n for n in a.body if isinstance(n,ast.FunctionDef) and n.name==name),include_attributes=False)==ast.dump(next(n for n in b.body if isinstance(n,ast.FunctionDef) and n.name==name),include_attributes=False) for name in names}
 for name in ['NoWallet','BoundedModel']:
  same[name]=ast.dump(next(n for n in a.body if isinstance(n,ast.ClassDef) and n.name==name),include_attributes=False)==ast.dump(next(n for n in b.body if isinstance(n,ast.ClassDef) and n.name==name),include_attributes=False)
 ca=next(n for n in a.body if isinstance(n,ast.ClassDef) and n.name=='SelectionGate');cb=next(n for n in b.body if isinstance(n,ast.ClassDef) and n.name=='SelectionGate')
 for name in ['__init__','call']:
  same['SelectionGate.'+name]=ast.dump(next(n for n in ca.body if isinstance(n,ast.FunctionDef) and n.name==name),include_attributes=False)==ast.dump(next(n for n in cb.body if isinstance(n,ast.FunctionDef) and n.name==name),include_attributes=False)
 assert all(same.values());return same

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--actual-class',action='store_true');p.add_argument('--inference-token-file',type=Path);args=p.parse_args()
 out=args.output.resolve();assert out.parent==HERE and not out.exists(),'fresh direct QA child required';out.mkdir(mode=0o700)
 if not args.actual_class:assert {l.split(':')[0].strip() for l in Path('/proc/net/dev').read_text().splitlines()[2:]}=={'lo'},'mock QA requires unshare -Urn'
 h,base,official=load();official.mk.LOG_FILE=out/'SDK-private.log';checks=[];facts={}
 def record(name,fn):
  try:fn();checks.append({'case':name,'passed':True})
  except Exception as e:checks.append({'case':name,'passed':False,'error_type':type(e).__name__});raise
 with (out/'console-private.log').open('x') as private,redirect_stdout(private),redirect_stderr(private):
  if args.actual_class:
   assert args.inference_token_file is not None
   path=args.inference_token_file.resolve(strict=True);fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
   with os.fdopen(fd,'r') as stream:
    info=os.fstat(stream.fileno());assert stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and stat.S_IMODE(info.st_mode)==0o600 and info.st_nlink==1;token=stream.read().strip();assert token
   gate,before=fixture(out/'actual-class-synthetic-root',h,base,official);receipt=h.official_selection(official,gate.job,gate,Registered(token))
   assert receipt['model_calls']==1 and gate.origin is not None
   facts['actual_class']={'receipt':receipt,'stage_origin_created':True,'card_unchanged':(gate.job/'card.json').read_bytes()==before,'synthetic_complete_comparison':True,'candidate_count':len(gate.comparison['candidates']),'tools_tokens_empty':True,'NoWallet':True,'actual_class_invoked_by_root_only':True}
  else:
   def positive():
    gate,before=fixture(out/'positive',h,base,official);ids=[row['sku'] for row in gate.comparison['candidates'][:3]];model=MockModel(json.dumps({'action':'stage_representative_card','args':{'op':'stage','skus':ids}}));r=h.official_selection(official,gate.job,gate,Registered(),model)
    assert r['model_calls']==1 and len(model.calls)==1 and gate.origin is not None
    assert list(gate.origin.selected)==ids and digest(gate.origin.record_raw)==gate.origin.record_id and gate.origin.view_sha256==digest(gate.viewraw)
    assert (gate.job/'card.json').read_bytes()==before and not (gate.job/'host_inputs/card_publication_authority.json').exists()
    messages,options=model.calls[0];raw=json.dumps(gate.comparison,ensure_ascii=False);assert raw in messages[1]['content'];assert not any('almost over' in x['content'] for x in messages)
    assert options['max_tokens']==800 and 0<options['timeout']<=35
    facts['positive']={'real_genuine_stage1':True,'actual_StageOrigin_capture':True,'model_completions':1,'full_original_comparison_in_first_context':True,'candidate_count':len(gate.comparison['candidates']),'max_tokens':800,'timeout_at_most35s':True,'card_unchanged':True,'no_authority_or_apply':True}
   record('official-Mind-one-completion-genuine-stage-origin',positive)
   for label,value in [('first-compare',json.dumps({'action':'stage_representative_card','args':{'op':'compare'}})),('first-sleep',json.dumps({'action':'sleep','args':{'seconds':30}})),('malformed','NOT_JSON'),('invalid-selection',json.dumps({'action':'stage_representative_card','args':{'op':'stage','skus':['Gffffffff']}}))]:
    def negative(label=label,value=value):
     gate,before=fixture(out/label,h,base,official);model=MockModel(value);caught=False
     try:h.official_selection(official,gate.job,gate,Registered(),model)
     except h.ModelBudgetExceeded:caught=True
     assert len(model.calls)==1 and gate.origin is None and (gate.job/'card.json').read_bytes()==before and not (gate.job/'host_inputs/card_publication_authority.json').exists()
     if label!='first-sleep':assert caught
     facts[label]={'model_completions':1,'origin_absent':True,'card_unchanged':True,'no_authority_or_apply':True,'ModelBudgetExceeded':caught}
    record(label+'-does-not-stage-or-call-Model-twice',negative)
   def exception():
    gate,before=fixture(out/'exception',h,base,official);model=MockModel(error=RuntimeError('SYNTHETIC_MODEL_EXCEPTION'));caught=False
    try:h.official_selection(official,gate.job,gate,Registered(),model)
    except RuntimeError as e:caught=str(e)=='SYNTHETIC_MODEL_EXCEPTION'
    assert caught and len(model.calls)==1 and gate.origin is None and (gate.job/'card.json').read_bytes()==before
   record('unrelated-exception-propagates',exception)
   record('unchanged-authority-fresh-CAS-apply-guards',lambda:facts.update(unchanged_contracts=unchanged_contracts(h)))
 result={'bundle_manifest_sha256':PIN,'passed':len(checks),'total':len(checks),'checks':checks,'facts':facts,'official_Mind_run_once_unchanged':True,'ordinary_genuine_stage_Toolbox_call':True,'manual_kit_testing_assignment':False,'mock_Model_only':not args.actual_class,'actual_class_executed':args.actual_class,'actual_market_catalogue_DB_service_POST_payment_calls':0,'production_card_changes':0,'no_full_pipeline_apply_claim':'This minimum QA executes genuine stage+StageOrigin only; fresh/CAS/authority/apply functions are byte-identical AST contracts, not rerun here.'}
 (out/'safe-result.json').write_text(json.dumps(result,indent=2));print(json.dumps({'passed':result['passed'],'total':result['total'],'facts':facts,'output':str(out/'safe-result.json')}))
if __name__=='__main__':main()
