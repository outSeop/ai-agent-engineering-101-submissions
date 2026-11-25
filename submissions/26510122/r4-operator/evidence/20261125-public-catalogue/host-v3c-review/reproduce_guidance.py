from pathlib import Path
import argparse,hashlib,json,os,subprocess,sys,tempfile
p=argparse.ArgumentParser();p.add_argument('--operator',required=True);p.add_argument('--stage');p.add_argument('--output',required=True);a=p.parse_args();root=Path(__file__).resolve().parent;op=Path(a.operator).resolve();out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='public-v3c-QA-') as tmp:
 temp=Path(tmp);stage=Path(a.stage).resolve() if a.stage else temp/'stage'
 if not a.stage:
  meta=json.loads((root/'host-source/MANIFEST.json').read_text());base=op/'deploy/public_catalogue_runtime_v3'
  for n,sha in meta['file_sha256'].items():
   src=root/'host-source'/n if (root/'host-source'/n).is_file() else base/n;b=src.read_bytes()
   if hashlib.sha256(b).hexdigest()!=sha:raise SystemExit('base or reviewed host artifact mismatch: '+n)
   target=stage/n;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b)
  (stage/'MANIFEST.json').write_bytes((root/'host-source/MANIFEST.json').read_bytes())
 s=(root/'test_control_flow.py').read_text();old="OP=Path('/home/seop/.local/share/ourolabs-r4-checkout/submissions/26510122/r4-operator')";oldstage="ST=OP/'runtime/r3-stock-20261124-204104/agent-work/validation/public_catalogue_runtime_v3c'"
 if s.count(old)!=1 or s.count(oldstage)!=1:raise SystemExit('unexpected original QA import shape')
 s=s.replace(old,'OP=Path('+repr(str(op))+')').replace(oldstage,'ST=Path('+repr(str(stage))+')');(temp/'test_control_flow.py').write_text(s);(temp/'test_remaining_guidance.py').write_bytes((root/'test_remaining_guidance.py').read_bytes())
 code=subprocess.call([sys.executable,str(temp/'test_remaining_guidance.py')],env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'))
 for n in ('results.json','remaining-guidance-results.json'):
  if (temp/n).exists():(out/n).write_bytes((temp/n).read_bytes())
 raise SystemExit(code)
