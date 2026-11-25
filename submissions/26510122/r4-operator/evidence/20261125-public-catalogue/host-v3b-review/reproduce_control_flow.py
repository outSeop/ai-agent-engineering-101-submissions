from pathlib import Path
import argparse,os,subprocess,sys,tempfile
p=argparse.ArgumentParser();p.add_argument('--operator',required=True);p.add_argument('--stage',required=True);p.add_argument('--output',required=True);a=p.parse_args();root=Path(__file__).resolve().parent;out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
s=(root/'test_control_flow.py').read_text();old="OP=Path('/home/seop/.local/share/ourolabs-r4-checkout/submissions/26510122/r4-operator')";oldstage="ST=OP/'runtime/r3-stock-20261124-204104/agent-work/validation/public_catalogue_runtime_v3b'"
if s.count(old)!=1 or s.count(oldstage)!=1:raise SystemExit('unexpected original QA path shape')
s=s.replace(old,'OP=Path('+repr(str(Path(a.operator).resolve()))+')').replace(oldstage,'ST=Path('+repr(str(Path(a.stage).resolve()))+')')
with tempfile.TemporaryDirectory(prefix='public-v3b-QA-') as tmp:
 script=Path(tmp)/'test_control_flow.py';script.write_text(s);env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1');code=subprocess.call([sys.executable,str(script)],env=env);result=Path(tmp)/'results.json'
 if result.exists():(out/'results.json').write_bytes(result.read_bytes())
 raise SystemExit(code)
