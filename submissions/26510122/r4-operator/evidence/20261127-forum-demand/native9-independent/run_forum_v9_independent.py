from pathlib import Path
from hashlib import sha256
from contextlib import redirect_stdout,redirect_stderr
import sys,json,shutil
OP=Path('/home/seop/.local/share/ourolabs-r4-checkout/submissions/26510122/r4-operator');QA=Path(__file__).parent;SRC=OP/'runtime/class-rebuild-forum-marketing-20261127/tools/forum_marketing';OUT=QA/'accepted9-full-independent';ROOT=OUT/'isolated-sdk-root';ROOT.mkdir(mode=0o700,parents=True);(ROOT/'tools/forum_marketing').mkdir(parents=True);(ROOT/'codex-r4').mkdir();(ROOT/'logs').mkdir();ADAPTER=ROOT/'external-test-adapter';ADAPTER.mkdir();pins={}
assert {l.split(':')[0].strip() for l in Path('/proc/net/dev').read_text().splitlines()[2:]}=={'lo'}
for n in ['logic.py','test.py','permission.yml','forge.json']:
 b=(SRC/n).read_bytes();(ROOT/'tools/forum_marketing'/n).write_bytes(b);pins[n]=sha256(b).hexdigest()
assert pins['logic.py']=='b2edc8dba8c214a22074eb1f3db35ce5eb8234f444cf22710f025078b64e48e9';assert json.loads((ROOT/'tools/forum_marketing/forge.json').read_bytes())['sha256']=={n:d for n,d in pins.items() if n!='forge.json'}
for n in ['forum.py','dispatcher.py','price_policy.py']:shutil.copyfile(OP.parent/'round-4/codex-r4'/n,ROOT/'codex-r4'/n)
shutil.copyfile(ROOT/'tools/forum_marketing/logic.py',ADAPTER/'logic.py');permission=(SRC/'permission.yml').read_text();assert 'write: [state/r4-benefits]' in permission;(ADAPTER/'permission.yml').write_text(permission.replace('write: [state/r4-benefits]','write: [state/r4-benefits, diagnostic-fixtures, forum-final-safe.json]'));shutil.copyfile(QA/'forum_v9_external_test.py',ADAPTER/'test.py')
sys.path.insert(0,str(OP/'kit'));import agent_kit as official
class NoWallet:
 def grant(self,*a):return None
with (OUT/'private-console.log').open('w') as log,redirect_stdout(log),redirect_stderr(log):
 official.mk.LOG_FILE=ROOT/'logs/SDK-private.log';box=official.Toolbox(ROOT,{'name':'outseop-r4','market':'https://market.ourolabs.ai','tokens':{},'addresses':{},'signer':NoWallet()});out=box.run('forum_marketing','test',d=ADAPTER);(OUT/'SDK-envelope-private.json').write_text(json.dumps(out,indent=2))
p=ROOT/'forum-final-safe.json';r=json.loads(p.read_bytes()) if p.exists() else {'passed':0,'total':0,'cases':[],'setup_error':out.get('error')};r.update(source4_sha256=pins,SDK_test_ok=out.get('ok',False),external_adapter_scope='Test-only fixture/result write paths; unchanged genuine4/forge/index, no actual signer cap; offline namespace.');(OUT/'safe-result.json').write_text(json.dumps(r,indent=2));print(json.dumps({k:r.get(k) for k in ['passed','total','cases','facts','setup_error','SDK_test_ok']}))
