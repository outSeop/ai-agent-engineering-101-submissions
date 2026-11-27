"""Public TEST-ONLY reproducer: prepare-only unless --run-synthetic. No production actions."""
from pathlib import Path
from hashlib import sha256
import argparse,json,sys,os,time
HERE=Path(__file__).resolve().parent
OP=next(p for p in HERE.parents if (p/'kit/agent_kit.py').exists())
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-synthetic',action='store_true');p.add_argument('--output',type=Path);a=p.parse_args()
out=(a.output or OP/'runtime'/('stock15-public-reproduction-'+str(int(time.time())))).resolve()
assert out.is_relative_to((OP/'runtime').resolve()) and not out.exists(), 'output must be a new owned operator/runtime directory'
manifest=json.loads((HERE/'MANIFEST.json').read_bytes())
for name,digest in manifest['file_sha256'].items():assert sha256((HERE/name).read_bytes()).hexdigest()==digest,name
command=[sys.executable,'-B',str(HERE/'run_stock_campaign_independent.py'),'--source',str(HERE/'generated/stock_procurement@15'),'--logic-sha','e479504a2d639ac020d84d32a78ecf960bab182d3c8a5a4362950b83d6542d7c','--output',str(out)]
if not a.run_synthetic:print(json.dumps({'prepared_only':True,'requires_offline_network_namespace':True,'command':command}));raise SystemExit(0)
assert {line.split(':')[0].strip() for line in Path('/proc/net/dev').read_text().splitlines()[2:]}=={'lo'}, 'invoke under unshare -Urn'
os.execv(sys.executable,command)
