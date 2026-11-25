"""Original SDK cmd_run + actual managed construction; all external effects mocked."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from contextlib import ExitStack
import importlib.util,json,sys,socket,tempfile,threading,time as real_time
OP=Path('/home/seop/.local/share/ourolabs-r4-checkout/submissions/26510122/r4-operator')
sys.path[:0]=[str(OP/'kit'),str(OP/'deploy/public_catalogue_runtime_v3c'),str(OP.parent/'round-4/codex-r4'),str(OP/'deploy')]
import agent_kit as sdk
import managed_runtime_public_catalogue_host_candidate as managed
import forum_campaign_operator as campaign
spec=importlib.util.spec_from_file_location('startup_hook',Path(__file__).with_name('r4_forum_official_background_host.py'));host=importlib.util.module_from_spec(spec);spec.loader.exec_module(host)
with tempfile.TemporaryDirectory() as directory:
 op=Path(directory)/'operator';op.mkdir();root=Path(directory)/'shop';root.mkdir();(root/'agent.json').write_text('{}');stages=[];results=[];calls=[];moves=iter([{'action':'forum_marketing','args':{'action':'publish','decision':{'action':'spotlight','sku':'G01234567','grade':'B'}}},{'action':'sleep','args':{}}])
 view={'status':'options','spotlight_allowed':True,'items':[{'sku':'G01234567','grade':'B','name':'SYNTHETIC small pack','spotlight_eligible':True}],'reply_options':[]}
 def atomic(args):
  calls.append(args)
  return {'status':'nothing_to_reconcile'} if args['action']=='reconcile' else view if args['action']=='context' else {'status':'dry_selection'}
 tools=SimpleNamespace(bind_decision_model=lambda *a:None,stock_executor=lambda a:None,tools={'forum_marketing':{}},forum_executor=atomic,refresh_public_card=lambda:None)
 _,base,_=managed.managed_classes(sdk,enable_stock=True)
 real_mind=sdk.Mind;native_sdk=SimpleNamespace(Mind=real_mind)
 class Main(base):
  def __init__(self,root,agent,model,toolbox,ctx,roles):
   super().__init__(root,agent,model,toolbox,ctx,roles)
   assert set(ctx)=={'market','name','tokens','addresses','signer'} and ctx['tokens']=={}
   self.bg=host.install_tick(native_sdk,self.marketing_coordinator,op,root,agent,model,ctx,campaign=campaign)
 def construct(*args):
  stages.append('construct');answer=Main(*args);return answer
 token={}
 def join(role,name,key,url):
  assert stages==['construct'] and url=='https://example.invalid';stages.append('join');token[role]='SYNTHETIC_NOT_REAL_TOKEN';return {'name':name,'round':4}
 market=SimpleNamespace(base='https://market.ourolabs.ai',token=token,join=join,c=SimpleNamespace(get=lambda url:SimpleNamespace(json=lambda:{})))
 def start(target,daemon):results.append(target.__self__.marketing_coordinator.tick())
 args=SimpleNamespace(dir=root,buyer_only=False,with_buyer=False,market=market.base,owner=None,name='outseop-r4',port=18000,tunnel=False,public_url='https://example.invalid',app=False)
 with ExitStack() as stack:
  for obj,fields in [(sdk,dict(Model=lambda *a:SimpleNamespace(complete=lambda *a,**k:json.dumps(next(moves))),Toolbox=lambda *a:tools,Mind=construct,Signer=lambda *a:object(),serve=lambda *a:None,agent_app=lambda *a:None,threading=SimpleNamespace(Lock=threading.Lock,Thread=lambda **kw:SimpleNamespace(start=lambda:start(**kw))),time=SimpleNamespace(time=real_time.time,strftime=real_time.strftime,sleep=lambda *_:(_ for _ in ()).throw(KeyboardInterrupt())),log=lambda *a:None)),(sdk.mk,dict(Market=lambda *a:market,load_key=lambda *a:SimpleNamespace(address='0x'+'2'*40),wait_card=lambda *a:True,ignore_pem=lambda *a:None)),(socket.socket,dict(connect=lambda *a:(_ for _ in ()).throw(AssertionError('network forbidden'))))]:stack.enter_context(patch.multiple(obj,**fields))
  sdk.cmd_run(args)
 assert stages==['construct','join'] and len(results)==1 and results[0]['status']=='dry_selection' and results[0]['publication_attempts']==1
 assert [x['action'] for x in calls]==['reconcile','context','publish'] and results[0]['model_calls']==2
 print(json.dumps({'original_cmd_run':True,'actual_managed_constructor':True,'initial_context_keys_exact':True,'shop_url_absent_before_join':True,'same_context_updated_after_join':True,'original_Mind_run_once':True,'mock_Model_calls':2,'mock_publish_calls':1,'actual_Model_market_post_calls':0}))
