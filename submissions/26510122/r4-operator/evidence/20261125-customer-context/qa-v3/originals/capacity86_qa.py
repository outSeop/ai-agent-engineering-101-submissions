from pathlib import Path
from copy import deepcopy
import json,time
ROOT=Path(__file__).resolve().parent
prefix=(ROOT/'ordinary_toolbox_qa.py').read_text().split('\nwith Fake() as f:',1)[0];ns={'__file__':str(ROOT/'ordinary_toolbox_qa.py')};exec(compile(prefix,'anonymous_shape_external_fixture','exec'),ns)
Fake=ns['Fake'];base=ns['base'];unpack=ns['unpack'];original=json.loads((ns['OP']/'runtime/qa-build-customer-context-v1-20261125/anonshape-fixture.json').read_text());old=original['observed_at'];d=deepcopy(original);now=int(time.time());d['observed_at']=now-1;d['valid_until']=now+100
for row in d['units']:
 if row['expires_at'] is not None:row['expires_at']=now+row['expires_at']-old
for i in range(70,86):
 row=deepcopy(d['units'][i-70]);row.update(unit_ref='ANON-EXTENSION-'+str(i),sku='G'+format(0xf0000000+i,'08x'),name='가상추가'+chr(0xAC00+i)+'가'*(max(5,len(row['name']))-5),price_credits=row['price_credits']+97*(i-69),expires_at=now+86400+13*i);d['units'].append(row)
checks=[];records=[]
def ck(case,ok,observed=None):checks.append({'case':case,'passed':bool(ok),'observed':observed})
with Fake() as f:
 f.write(base(),d);o=f.call();rows=unpack(o) if 'verified_context' in o else []
 ck('anonymous86_extension_all_exact_or_explicit_failure',len(rows)==86 and [(r['sku'],r['preferred_price'],r['grade'],r['expires_at']) for r in rows]==[(x['sku'],x['price_credits'],x['grade'],x['expires_at']) for x in d['units']],{'rows':len(rows),'error':o.get('error'),'pages':o.get('pages'),'text_limit':o.get('verified_context',{}).get('inventory',{}).get('text_limit'),'compact_chars':len(json.dumps(o,ensure_ascii=False,separators=(',',':')))})
 records.append({'case':'anonymous86_extension','output_rows':len(rows),'error':o.get('error'),'actual86_inventory_claim':False})
 wide=deepcopy(d)
 for i,row in enumerate(wide['units']):row['category_path']=chr(0xAC00+i)+'가'*599
 f.write(base(),wide);z=f.call();ck('uncompressible86_no_partial_silent_drop',z=={'error':'observation_capacity_exceeded','inventory_count':86},{'error':z.get('error'),'inventory_count':z.get('inventory_count'),'partial_context_present':'verified_context' in z});records.append({'case':'synthetic_wide_string_paths86','source_not_actual86':True,'result':z})
result={'checks':checks,'passed':sum(x['passed'] for x in checks),'failed':sum(not x['passed'] for x in checks),'records':records,'all_inputs_anonymous_synthetic':True,'actual86_capture_available':False,'actual_model_market_calls':0,'production_changed':False,'no_capacity_result_extrapolated_to_actual86':True};(ROOT/'anonymous86-capacity-qa-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
