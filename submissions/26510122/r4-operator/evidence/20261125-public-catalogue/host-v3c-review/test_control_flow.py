from pathlib import Path
from copy import deepcopy
import importlib.util,json,sys,tempfile,time
from unittest.mock import patch
OP=Path('/home/seop/.local/share/ourolabs-r4-checkout/submissions/26510122/r4-operator');ST=OP/'runtime/r3-stock-20261124-204104/agent-work/validation/public_catalogue_runtime_v3c';QA=Path(__file__).resolve().parent;sys.path[:0]=[str(ST),str(OP.parent/'round-4/codex-r4'),str(OP/'kit')]
import broker_public_catalogue_host_candidate as mod
from public_catalogue_protocol import CatalogueProtocol
from public_catalogue_snapshot_host import CatalogueError
from public_catalogue_phase_metrics import PhaseMetrics,PHASES
checks=[]
def ck(n,b):checks.append(dict(case=n,passed=bool(b)))
def page(empty=False,snapshot='a'*64):
 t=int(time.time());return dict(status='ready',coverage='synthetic',observed_at=t-1,as_of=t,valid_until=t+120,snapshot=snapshot,query_id='b'*64,columns=['sku','grade','name','preferred_price','remaining_seconds'],common={},lookup={},rows=[] if empty else [['G00000001','C','합성상품',1001,100]],text_limit=1024,catalogue=dict(source_count=1,eligible_count=1,matched_count=int(not empty),offset=0,returned_count=int(not empty),next_args=None))
class Catalogue:
 instruction='synthetic public search';protocol=CatalogueProtocol(lambda s:s)
 def __init__(self,clock=None):self.searches=[];self.renders=0;self.fallbacks=[];self.page=page();self.clock=clock
 def open(self,*a):return deepcopy(self.page)
 def search(self,args,remaining):
  self.protocol.search(args,self.page);self.searches.append(deepcopy(args));self.page=page(args.get('q') in ('셔틀콕','zero'));return deepcopy(self.page)
 def render(self,args,remaining):self.renders+=1;return dict(status='rendered',reply='검증한 합성 상품입니다.',observed_at=self.page['observed_at'],valid_until=self.page['valid_until'])
 def fallback(self,text,remaining):
  self.fallbacks.append(remaining)
  if self.clock:self.clock[0]+=min(3,remaining)
  raise CatalogueError('fallback_not_applicable')
class Model:
 def __init__(self,moves,clock=None):self.moves=moves;self.messages=[];self.timeouts=[];self.clock=clock
 def complete(self,messages,**kw):
  self.messages.append(deepcopy(messages));self.timeouts.append(kw.get('timeout'))
  if self.clock:self.clock[0]+=min(26,kw['timeout'])
  return json.dumps(self.moves[min(len(self.messages)-1,len(self.moves)-1)],ensure_ascii=False)
def search(q):return dict(action='search_products',args=dict(q=q))
def run(moves,text='셔틀콕 빵 국거리 알려주세요',evidence=None,clock=None):
 cat=Catalogue(clock);model=Model(moves,clock);legacy=[];phases=[]
 def execute(args):
  legacy.append(deepcopy(args));return dict(outcome='context',inventory=[dict(sku='G00000001',grade='C')]) if args['action']=='context' else dict(outcome='price_out_of_bounds')
 b=mod.Broker(execute,model,max_steps=3,seconds=65,model_seconds=35,catalogue=cat,phase_report=phases.append)
 with patch.object(mod,'evidence',return_value=evidence or {}),patch.object(mod,'monotonic',side_effect=lambda:clock[0]) if clock is not None else patch.object(mod,'monotonic',wraps=mod.monotonic):answer=b.handle(text)
 return cat,model,legacy,phases,answer
moves=[search('셔틀콕'),search('셔틀콕'),search('빵'),search('국거리'),dict(action='render_public_products',args=dict(items=[dict(sku='G00000001',grade='C')]))]
cat,model,legacy,phases,answer=run(moves)
ck('five_readonly_steps_complete',len(model.messages)==5 and cat.renders==1 and '합성' in answer['reply'])
ck('duplicate_no_tool_requery',[r['q'] for r in cat.searches]==['셔틀콕','빵','국거리'])
history=[json.loads(m['content']) for m in model.messages[1] if m['role']=='assistant'];ck('history_first_search_q_preserved',history[0]['args']==dict(q='셔틀콕'))
observations=[json.loads(m['content']) for m in model.messages[2] if m['role']=='user'];ck('duplicate_explicit_previous_no_match',any(z.get('tool_result',{}).get('outcome')=='catalogue_search_already_performed' and z['tool_result'].get('already_executed') and z['tool_result'].get('previous_result',{}).get('catalogue',{}).get('matched_count')==0 for z in observations))
ck('q_AND_and_finish_system_instruction','AND semantics' in model.messages[0][0]['content'] and 'factual no-match' in model.messages[0][0]['content'])
ck('original_no_financial_executor_called',[x['action'] for x in legacy]==['context'])
ck('history_all_success_args',[json.loads(m['content'])['args'] for m in model.messages[-1] if m['role']=='assistant']==[dict(q='셔틀콕'),dict(q='셔틀콕'),dict(q='빵'),dict(q='국거리')])
# Pure financial/protected requests retain three model judgments and cannot use public fallback.
for label,text,evidence in [('buy','구매 G00000001',{}),('consent','지금 구매할게요',{}),('refund','환불 요청합니다',{}),('rights','공개 정보 문의',dict(right='SYNTHETIC'))]:
 c,m,l,p,a=run([search('zero')],text,evidence);ck('protected_three_'+label,len(m.messages)==3);ck('protected_fallback_blocked_'+label,c.fallbacks==[])
# Starting a financial action closes the extended read-only budget.
c,m,l,p,a=run([dict(action='offer',args=dict(sku='G00000001',proposed_price=1001)),search('zero')]);ck('financial_action_reverts_to_three',len(m.messages)==3 and sum(x['action']=='offer' for x in l)==1)
# A stale cached page cannot suppress the actual search/validity check.
c=Catalogue();m=Model([search('zero')]*5)
# Same query, changed snapshot never reuses a prior zero cache.
class ChangingCatalogue(Catalogue):
 def search(self,args,remaining):
  z=super().search(args,remaining)
  if len(self.searches)==1:z['valid_until']=int(time.time())-1
  return z
c=ChangingCatalogue();b=mod.Broker(lambda a:dict(outcome='context',inventory=[]),m,max_steps=3,seconds=65,model_seconds=35,catalogue=c);b.handle('재고 알려주세요');ck('stale_cache_does_not_suppress_validation',len(c.searches)>=2)
clock=[0.0];c,m,l,p,a=run([search('zero')],clock=clock);ck('same_absolute_deadline_and_reserve',len(m.messages)==3 and m.timeouts==[35,34,8] and c.fallbacks==[5] and clock[0]<=65)
# Metric retry allowance changes only the bounded maximum to5.
with tempfile.TemporaryDirectory(dir=QA) as tmp:
 metric=PhaseMetrics(Path(tmp)/'metrics.json');ev={k:0.0 for k in PHASES};ev.update(outcome='fallback',retries=5,reason='no_match',phase_reasons=dict(search='no_match'));metric(ev);ck('metrics_accept_five',metric.rows['fallback']['retries_sum']==5);ev['retries']=6;metric(ev);ck('metrics_reject_six',metric.rows['fallback']['count']==1)
result=dict(checks=checks,passed=sum(x['passed'] for x in checks),failed=sum(not x['passed'] for x in checks),all_Model_catalogue_legacy_service_calls_mocked=True,actual_model_market_wallet_DB_service_operations=0)
(QA/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(dict(passed=result['passed'],failed=result['failed'],failures=[x for x in checks if not x['passed']]),ensure_ascii=False))
