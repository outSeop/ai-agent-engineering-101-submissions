"""Source-only verification. No context invocation, wallet, Model, POST or live mutation."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,sys
from types import SimpleNamespace
OP=Path('/home/seop/.local/share/ourolabs-r4-checkout/submissions/26510122/r4-operator')
def main():
 p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--forge-sha',required=True);a=p.parse_args()
 sys.path.insert(0,str(OP/'kit'));import agent_kit as official
 spec=importlib.util.spec_from_file_location('marketing_request_glue_verified',Path(__file__).with_name('marketing_request_glue.py'));h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
 h.capture_original_sdk(official,OP)
 source=a.source.resolve(strict=True);pins={n:hashlib.sha256(h.raw(source/n)).hexdigest() for n in h.EXACT4}
 if pins['forge.json']!=a.forge_sha:raise ValueError('expected forge mismatch')
 h.PinnedBusinessTransport(SimpleNamespace(),source,pins,official)
 print(json.dumps({'status':'verified_source_only','exact4':pins,'source_version':json.loads((source/'forge.json').read_text())['version'],'SDK7_verified':True,'business_tool_calls':0,'actual_Model_calls':0,'wallet_or_signer':False,'HTTP_POSTs':0}))
if __name__=='__main__':main()
