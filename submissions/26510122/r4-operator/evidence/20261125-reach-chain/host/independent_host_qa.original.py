from pathlib import Path
import importlib.util,sys,json,hashlib
from copy import deepcopy
ROOT=Path(__file__).resolve().parent
OP=ROOT.parents[1]
HOST=OP/'runtime/r3-stock-20261124-204104/agent-work/codex-r4/public_trial_preview_host.py'
HOST_SHA='86aff2808f0ba8d5035bdad90cbc9434f3be71fc45a5fac2fd636c2d2aa4484f'
assert hashlib.sha256(HOST.read_bytes()).hexdigest()==HOST_SHA
sys.path.insert(0,str(HOST.parent))
spec=importlib.util.spec_from_file_location('unchanged_preview_host',HOST);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
ns={};exec(compile((ROOT/'tools/plan_public_sku_trials/logic.py').read_bytes(),'unchanged_planner','exec'),ns)
checks=[]
def check(name,ok):checks.append({'case':name,'passed':bool(ok)})
def summary():return {'mode':'public_market_sample','requested_time':{'start':96400,'end':100000},'sample_time':{'start':96399,'end':99999},'coverage':'boundaries_observed','by_sku':[{'sku':'G00000001','name':'가상 계란','category':'식품>가상>계란','count':7},{'sku':'G00000002','name':'가상 요거트','category':'식품>가상>요거트','count':3}],'by_category':{'식품>가상>계란':7,'식품>가상>요거트':3},'sealed_count':0,'unclassified_count':0}
def make(now=100001):
 clock={'wall':now,'mono':50};calls=[]
 def execute(name,args):
  calls.append((name,deepcopy(args)))
  if name==mod.SUMMARY_TOOL:return {'ok':True,'result':summary()}
  return {'ok':True,'result':ns['run'](args,None)}
 return mod.Preview(execute,lambda:clock['mono'],lambda:clock['wall']),clock,calls
p,c,calls=make();o=p.call(mod.SUMMARY_TOOL,{});ref=o['observation_ref'];check('fresh_pinned_summary_reference_ready',o['status']=='observation_ready' and len(ref)>20)
for key,value in [('summary',summary()),('existing_skus',['G00000001']),('cash',1),('url','https://example.invalid'),('path','/tmp/none')]:
 before=len(calls);x=p.call(mod.PLAN,{'observation_ref':ref,'max_trials':3,key:value});check('reject_injected_'+key,x['status']=='invalid_arguments' and len(calls)==before)
for v in [True,0,9,1.5,'3']:
 check('reject_max_trials_'+repr(v),p.call(mod.PLAN,{'observation_ref':ref,'max_trials':v})['status']=='invalid_arguments')
check('wrong_reference_rejected',p.call(mod.PLAN,{'observation_ref':'synthetic-wrong','max_trials':3})['status']=='observation_unavailable')
out=p.call(mod.PLAN,{'observation_ref':ref,'max_trials':1});check('bounded_pure_plan_and_explicit_no_stock_exclusion',out['status']=='planning_only' and len(out['candidates'])==1 and out['inventory_exclusions_applied'] is False)
check('same_sample_resolved_host_side',calls[-1][1]=={'summary':summary(),'existing_skus':[]})
check('one_use_replay_rejected',p.call(mod.PLAN,{'observation_ref':ref,'max_trials':3})['status']=='observation_unavailable')
for label,delta in [('mono',150),('wall',151)]:
 p,c,_=make();o=p.call(mod.SUMMARY_TOOL,{});c[label]+=delta;check('expired_'+label+'_rejected',p.call(mod.PLAN,{'observation_ref':o['observation_ref'],'max_trials':3})['status']=='observation_unavailable')
for value in [99894,100151]:
 p,_,_=make(value);check('stale_or_future_summary_'+str(value),p.call(mod.SUMMARY_TOOL,{})['status']=='summary_stale')
p,c,calls=make()
for v in [True,59,86401,'3600']:
 check('invalid_window_'+repr(v),p.call(mod.SUMMARY_TOOL,{'window_seconds':v})['status']=='invalid_arguments')
check('summary_url_injection_rejected',p.call(mod.SUMMARY_TOOL,{'url':'https://example.invalid'})['status']=='invalid_arguments')
check('unknown_tool_rejected',p.call('pay',{})['status']=='invalid_arguments')
for perm in [{'wallet':['shop']},{'identity':['shop']}]:
 try:mod.NoWallet().grant('any',perm,10);ok=False
 except PermissionError:ok=True
 check('no_wallet_'+next(iter(perm)),ok)
base=summary();envelope={'ok':True,'result':ns['run']({'summary':base,'existing_skus':[]},None)}
for field,value in [('sku','0x'+'ab'*20),('observed_count',11),('planned_units',2)]:
 bad=deepcopy(envelope);bad['result']['candidates'][0][field]=value;check('reject_output_'+field,mod.Preview.project_plan(bad,base,3)['status']=='preview_unavailable')
bad=deepcopy(envelope);bad['result']['unexpected']='x';check('reject_output_extra',mod.Preview.project_plan(bad,base,3)['status']=='preview_unavailable')
for tool in mod.PINNED:
 mod.bundle(OP/'runtime/public-trial-preview-20261125-0950/tools',tool)
check('actual_copied_bundles_match_reviewed_v2_hashes',True)
session=OP/'runtime/public-trial-preview-20261125-0950'
actions=[];observations=[]
for line in (session/'logs/react.jsonl').read_text().splitlines():
 record=json.loads(line);action=record.get('action');args=record.get('args',{})
 observation=record.get('observation');observation=json.loads(observation) if isinstance(observation,str) else observation
 actions.append({'action':action,'timestamp':record.get('ts'),'argument_field_names':list(args)})
 if observation:
  observations.append({k:v for k,v in observation.items() if k!='observation_ref'})
check('actual_class_action_chain', [x['action'] for x in actions]==[mod.SUMMARY_TOOL,mod.PLAN,'sleep'])
actual=json.loads((session/'summary.json').read_text());check('actual_preview_matches_logged_observation',actual['preview']==observations[-1])
result={'host_sha256':HOST_SHA,'checks':checks,'passed':sum(x['passed'] for x in checks),'failed':sum(not x['passed'] for x in checks),'synthetic_host_tests_only':True,'new_market_calls':0,'new_model_calls':0,'private_model_thoughts_exported':False,'actual_existing_run':{'summary':actual,'actions_without_thoughts_or_reference':actions,'public_observations_without_reference':observations},'scope':'Bounded source-pinned public preview only; general planner inputs remain unapproved; no stock lookup or purchase.'}
(ROOT/'independent-host-qa-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'passed':result['passed'],'failed':result['failed'],'actions':[x['action'] for x in actions],'new_market_calls':0,'new_model_calls':0}))
