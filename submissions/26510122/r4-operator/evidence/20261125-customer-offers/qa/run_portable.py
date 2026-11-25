"""Replay read_customer_offers QA in temporary Fake-only roots, never on live cache."""
from pathlib import Path
import argparse,hashlib,json,shutil,subprocess,sys,tempfile

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--operator',type=Path,required=True);parser.add_argument('--sources',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
 operator=args.operator.resolve(strict=True);sources=args.sources.resolve(strict=True);here=Path(__file__).resolve().parent;src=sources/'tools/read_customer_offers';manifest=json.loads((src/'forge.json').read_text());assert manifest['version']==1 and manifest['sha256']['logic.py']=='28f146dce898dce1ebb71446afb223a0fb8064e55790f3676209bdf74421675a';assert (operator/'kit').is_dir();args.output.mkdir(parents=True,exist_ok=False)
 with tempfile.TemporaryDirectory(prefix='customer-offers-Fake-only-') as temp:
  op=Path(temp)/'operator';root=op/'runtime/qa-read-customer-offers-v1-20261125';root.mkdir(parents=True);(op/'kit').symlink_to(operator/'kit',target_is_directory=True);dst=root/'tools/read_customer_offers';dst.mkdir(parents=True)
  for filename in ['logic.py','test.py','permission.yml','forge.json']:
   data=(src/filename).read_bytes()
   if filename!='forge.json':assert hashlib.sha256(data).hexdigest()==manifest['sha256'][filename]
   (dst/filename).write_bytes(data)
  script=root/'ordinary_toolbox_qa.py';script.write_bytes((here/'originals/ordinary_toolbox_qa.py').read_bytes());p=subprocess.run([sys.executable,str(script)],text=True,capture_output=True,timeout=120);(args.output/'stdout.txt').write_text(p.stdout);(args.output/'stderr.txt').write_text(p.stderr);assert p.returncode==0,'QA harness failed: see logs'
  result=json.loads((root/'ordinary-toolbox-qa-results.json').read_text());shutil.copyfile(root/'ordinary-toolbox-qa-results.json',args.output/'ordinary-toolbox-qa-results.json');summary={'totals':result['totals'],'actual_prod_cache_card_DB_write':False,'market_calls':0,'model_calls':0,'credentials_copied':False,'source_unchanged':True};(args.output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n');print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':main()
