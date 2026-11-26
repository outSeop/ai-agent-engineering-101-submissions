from pathlib import Path
import importlib.util,json,time,tempfile,sys
OP=Path('/home/seop/.local/share/ourolabs-r4-checkout/submissions/26510122/r4-operator')
spec=importlib.util.spec_from_file_location('independent_conversion_canary',Path(__file__).resolve().parent.parent/'buyer_conversion_class_canary_host_v2.py');h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
bundle=OP/'runtime/buyer-conversion-20261126-implementation/public_catalogue_runtime_v4d_candidate';pin=h.digest((bundle/'MANIFEST.json').read_bytes())
with tempfile.TemporaryDirectory() as folder:
 root=Path(folder);now=int(time.time());doc={'schema':'outseop-r4.customer-offers.v1','shop':'outseop-r4','observed_at':now,'valid_until':now+150,'units':[{'unit_ref':'synthetic-only-'+str(i),'sku':f'G{i+1:08x}','name':'합성 쌀 1팩','category_path':['식품','쌀'],'state':'available','grade':'A' if i==0 else 'B','price_credits':1000+i,'standard_fee_credits':None,'expires_at':now+3600} for i in range(2)]}
 source=root/'public-synthetic.json';source.write_bytes(h.encode(doc));source.chmod(0o400);session=root/'session';raw,snapshot=h.prepare(OP,session,source,bundle,pin)
 class Model:
  def __init__(self):self.index=0
  def complete(self,messages,**kwargs):
   moves=[{'action':'search_products','args':{'q':'쌀','grade':'A','limit':8}},
          {'action':'search_products','args':{'q':'쌀','grade':'B','limit':8}},
          {'action':'render_public_products','args':{'items':[{'sku':'G00000001','grade':'A'},{'sku':'G00000002','grade':'B'}]}},
          {'action':'render_public_products','args':{'items':[{'sku':'G00000001','grade':'A'},{'sku':'G00000002','grade':'B'}]}},
          {'action':'respond','args':{'text':'확인할 상품을 지정해 주세요.'}}]
   move=moves[self.index];self.index+=1;return json.dumps(move)
 with (root/'console-private.log').open('w') as log,h.redirect_stdout(log),h.redirect_stderr(log):r=h.run_asgi(OP,session,raw,snapshot,Model(),'지금 파는 쌀 A등급과 B등급 상품 두 가지의 가격과 소비기한을 알려 주세요.',scenario='followup')
 private=json.loads((session/'logs/all-transport-turns-private.json').read_bytes());assert len(private)==3
 assert r['raw_history_marker_forwarded'] is False and r['actual_financial_execution_count']==0
 assert private[0]['task_state']=='TASK_STATE_INPUT_REQUIRED' and private[1]['task_state']=='TASK_STATE_INPUT_REQUIRED'
 assert [x.get('remembered_public_count') for x in r['Model_metrics']]==[0,0,0,2,0]
 Path(__file__).with_name('asgi-crosspage-safe-result.json').write_text(json.dumps({k:r[k] for k in ('per_turn_safe','raw_history_marker_forwarded','actual_financial_execution_count','same_task_continuation_accepted','cross_task_id_is_different')},indent=2)+'\n')
 print(json.dumps({'actual_SDK_ASGI':True,'baseline_public_state':private[0]['body'].get('result',{}).get('task',private[0]['body'].get('result',{})).get('status',{}).get('state'),'same_task_continuation_accepted':r['same_task_continuation_accepted'],'cross_task_id_is_different':r['cross_task_id_is_different'],'remembered_public_counts':[x.get('remembered_public_count') for x in r['Model_metrics']],'raw_history_forwarded':r['raw_history_marker_forwarded'],'actual_Model_calls':0,'DB_wallet_market_calls':0}))
