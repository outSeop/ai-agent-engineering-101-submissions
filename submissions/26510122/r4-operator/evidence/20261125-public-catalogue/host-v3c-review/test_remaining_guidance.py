from pathlib import Path
import importlib.util,json
QA=Path(__file__).resolve().parent
s=importlib.util.spec_from_file_location('unchanged_v3b_regressions_on_v3c',QA/'test_control_flow.py');t=importlib.util.module_from_spec(s);s.loader.exec_module(t)
cat,model,legacy,phases,answer=t.run([t.search('셔틀콕'),t.search('소금빵'),t.search('치아바타'),t.search('청국장'),dict(action='render_public_products',args=dict(items=[dict(sku='G00000001',grade='C')]))])
checks=[]
def ck(n,b):checks.append(dict(case=n,passed=bool(b)))
metadata=[]
for msgs in model.messages:
 values=[]
 for m in msgs:
  if m['role']=='user':
   try:x=json.loads(m['content'])
   except:continue
   if 'host_readonly_flow' in x:values.append(x['host_readonly_flow'])
 metadata.append(values[-1])
ck('remaining5to1_no_step_increase',[x['remaining_decisions_including_this_one'] for x in metadata]==[5,4,3,2,1])
ck('last_decision_final_render_or_respond',metadata[-1]['final_decision'] is True and metadata[-1]['allowed_final_actions']==['render_public_products','respond'] and 'do not request another search' in metadata[-1]['instruction'])
ck('literal_not_semantic_and_initial_inventory_guidance','literal product-name/category text, not synonyms or inferred ingredients' in model.messages[0][0]['content'] and 'already supplied initial inventory' in model.messages[0][0]['content'])
_,m,_,_,_=t.run([t.search('zero')],text='구매 G00000001')
ck('protected_financial_no_terminal_public_instruction',len(m.messages)==3 and all('host_readonly_flow' not in x['content'] for msgs in m.messages for x in msgs))
result=dict(checks=checks,passed=sum(x['passed'] for x in checks),failed=sum(not x['passed'] for x in checks),source_control_regressions_passed=20,actual_Model_market_service_wallet_DB_calls=0,scope='prompt metadata delivery only; mock does not prove that actual Model follows guidance')
(QA/'remaining-guidance-results.json').write_text(json.dumps(result,indent=2));print(json.dumps(dict(passed=result['passed'],failed=result['failed'],failures=[x for x in checks if not x['passed']])))
