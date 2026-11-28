"""Independent common-front ASGI replay. Maintained stub-only fixture support; no listener, inference auth or real Model.
Uses verified public source assets and an owned synthetic runtime root only.
"""
from pathlib import Path
from contextlib import redirect_stdout,redirect_stderr
from copy import deepcopy
from hashlib import sha256,sha1
from uuid import uuid4
import re
import argparse,importlib.util,json,os,stat,sys,time
GUEST={'outcome':'context','inventory':[],'verified_account':False,'redeemable_mileage':0,'preferences':[],'wait':None,'wait_discount':0,'prior_offer':None,'transfer_reference_present':False}
CASES={
 'unsupported-compound-repeat':'소이밀크와 게이밍체어 재고와 가격 보여 주세요. 소이밀크 재고도 알려 주세요. 결제는 나중에 할게요.',
 'compound':'소이밀크와 게이밍체어 재고와 가격 보여 주세요. 결제는 나중에 할게요.',
 'repeated-positive':'소이밀크 재고와 가격 보여 주세요. 소이밀크는 어떤 상품이 있나요? 결제는 나중에 할게요.'}
ACTION={'action':'search_similar_products','args':{'groups':[{'product_phrase':'소이밀크','queries':['두유']},{'product_phrase':'게이밍체어','queries':['의자']}]}}
def encode(x):return (json.dumps(x,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode()
def digest(x):return sha256(x).hexdigest()
def fixed(path,raw):
 path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
 with path.open('xb') as f:f.write(raw)
 path.chmod(0o400)
def module(name,path):
 sp=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(sp);sys.modules[name]=m;sp.loader.exec_module(m);return m
def protected(path):
 path=Path(path);s=path.lstat()
 if path.resolve(strict=True)!=path or not stat.S_ISREG(s.st_mode) or s.st_uid!=os.getuid() or s.st_nlink!=1 or s.st_mode&0o022:raise ValueError('unprotected QA source')
 return path.read_bytes()
def verify_component(folder,pin,field):
 raw=protected(folder/'MANIFEST.json');assert digest(raw)==pin;meta=json.loads(raw)
 for name,h in meta[field].items():
  rel=Path(name);assert not rel.is_absolute() and '..' not in rel.parts;assert digest(protected(folder/rel))==h
 return meta
def verify_build(operator,path,pin,expected_semantic=9):
 operator=Path(operator).resolve(strict=True)
 path=Path(path)
 if path.resolve(strict=True)!=path:raise ValueError('receipt must be canonical, not a symlink')
 assert path.name=='BUILD.json' and path.parent.parent==operator/'runtime/releases'
 raw=protected(path);assert digest(raw)==pin;r=json.loads(raw);root=path.parent
 assert r['schema']=='r4-host-build.v1' and root.name==r['release_id'] and r['native_asset_bytes_preserved'] is True and r['business_sources_modified_by_builder'] is False
 runtime=Path(r['runtime_path']);front=Path(r['front_path']);assert runtime==root/'runtime' and front==root/'front'
 runtime_meta=verify_component(runtime,r['runtime_manifest_sha256'],'file_sha256');front_meta=verify_component(front,r['front_manifest_sha256'],'files')
 assert r['native_semantic_version']==expected_semantic
 for folder,tool in [('catalogue','public_catalogue'),('semantic','semantic_candidates')]:
  record=json.loads(protected(runtime/folder/'forge.json'));assert record['tool']==tool and record['sha256']=={name:digest(protected(runtime/folder/name)) for name in ['logic.py','test.py','permission.yml']}
 assert len(json.loads(protected(operator/'sources/upstream.json'))['files'])==7
 for row in json.loads(protected(operator/'sources/upstream.json'))['files']:
  data=protected(operator/'kit'/row['name']);assert sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()==row['upstream_git_blob_sha']
 sys.path[:0]=[str(front),str(runtime),str(operator/'kit'),str(operator.parent/'round-4/codex-r4')]
 runner=module('common_front_qa_runner',front/'run_front_edge.py');edge=runner.reviewed_front(r['front_manifest_sha256']);configmod=module('common_front_qa_config',front/'config.py');config=configmod.load_pinned(front,front_meta,operator=operator)
 assert config.runtime_path==runtime and config.runtime_manifest_sha256==r['runtime_manifest_sha256']
 runner.verify(operator,runtime,r['runtime_manifest_sha256'],config)
 return r,runtime,front,runner,edge,config

def public_source(observed):
 if type(observed) is not int or observed<=0:raise ValueError('explicit positive fixture timestamp required')
 units=[]
 for i in range(1,118):
  name='두유 12팩' if i==1 else '의자' if i==2 else '합성 보관용품 '+str(i)
  units.append({'unit_ref':digest(('synthetic-public-unit-'+str(i)).encode())[:32],'sku':'G'+format(i,'08x'),'name':name,'category_path':['식품','두유'] if i==1 else ['가구','의자'] if i==2 else ['생활','보관용품'],'state':'available','grade':'B' if i==1 else 'A','price_credits':8010 if i==1 else 20000 if i==2 else 1000+i,'standard_fee_credits':None,'expires_at':observed+86400 if i==1 else None})
 document={'schema':'outseop-r4.customer-offers.v1','shop':'outseop-r4','observed_at':observed,'valid_until':observed+150,'units':units}
 return encode(document),document
class NoWallet:
 def grant(self,*args):raise PermissionError('no financial/network signer capability')
class StubModel:
 def __init__(self,case):self.calls=0;self.case=case
 def complete(self,messages,**kwargs):
  self.calls+=1;action=deepcopy(ACTION)
  if self.case=='repeated-positive':action['args']['groups']=action['args']['groups'][:1]
  return json.dumps(action,ensure_ascii=False)

def run_case(operator,out,case,build,runtime,frontdir,runner,edge,config,fixture_clock):
 operator=Path(operator).resolve(strict=True)
 import agent_kit as official
 from starlette.testclient import TestClient
 out.mkdir(mode=0o700)
 for n in ['logs','.kit','scratch','tools','host_inputs','gate']:(out/n).mkdir(mode=0o700)
 raw,document=public_source(fixture_clock);fixed(out/'host_inputs/customer_offer_context.json',raw)
 # Only the public-code name normalizer is imported, never original agent/persona/DB/identity.
 import dispatcher
 base=deepcopy(GUEST);base['inventory']=[{'sku':row['sku'],'name':dispatcher.public_product_name(row['name']),'grade':row['grade'],'category':None,'reference_price':row['price_credits'],'min_base':row['price_credits'],'preferred_price':row['price_credits'],'stock_status':'available','available':True,'wait_eligible':False} for row in document['units'][:30]]
 original_hash=digest(encode(base));fixed(out/'agent.json',encode({'llm':{'base':'market'},'goal':'synthetic no-wallet common-front replay'}));fixed(out/'host_inputs/broker_context_base.json',encode(base))
 # Exact boundary tools, not production state or financial executors.
 origins={name:operator.parent/'round-4/tools'/name for name in ('a2a_info','shop_info')}
 if callable(getattr(runner,'pinned_forum_validator',None)) and (runtime/'forum_marketing').is_dir():
  origins['forum_marketing']=runtime/'forum_marketing'
  origins['publish_shop_info']=operator.parent/'round-4/tools/publish_shop_info'
 for name,origin in origins.items():
  record=json.loads(protected(origin/'forge.json'))
  for leaf in ('logic.py','permission.yml','test.py','forge.json'):
   data=protected(origin/leaf)
   if leaf!='forge.json':assert digest(data)==record['sha256'][leaf]
   fixed(out/'tools'/name/leaf,data)
 worker=module('qa_catalogue_worker',runtime/'bounded_public_catalogue_host.py');protocol=module('qa_catalogue_protocol',runtime/'public_catalogue_protocol.py');request=module('qa_catalogue_request',runtime/'public_catalogue_request_host.py');composition=module('qa_catalogue_composition',runtime/'public_catalogue_composition_candidate.py')
 pins={leaf:digest(protected(runtime/'catalogue'/leaf)) for leaf in ['logic.py','permission.yml','test.py','forge.json']};semanticpins={leaf:digest(protected(runtime/'semantic'/leaf)) for leaf in pins};worker.instruction_from(runtime/'catalogue',pins,official);worker.instruction_from(runtime/'semantic',semanticpins,official,tool_name='semantic_candidates')
 native=worker.BoundedPublicCatalogue(runtime/'catalogue',operator/'kit',out/'scratch',pins,semantic_source=runtime/'semantic',semantic_pins=semanticpins)
 native_results=[];native_arguments=[];legacy=[];model_metrics=[];phases=[];supplies=[];assembled={}
 def supplier():
  supplies.append(True);assert (out/'host_inputs/customer_offer_context.json').read_bytes()==raw;return raw,deepcopy(document)
 def invoke(**kwargs):
  assert kwargs['snapshot']==raw;native_arguments.append(deepcopy(kwargs['args']));result=native(**kwargs);native_results.append((kwargs['args']['op'],result));return result
 def stock(raw,doc):return [{'sku':r['sku'],'grade':r['grade'],'stock_status':r['state'],'expires_at':r['expires_at'],'preferred_price':r['price_credits']} for r in doc['units']]
 def factory(execute):
  def explicit_broker_mask(text):
   if 'app' not in assembled:raise ValueError('broker hook unavailable before app assembly')
   return assembled['app'].loaded_broker.mask(text)
  return request.ScopedPublicCatalogue(supplier,invoke,protocol.CatalogueProtocol(explicit_broker_mask),composition.SEARCH_INSTRUCTION,stock_state_supplier=stock)
 def toolbox_factory(parent,isolated,ctx):
  assert Path(isolated)==out
  class Box(parent):
   def decision_tool(self,args):
    legacy.append(deepcopy(args))
    if args.get('action')!='context':raise PermissionError('all financial executors forbidden')
    return deepcopy(base)
  return Box(out,ctx)
 chosen=StubModel(case)
 class Instrument:
  def complete(self,messages,**kwargs):
   pages=[]
   def walk(x):
    if isinstance(x,dict):
     if x.get('status')=='ready' and isinstance(x.get('rows'),list) and 'catalogue' in x:pages.append(x)
     for y in x.values():walk(y)
    elif isinstance(x,list):
     for y in x:walk(y)
   for msg in messages:
    try:walk(json.loads(msg['content']))
    except (ValueError,TypeError):pass
   assert all(len(p['rows'])<=8 and len(json.dumps(p,ensure_ascii=False,separators=(',',':')))<=5500 for p in pages)
   model_metrics.append({'prompt_characters':sum(len(x['content']) for x in messages),'page_rows':[len(p['rows']) for p in pages],'max_tokens':kwargs.get('max_tokens'),'timeout':kwargs.get('timeout')});return chosen.complete(messages,**kwargs)
 admission=module('qa_common_admission',frontdir/'admission_gate.py').AdmissionGate(out/'gate/admission.json',owner=os.getuid());admission.initialize_closed()
 ctx={'name':'outseop-r4','market':'https://market.ourolabs.ai','shop_url':'https://synthetic-local-only.invalid','tokens':{},'addresses':{},'signer':NoWallet()};official.mk.LOG_FILE=out/'logs/SDK-private.log'
 async def forbidden_old(scope,body):raise AssertionError('old proxy forbidden in isolated replay')
 app=runner.assemble(official,operator,runtime,build['runtime_manifest_sha256'],ctx,Instrument(),trace=out/'logs/front-private.jsonl',old_request=forbidden_old,options_override={'catalogue_source_factory':factory,'public_phase_report':phases.append},toolbox_factory=toolbox_factory,_front=edge,admission=admission,config=config,isolated_root=out,host_state_db=out/'tasks.sqlite3',persistent_engine=True)
 if not hasattr(app,'loaded_broker'):raise ValueError('reviewed assembler must expose loaded_broker; no legacy fallback')
 assembled['app']=app
 if Path(app.host_state_db.path)!=out/'tasks.sqlite3':raise ValueError('persistent test state escaped isolated root')
 app.host_state_db.set_maintenance(True)
 payload={'jsonrpc':'2.0','id':uuid4().hex,'method':'SendMessage','params':{'message':{'messageId':uuid4().hex,'role':'ROLE_USER','parts':[{'text':CASES[case]}],'metadata':{'from':'synthetic-unverified-guest'}}}}
 begin=time.monotonic()
 with TestClient(app,base_url=ctx['shop_url']) as client:
  closed=client.post('/',headers={'A2A-Version':'1.0'},json=payload);assert closed.status_code==503 and not model_metrics and admission.read()['admissions']==0
  app.host_state_db.set_maintenance(False);response=client.post('/',headers={'A2A-Version':'1.0'},json=payload)
 elapsed=round(time.monotonic()-begin,4);body=response.json();result=body.get('result',{});task=result.get('task',result);reply=task.get('status',{}).get('message',{}).get('parts',[{}])[0].get('text')
 verified=[r for op,r in native_results if op in ('render','fallback','prepared_fallback','semantic_candidates') and isinstance(r,dict) and r.get('status')=='rendered'];exact=bool(verified and verified[-1].get('reply')==reply)
 safe={'case':case,'status':'verified_genuine_ASGI_final_reply' if response.status_code==200 and exact and len(model_metrics)==1 else 'not_verified','http_status':response.status_code,'final_reply_exact_genuine':exact,'reply_sha256':digest(reply.encode()) if isinstance(reply,str) else None,'reply_characters':len(reply) if isinstance(reply,str) else 0,'native_operations':[op for op,r in native_results],'native_semantic_version':build['native_semantic_version'],'source_rows':117,'fixture_observed_at':fixture_clock,'fixture_food_expires_at':document['units'][0]['expires_at'],'source_snapshot_sha256':digest(raw),'cross_run_reply_hash_fixed':False,'SDK_clock_unchanged':True,'legacy_fixture_rows':30,'source_truncated':False,'model_calls':len(model_metrics),'Model_metrics':model_metrics,'phase_metrics':phases,'maintenance_closed_503_without_Model':True,'legacy_admission_used':False,'legacy_admission_count':admission.read()['admissions'],'durable_current_owner_indexed':app.host_state_db.transport_route(task.get('id'))=='current','legacy_context_calls':sum(x.get('action')=='context' for x in legacy),'financial_executor_attempts':sum(x.get('action')!='context' for x in legacy),'legacy_fixture_unchanged':digest(encode(base))==original_hash,'isolated_root_for_agent_mind_app_toolbox':True,'persistent_engine':True,'fixture_SQLiteTaskStore':type(app.store).__name__,'persistent_DB_isolated':Path(app.host_state_db.path)==out/'tasks.sqlite3','tool_tokens':0,'tool_addresses':0,'NoWallet':True,'production_identity_persona_DB_log_reads':0,'actual_Model_called':False,'actual_market_API_POST_pay_DB_service_calls':0,'listener_started':False,'total_transport_seconds':elapsed,'bound_runtime_manifest_sha256':build['runtime_manifest_sha256'],'bound_front_manifest_sha256':build['front_manifest_sha256']}
 expected=deepcopy(ACTION)
 if case=='repeated-positive':expected['args']['groups']=expected['args']['groups'][:1]
 semantic_args=[a for a in native_arguments if a.get('op')=='semantic_candidates']
 semantic_results=[r for operation,r in native_results if operation=='semantic_candidates']
 safe['semantic_native_status']=semantic_results[-1].get('status') if semantic_results else None
 safe['semantic_native_reason']=semantic_results[-1].get('reason') if semantic_results else None
 safe['stub_wiring']={'stub_completion_count':chosen.calls,'predetermined_action':expected['action'],'actual_native_groups_equal_stub':len(semantic_args)==1 and semantic_args[0].get('groups')==expected['args']['groups'],'complete_original_text_forwarded':len(semantic_args)==1 and semantic_args[0].get('text')==CASES[case],'actual_Model_semantic_interpretation_tested':False}
 fixed(out/'safe-result.json',encode(safe));fixed(out/'logs/asgi-response-private.json',encode(body));fixed(out/'logs/native-results-private.json',encode(native_results));return safe
