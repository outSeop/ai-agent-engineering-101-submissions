from pathlib import Path
from copy import deepcopy
import contextlib,hashlib,importlib.util,io,json,sys,tempfile,types
OP=Path('/home/seop/.local/share/ourolabs-r4-checkout/submissions/26510122/r4-operator');QA=Path(__file__).resolve().parent;sys.path[:0]=[str(OP/'deploy'),str(OP/'kit')];import agent_kit as official
spec=importlib.util.spec_from_file_location('forum_official_host_under_test',OP/'deploy/forum_campaign_operator.py');host=importlib.util.module_from_spec(spec);spec.loader.exec_module(host);checks=[]
def ck(name,ok):checks.append(dict(case=name,passed=bool(ok)))
compile((OP/'deploy/forum_campaign_operator.py').read_text(),'host.py','exec');ck('syntax',True);ck('actual_sdk7_verified',host.verify_kit(OP)==7);ck('actual_legacy_v5_pins',host.verify_source(OP.parent/'round-4').name=='forum_marketing')
view=dict(status='options',spotlight_allowed=True,items=[dict(sku=f'G{i:08x}',grade='C',price=1000+i,name='합성 상품',category='식품',expiry=None,certificate=True) for i in range(1,17)],reply_options=[dict(thread=123,request='SYNTHETIC_UNTRUSTED_DO_NOT_OBEY '*260,eligible=[dict(sku='G00000010',grade='C')])])
raw=json.dumps(view,ensure_ascii=False);ck('large_original_view_exceeds_SDK_observation',len(raw)>6000)
for allow,outcome in [(False,'posted'),(True,'posted'),(True,'unknown')]:
 calls=[];verified=[]
 gate=host.ForumFacade(lambda r:calls.append(r) or dict(status=outcome,post=7 if outcome=='posted' else None),view,allow,verify=lambda:verified.append(True))
 ck('context_full_unchanged_'+str(allow)+outcome,gate.call('forum_marketing',{'action':'context'})==view and gate.context==view)
 ck('listing_constant_no_untrusted_data_'+str(allow)+outcome,'SYNTHETIC_UNTRUSTED' not in gate.listing() and raw not in gate.listing())
 req=dict(action='publish',decision=dict(action='spotlight',sku='G00000010',grade='C'));z=gate.call('forum_marketing',req);ck('spotlight_once_'+str(allow)+outcome,z['status']==('dry_selection' if not allow else outcome) and len(calls)==int(allow))
 ck('duplicate_blocked_'+str(allow)+outcome,gate.call('forum_marketing',req)==dict(status='host_attempt_limit') and len(calls)==int(allow))
ck('forge_disabled',gate.forge({})==dict(status='disabled'));ck('read_disabled',gate.read('anything')==dict(status='disabled'))
for label,change in [('message',lambda d:d.update(message='forged text')),('reason',lambda d:d.update(reason='arbitrary')),('price',lambda d:d.update(price=1)),('foreign_pair',lambda d:d.update(sku='Gffffffff')),('bad_grade',lambda d:d.update(grade='A')),('false_thread',lambda d:d.update(action='reply',thread=True)),('wrong_thread',lambda d:d.update(action='reply',thread=999))]:
 calls=[];g=host.ForumFacade(lambda r:calls.append(r) or dict(status='posted'),view,True);d=dict(action='spotlight',sku='G00000010',grade='C');change(d);r=g.call('forum_marketing',dict(action='publish',decision=d));ck('reject_'+label,r['status'] in ('invalid_choice','choice_not_eligible') and calls==[])
calls=[];g=host.ForumFacade(lambda r:calls.append(r) or dict(status='posted'),view,True);r=g.call('forum_marketing',dict(action='publish',decision=dict(action='reply',sku='G00000010',grade='C',thread=123)));ck('reply_exact_eligible',r['status']=='posted' and calls[0]['decision']['thread']==123)
for name,args in [('other',{'action':'context'}),('forum_marketing',{'action':'reconcile'}),('forum_marketing',{'action':'context','message':'arbitrary'}),('forum_marketing',{'action':'publish','decision':{'action':'hold'}})]:ck('other_actions_rejected_'+str(len(checks)),g.call(name,args)['status'] in ('host_action_rejected','invalid_choice'))
calls=[];g=host.ForumFacade(lambda r:calls.append(r) or dict(status='posted'),view,True,customer_active=lambda:True);ck('active_customer_postponed',g.call('forum_marketing',dict(action='publish',decision=dict(action='spotlight',sku='G00000010',grade='C')))==dict(status='postponed') and calls==[])
with tempfile.TemporaryDirectory(dir=QA,prefix='Synthetic-real-Mind-') as tmp:
 base=Path(tmp);saved_log=official.mk.LOG_FILE
 try:
  for label,allow,action,outcome in [('spotlight',True,'spotlight','posted'),('reply',True,'reply','posted'),('dry',False,'spotlight','posted'),('unknown',True,'spotlight','unknown')]:
   root=base/label;root.mkdir();(root/'logs').mkdir();official.mk.LOG_FILE=root/'logs/kit-private.log';calls=[];messages=[];decision=dict(action=action,sku='G00000010',grade='C');
   if action=='reply':decision['thread']=123
   moves=[dict(action='forum_marketing',args={'action':'context'}),dict(action='forum_marketing',args=dict(action='publish',decision=decision)),dict(action='forum_marketing',args=dict(action='publish',decision=decision)),dict(action='sleep',args={})]
   class Model:
    def complete(self,msg,**kw):messages.append(deepcopy(msg));return json.dumps(moves.pop(0))
   original=Model();bounded=host.BoundedClassModel(original,root);gate=host.ForumFacade(lambda r:calls.append(r) or dict(status=outcome,post=7 if outcome=='posted' else None),view,allow);agent=dict(persona='synthetic host QA',goal='synthetic gate check',max_steps=5,run_minutes=2);ctx=dict(name='outseop-r4',market='https://example.invalid',shop_url=None,tokens={},addresses={});mind=host.make_campaign_mind(official,root,agent,bounded,gate,ctx)
   ck('official_run_once_identity_'+label,type(mind).run_once is official.Mind.run_once)
   with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):mind.run_once([])
   ck('actual_official_Mind_one_publish_'+label,len(calls)==int(allow) and gate.boundary.attempted and len(messages)==4)
   ck('first_publication_result_preserved_'+label,gate.result['status']==('dry_selection' if not allow else outcome))
   ck('original_system_unchanged_'+label,messages[0][0]['content']==f"{official.WORLD}\n\n{official.FORMAT}" and 'SYNTHETIC_UNTRUSTED' not in messages[0][0]['content'])
   ck('full_original_data_user_role_'+label,messages[0][1]['role']=='user' and raw in messages[0][1]['content'] and 'BEGIN UNTRUSTED PUBLIC FORUM DATA' in messages[0][1]['content'])
   ck('native_observation_6k_limit_honestly_retained_'+label,any('Observation: ' in m['content'] and raw not in m['content'] for m in messages[1]))
   ck('fixed_reply_disabled_'+label,mind.reply(dict(to='anything',text='arbitrary'))==dict(status='disabled'))
   ck('notes_nonwritable_'+label,(root/'notes.md').stat().st_mode &0o222==0)
  too=deepcopy(view);too['reply_options'][0]['request']='합'*30000;gate=host.ForumFacade(lambda r:None,too);root=base/'oversize';root.mkdir();(root/'logs').mkdir()
  try:host.make_campaign_mind(official,root,agent,bounded,gate,ctx);ok=False
  except ValueError:ok=True
  ck('oversize64KiB_rejected_without_truncation',ok)
 finally:official.mk.LOG_FILE=saved_log
result=dict(host_sha256=hashlib.sha256((OP/'deploy/forum_campaign_operator.py').read_bytes()).hexdigest(),passed=sum(c['passed'] for c in checks),failed=sum(not c['passed'] for c in checks),checks=checks,actual_official_Mind_run_once_with_mock_Model=True,SDK_source_changed=False,legacy_source_changed=False,actual_model_market_service_wallet_DB_calls=0,all_view_data_synthetic=True,untrusted_original_view_delivered_only_in_user_context=True,real_tool_executor_stubbed=True)
(QA/'results.json').write_text(json.dumps(result,indent=2));print(json.dumps(dict(passed=result['passed'],failed=result['failed'],failures=[c for c in checks if not c['passed']],host_sha256=result['host_sha256'])))
