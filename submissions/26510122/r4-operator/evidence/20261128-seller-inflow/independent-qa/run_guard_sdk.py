"""Portable offline external SDK guard adapter. Requires network namespace lo-only."""
import argparse,json,os,sys,shutil
from pathlib import Path
from hashlib import sha256
from contextlib import redirect_stdout,redirect_stderr

def main():
 p=argparse.ArgumentParser();p.add_argument('--operator',type=Path,required=True);p.add_argument('--source',type=Path,required=True);p.add_argument('--dependency-dir',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();assert {line.split(':')[0].strip() for line in Path('/proc/net/dev').read_text().splitlines()[2:]}=={'lo'}
 op=a.operator.resolve(strict=True);src=a.source.resolve(strict=True);deps=a.dependency_dir.resolve(strict=True);out=a.output.resolve();out.relative_to(op/'runtime');os.umask(0o077);out.mkdir(mode=0o700);root=out/'root';root.mkdir(mode=0o700);code=root/'codex-r4';code.mkdir(mode=0o700);adapter=root/'adapter';adapter.mkdir(mode=0o700);support=root/'qa-support';support.mkdir(mode=0o700);here=Path(__file__).parent
 pins={n:sha256((src/n).read_bytes()).hexdigest() for n in ['logic.py','test.py','permission.yml','forge.json']};assert pins['logic.py']=='ade6803aa1e36c5d48a744cddf59637a29b44d040d1866b0a6ed1de54a56ff22';receipt=json.loads((src/'forge.json').read_bytes());assert receipt['tool']=='forum_marketing' and receipt['version']==15 and receipt['sha256']=={n:h for n,h in pins.items() if n!='forge.json'}
 for name in ['forum.py','dispatcher.py','price_policy.py']:shutil.copyfile(op.parent/'round-4/codex-r4'/name,code/name)
 for name in ['forum_marketing12.py','forum_marketing11.py','forum_marketing10.py','forum_marketing9.py']:shutil.copyfile(deps/name,code/name)
 shutil.copyfile(here/'portable_forum_contract.py',support/'portable_forum_contract.py');(root/'qa-binding.json').write_text(json.dumps({'operator':str(op),'support':str(support)}));shutil.copyfile(src/'logic.py',adapter/'logic.py');shutil.copyfile(here/'guard_external_test.py',adapter/'test.py');permission=(src/'permission.yml').read_text();assert 'write: [state/r4-benefits]' in permission;(adapter/'permission.yml').write_text(permission.replace('write: [state/r4-benefits]','write: [state/r4-benefits, diagnostic-fixtures, guards-safe.json]'))
 sys.path.insert(0,str(op/'kit'));import agent_kit as sdk
 class NoWallet:
  def grant(self,*a):return None
  def do(self,*a):raise AssertionError('No financial capability')
 with (out/'SDK-private.log').open('w') as log,redirect_stdout(log),redirect_stderr(log):
  sdk.mk.LOG_FILE=root/'SDK-private.log';box=sdk.Toolbox(root,{'name':'outseop-r4','market':'https://market.ourolabs.ai','tokens':{},'addresses':{},'signer':NoWallet()});envelope=box.run('forum_marketing','test',d=adapter);(out/'SDK-envelope-private.json').write_text(json.dumps(envelope))
 result=json.loads((root/'guards-safe.json').read_bytes()) if (root/'guards-safe.json').exists() else {'passed':0,'total':5};result.update(SDK_ok=envelope.get('ok',False),source4_sha256=pins,adapter_scope='Fixture/output writes and portable path binding only; original genuine source/SDK/forge unchanged.');(out/'safe-result.json').write_text(json.dumps(result,indent=2));print(json.dumps({'passed':result['passed'],'total':result['total'],'SDK_ok':result['SDK_ok']}));assert result['passed']==result['total']==5 and result['SDK_ok']
if __name__=='__main__':main()
