"""Official SDK native call/test orchestration, external test adapter explicitly separate."""
from pathlib import Path
from hashlib import sha256
from contextlib import redirect_stdout,redirect_stderr
import argparse,json,sys,time,shutil,sqlite3
ap=argparse.ArgumentParser();ap.add_argument('--source',required=True);ap.add_argument('--logic-sha',required=True);ap.add_argument('--output',required=True);ap.add_argument('--only-case',default='');opts=ap.parse_args()
OP=next(p for p in Path(__file__).resolve().parents if (p/'kit/agent_kit.py').exists());QA=Path(__file__).parent;OUT=Path(opts.output);OUT.mkdir(mode=0o700);ROOT=OUT/'isolated-sdk-root';ROOT.mkdir(mode=0o700);(ROOT/'tools').mkdir();(ROOT/'host_inputs').mkdir(mode=0o700);(ROOT/'codex-r4').mkdir(mode=0o700);(ROOT/'state/r4-demand').mkdir(mode=0o700,parents=True);(ROOT/'logs').mkdir();pins={}
if opts.only_case:(ROOT/'external-case-filter.json').write_text(json.dumps([opts.only_case]))
assert {l.split(':')[0].strip() for l in Path('/proc/net/dev').read_text().splitlines()[2:]}=={'lo'},'run only in isolated offline network namespace'
for source,name in [(Path(opts.source),'stock_procurement'),(QA/'generated/record_stock_request@4','record_stock_request')]:
 target=ROOT/'tools'/name;target.mkdir();pins[name]={}
 for n in ['logic.py','test.py','permission.yml','forge.json']:
  raw=(source/n).read_bytes();(target/n).write_bytes(raw);(target/n).chmod(0o400);pins[name][n]=sha256(raw).hexdigest()
 assert json.loads((target/'forge.json').read_bytes())['sha256']=={n:d for n,d in pins[name].items() if n!='forge.json'}
assert pins['stock_procurement']['logic.py']==opts.logic_sha
parent=(OP.parent/'round-4/codex-r4/procurement.py').read_bytes();assert sha256(parent).hexdigest()=='675bdaa2942f7bdf3d119d10c6e1176f790ae0bacbb22a32cf77ae82de0628c6';(ROOT/'host_inputs/legacy-stock8.py').write_bytes(parent)
prior14=QA/'generated/stock_procurement@14/logic.py';assert sha256(prior14.read_bytes()).hexdigest()=='7c8e4a5db5916ae16a3f3d0c7b0208d25e470f9e6149d60351b06cb67b73f707';shutil.copyfile(prior14,ROOT/'host_inputs/prior-stock14.py')
for n in ['dispatcher.py','price_policy.py']:shutil.copyfile(OP.parent/'round-4/codex-r4'/n,ROOT/'codex-r4'/n)
now=time.time();items=[{'sku':'G159be1f8','name':'아침 곡물쌀 5kg','category':'식품>곡물'},{'sku':'G00000002','name':'들녘 취나물 300g','category':'식품>채소'},{'sku':'G00000003','name':'맑은 두유 1L','category':'식품>음료'}]
for i in range(5626):items.append({'sku':f'G{i+0x100000:08x}','name':f'생활 공용품 {i}','category':'생활>공용'})
p=ROOT/'host_inputs/stock-public-catalog.json';p.write_text(json.dumps({'observed_at':now-1,'valid_until':now+149,'round':4,'items':items},ensure_ascii=False));p.chmod(0o400)
# Separate external validation directory uses ordinary SDK d= test API. No forge/index or genuine four files edited.
ADAPTER=ROOT/'external-independent-test';ADAPTER.mkdir();shutil.copyfile(ROOT/'tools/stock_procurement/logic.py',ADAPTER/'logic.py');shutil.copyfile(ROOT/'tools/stock_procurement/permission.yml',ADAPTER/'permission.yml');shutil.copyfile(QA/'stock13_external_sdk_test.py',ADAPTER/'test.py');shutil.copyfile(QA/'stock12_external_contract.py',ADAPTER/'stock12_external_contract.py')
permission=(ADAPTER/'permission.yml').read_text();assert 'write: [state/r4-benefits]' in permission;(ADAPTER/'permission.yml').write_text(permission.replace('write: [state/r4-benefits]','write: [state/r4-benefits, independent-fixtures, independent-stock13-safe-result.json]'))
sys.path.insert(0,str(OP/'kit'));import agent_kit as official
class NoWallet:
 def grant(self,name,permission,timeout):
  assert permission.get('pay_limit',0)<=1000000
  return None  # no signer URL, cap, production keys, funds or live wallet service
with (OUT/'private-console.log').open('w') as log,redirect_stdout(log),redirect_stderr(log):
 official.mk.LOG_FILE=ROOT/'logs/SDK-private.log';box=official.Toolbox(ROOT,{'name':'outseop-r4','market':'https://market.ourolabs.ai','shop_url':'https://market.test/shops/outseop-r4','tokens':{},'addresses':{},'signer':NoWallet()})
 recorder=[]
 for ref,text,hints in [('actual-native-sku','G159be1f8 가격 알려주세요',{}),('actual-native-noun','취나물 재고와 가격 보여 주세요',{}),('actual-native-semantic','소이밀크 재고와 가격 보여 주세요. 결제는 나중에 할게요.',{'product_phrase':'소이밀크','queries':['두유']})]:
  out=box.run('record_stock_request','call',dict(op='record',text=text,event_ref=ref,observed_at=now-2,source='external_completed',**hints));assert out['ok'] and out['result']['status']=='recorded';recorder.append(out['result'])
 with sqlite3.connect(ROOT/'state/r4-demand/requests.sqlite3') as db:assert db.execute('SELECT COUNT(*) FROM request').fetchone()[0]==3
 out=box.run('stock_procurement','test',d=ADAPTER);(OUT/'official-test-envelope-private.json').write_text(json.dumps(out,indent=2))
result_path=ROOT/'independent-stock13-safe-result.json'
if result_path.exists():summary=json.loads(result_path.read_bytes())
else:summary={'passed':0,'total':0,'setup_error':out.get('error'),'cases':[]}
summary.update({'source4_sha256':pins,'source_logic_expected':opts.logic_sha,'real_recorder4_call_count':3,'SDK_test_ok':out.get('ok',False),'external_test_adapter_disclosed':True,'external_test_only_write_extension':['independent-fixtures','independent-stock13-safe-result.json'],'genuine4_source_files_unchanged':all(sha256((ROOT/'tools'/name/n).read_bytes()).hexdigest()==d for name,files in pins.items() for n,d in files.items()),'forge_log_or_tool_index_modified':False,'network_namespace_offline':True})
(OUT/'safe-result.json').write_text(json.dumps(summary,indent=2));print(json.dumps({k:summary.get(k) for k in ['passed','total','cases','setup_error','SDK_test_ok','genuine4_source_files_unchanged','real_recorder4_call_count']}))
