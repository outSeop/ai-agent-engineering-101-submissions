from pathlib import Path
import contextlib,hashlib,importlib.util,io,json,sys,tempfile,types
from unittest.mock import patch
OP=Path('/home/seop/.local/share/ourolabs-r4-checkout/submissions/26510122/r4-operator');QA=Path(__file__).resolve().parent;sys.path[:0]=[str(OP/'deploy'),str(OP/'kit')];import agent_kit as sdk
spec=importlib.util.spec_from_file_location('host_main_with_actual_Mind',OP/'deploy/forum_campaign_operator.py');host=importlib.util.module_from_spec(spec);spec.loader.exec_module(host);checks=[]
def ck(name,ok):checks.append(dict(case=name,passed=bool(ok)))
scenarios=[('dry',False,'spotlight','posted',False,'nothing_to_reconcile',False),('spotlight',True,'spotlight','posted',False,'nothing_to_reconcile',False),('reply',True,'reply','posted',False,'nothing_to_reconcile',False),('unknown',True,'spotlight','unknown',False,'nothing_to_reconcile',False),('foreground',True,'spotlight','posted',True,'nothing_to_reconcile',False),('reconcile_unknown',True,'spotlight','posted',False,'unknown',False),('oversize',True,'spotlight','posted',False,'nothing_to_reconcile',True)]
with tempfile.TemporaryDirectory(dir=QA,prefix='Synthetic-official-main-') as tmp:
 base=Path(tmp);op=base/'operator';(op/'runtime').mkdir(parents=True);(op/'kit').mkdir();(base/'round-4/codex-r4').mkdir(parents=True);oldlog=sdk.mk.LOG_FILE
 try:
  for label,allow,kind,outcome,active,recovery,oversize in scenarios:
   calls=[];models=[];modelcalls=[];httpgets=[];view=dict(status='options',spotlight_allowed=True,items=[dict(sku='Gabcdefab',grade='C',price=1000,name='합성 상품',category='식품')],reply_options=[dict(thread=123,request='합성 요청'+('가'*30000 if oversize else ''),eligible=[dict(sku='Gabcdefab',grade='C')])]);decision=dict(action=kind,sku='Gabcdefab',grade='C');
   if kind=='reply':decision['thread']=123
   moves=[dict(action='forum_marketing',args={'action':'context'}),dict(action='forum_marketing',args=dict(action='publish',decision=decision)),dict(action='sleep',args={})]
   class Toolbox:
    def __init__(self,root,ctx):assert isinstance(ctx['signer'],host.NoWallet)
    def run(self,name,mode,args,d):
     calls.append(args['action']);assert name=='forum_marketing' and mode=='call' and args['preset']=='aggressive'
     result=dict(status=recovery) if args['action']=='reconcile' else view if args['action']=='context' else dict(status=outcome,post=11 if outcome=='posted' else None)
     return dict(ok=True,result=result)
   class Model:
    def __init__(self,*a):models.append(True)
    def complete(self,messages,**kwargs):
     assert messages[0]['content']==f"{sdk.WORLD}\n\n{sdk.FORMAT}";assert 0<kwargs['timeout']<=35;modelcalls.append(True);return json.dumps(moves.pop(0))
   class Registered:
    name='outseop-r4';market='https://example.invalid';shop_url='https://example.invalid/shop'
    def token(self,r):return 'SYNTHETIC_NOT_REAL_AUTH'
    def address(self,r):return 'SYNTHETIC_NOT_A_REAL_WALLET'
   class Response:
    def raise_for_status(self):pass
    def json(self):return [dict(id=11,author='outseop-r4',role='shop',round=4,text='합성 게시\n두번째 줄')]
   fake=types.SimpleNamespace(Mind=sdk.Mind,Model=Model,Toolbox=Toolbox,mk=sdk.mk);worker=types.SimpleNamespace(validated_kit=lambda root:Registered());http=types.SimpleNamespace(get=lambda *a,**kw:httpgets.append(True) or Response());session=op/'runtime'/('forum-campaign-'+label);argv=['operator','--operator',str(op),'--session',str(session)]+(['--allow-one-post'] if allow else []);stdout=io.StringIO()
   with patch.object(sys,'argv',argv),patch.object(host,'verify_source',return_value=None),patch.object(host,'verify_kit',return_value=7),patch.object(host,'active_customer',return_value=active),patch.object(host.subprocess,'check_output',return_value='active\n'),patch.dict(sys.modules,{'agent_kit':fake,'worker_bootstrap':worker,'httpx':http}),contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(io.StringIO()):code=host.main()
   summary=json.loads((session/'summary.json').read_text());expected='postponed' if active else 'unknown' if recovery=='unknown' else 'context_too_large' if oversize else 'dry_selection' if not allow else outcome;eligible=not(active or recovery=='unknown' or oversize)
   ck(label+'_status_and_official_entry',code==0 and summary['status']==expected and summary['entrypoint']=='official Mind.run_once')
   ck(label+'_publish_count',calls.count('publish')==int(allow and eligible) and summary['publication_attempts']==int(eligible))
   ck(label+'_model_gate',len(models)==int(eligible) and len(modelcalls)==3*int(eligible))
   ck(label+'_JSON_and_output',json.loads(stdout.getvalue())==summary and (session/'summary.json').read_bytes().endswith(b'\n') and isinstance(json.loads((session/'tool-results-private.json').read_text()),list))
   if eligible:
    data=json.dumps(view,ensure_ascii=False).encode();ck(label+'_complete_view_hash_and_bytes',summary['original_view_sha256']==hashlib.sha256(data).hexdigest() and summary['original_view_utf8_bytes']==len(data) and summary['full_original_view_in_untrusted_user_context'])
   if expected=='posted':ck(label+'_public_confirmation_stub_only',summary['public_post_verified'] is True and len(httpgets)==1)
 finally:sdk.mk.LOG_FILE=oldlog
result=dict(host_sha256=hashlib.sha256((OP/'deploy/forum_campaign_operator.py').read_bytes()).hexdigest(),passed=sum(c['passed'] for c in checks),failed=sum(not c['passed'] for c in checks),checks=checks,actual_official_SDK_Mind_run_once=True,all_Model_Toolbox_HTTP_service_backend_calls_stubbed=True,all_contexts_synthetic=True,actual_Model_market_service_wallet_DB_operations=0,source_SDK_and_legacy_changed=False)
(QA/'main-mock-results.json').write_text(json.dumps(result,indent=2));print(json.dumps(dict(passed=result['passed'],failed=result['failed'],failures=[c for c in checks if not c['passed']],host_sha256=result['host_sha256'])))
