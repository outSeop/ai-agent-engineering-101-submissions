"""Narrow v5 two-delta and host one-attempt boundary verification; no network."""
from pathlib import Path
from hashlib import sha256
from contextlib import redirect_stdout,redirect_stderr
from unittest.mock import patch
import ast,json,sys,importlib.util,socket
H=Path(__file__).parent;OUT=H/'validation/first-purchase-bonus-notice-v5-narrow-20261125-second';OUT.mkdir(mode=0o700)
W=H.parent;STAGE=W/'validation/first_purchase_bonus_notice_v5_candidate';PIN='e4ad821895846a818876ae080123fe66a866891ac4badc1ee2e8f1c5dc823b08'
assert sha256((STAGE/'MANIFEST.json').read_bytes()).hexdigest()==PIN
manifest=json.loads((STAGE/'MANIFEST.json').read_text())
for name,d in manifest['file_sha256'].items():assert sha256((STAGE/name).read_bytes()).hexdigest()==d
# Reuse independent original-schema test fixture definitions, no repeated broad cases.
text=(H/'qa_first_purchase_bonus_notice_v3.py').read_text();text=text.replace("OUT=Path(__file__).parent/'validation/first-purchase-bonus-notice-v3-independent-20261125-second';OUT.mkdir(mode=0o700)","OUT=Path(__file__).parent/'validation/first-purchase-bonus-notice-v5-narrow-20261125-second/fixture';OUT.mkdir(mode=0o700)")
text=text.replace('first_purchase_bonus_notice_v3_candidate','first_purchase_bonus_notice_v5_candidate').replace('e527f2472f7385e8fbd5472a5b05eda3df7ee46b0b319ddbc89cf036e6ec9b88',PIN)
text=text.replace("['files_sha256']","['file_sha256']")
ns={'__file__':str(H/'qa_first_purchase_bonus_notice_v3.py'),'__name__':'narrow_fixture'};exec(compile(text,'independent-fixture', 'exec'),ns);m=ns['m'];Case=ns['Case'];results=[]
def record(name):results.append({'case':name,'passed':True})
with (OUT/'private-console.log').open('w') as log,redirect_stdout(log),redirect_stderr(log):
 a=ast.parse((W/'validation/first_purchase_bonus_notice_v3_candidate/tools/first_purchase_bonus_notice/logic.py').read_text());b=ast.parse((STAGE/'tools/first_purchase_bonus_notice/logic.py').read_text())
 aa={n.name:ast.dump(n,include_attributes=False) for n in a.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))};bb={n.name:ast.dump(n,include_attributes=False) for n in b.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))};assert aa.keys()==bb.keys();changed=[n for n in aa if aa[n]!=bb[n]];assert set(changed)=={'latest_forum','render'};record('only-two-business-function-deltas')
 c=Case('null-score');c.rows[0]['score']=None;r=c.call('preview');assert r['status']=='preview' and r['lane']=='eligible' and not c.post;assert '최초 정상 정산 시각부터 7일' in r['text'] and '발급일부터' not in r['text'] and '다음 구매부터' in r['text'];record('null-score-market-row-preview-noPOST-settlement-expiry-text')
 c.rows[0].pop('score');assert c.call('preview')['reason']=='history_unverified';record('score-field-still-required')
 # Test the runner gate in the actual inherited official SDK Mind loop, with a local Mock Model.
 sys.path[:0]=[str(STAGE/'host'),str(ns['OP']/'deploy'),str(ns['OP']/'kit')]
 import first_purchase_bonus_notice_operator_candidate as runner
 from forum_campaign_operator import make_campaign_mind,verify_kit
 import agent_kit as official
 assert verify_kit(ns['OP'])==7;runner.verified_source(STAGE/'tools/first_purchase_bonus_notice',manifest['file_sha256']['tools/first_purchase_bonus_notice/forge.json'])
 calls=[];gate=runner.NoticeGate({'lane':'eligible','text':r['text']},lambda:(calls.append(True) or {'status':'unknown'}))
 assert gate.call('other',{'mode':'dispatch'})=={'status':'disabled'};assert gate.call(runner.NAME,{'mode':'dispatch','text':'injected'})=={'status':'disabled'} and not calls
 class Model:
  def complete(self,messages,**kwargs):return json.dumps({'action':runner.NAME,'args':{'mode':'dispatch'}})
 session=OUT/'mock-mind';session.mkdir(mode=0o700);(session/'logs').mkdir();official.mk.LOG_FILE=session/'logs/SDK-private.log'
 mind=make_campaign_mind(official,session,{'max_steps':2,'run_minutes':1},Model(),gate,{'name':'outseop-r4','market':m.MARKET,'shop_url':None,'tokens':{},'addresses':{}})
 assert type(mind).run_once is official.Mind.run_once
 def denied(*args,**kwargs):raise AssertionError('network forbidden')
 with patch.object(socket,'getaddrinfo',denied),patch.object(socket.socket,'connect',denied):mind.run_once([])
 assert len(calls)==1 and gate.attempted and gate.result['status']=='unknown';assert gate.call(runner.NAME,{'mode':'dispatch'})=={'status':'disabled'} and len(calls)==1;record('original-Mind-mock-two-dispatch-unknown-once-only')
 # Code boundary review: allow flag defaults false; gated dispatch uses original Toolbox.run and exact source.
 source=(STAGE/'host/first_purchase_bonus_notice_operator_candidate.py').read_text();assert 'args.allow_one_post' in source and 'action="store_true"' in source and 'official.Toolbox(root,ctx).run(NAME,"call",{"mode":mode},d=source)' in source;assert 'fcntl.LOCK_EX|fcntl.LOCK_NB' in source;record('default-preview-ordinary-Toolbox-exact-pins-flock-static-boundary')
result={'passed':len(results),'total':len(results),'cases':results,'stage_manifest_sha256':PIN,'genuine_logic_sha256':manifest['file_sha256']['tools/first_purchase_bonus_notice/logic.py'],'genuine_forge_sha256':manifest['file_sha256']['tools/first_purchase_bonus_notice/forge.json'],'actual_Model_network_POST_production_changes':0,'method':'Two exact semantic deltas plus actual original SDK Mind.run_once with Mock Model and dispatch stub; runner live run not invoked.','prior_v3_known_functional_cases':'7/7 preserved; not broadly repeated','limitation':'Actual live preview/authorization/post is root activity, not this mock boundary evidence.'}
(OUT/'safe-result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
