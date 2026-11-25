"""Replay v2 external file-reader QA in temporary Fake-only roots; no live producer/model/checkout."""
from pathlib import Path
import argparse,hashlib,json,shutil,subprocess,sys,tempfile

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--operator',type=Path,required=True);parser.add_argument('--sources',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
 operator=args.operator.resolve(strict=True);sources=args.sources.resolve(strict=True);here=Path(__file__).resolve().parent;src=sources/'tools/read_customer_offers';manifest=json.loads((src/'forge.json').read_text());assert manifest['version']==2 and manifest['sha256']['logic.py']=='a122aed15c9462dfb6ed2c77665e6fbb82de7720633adb03ccf0ec7b1b4e45ff';assert (operator/'kit').is_dir();args.output.mkdir(parents=True,exist_ok=False)
 with tempfile.TemporaryDirectory(prefix='customer-offers-v2-Fake-only-') as temp:
  op=Path(temp)/'operator';root=op/'runtime/qa-read-customer-offers-v2-20261125';root.mkdir(parents=True);(op/'kit').symlink_to(operator/'kit',target_is_directory=True);dst=root/'tools/read_customer_offers';dst.mkdir(parents=True)
  for filename in ['logic.py','test.py','permission.yml','forge.json']:
   data=(src/filename).read_bytes()
   if filename!='forge.json':assert hashlib.sha256(data).hexdigest()==manifest['sha256'][filename]
   (dst/filename).write_bytes(data)
  for filename in ['ordinary_toolbox_qa.py','continuation_qa.py']:(root/filename).write_bytes((here/'originals'/filename).read_bytes())
  for filename in ['ordinary_toolbox_qa.py','continuation_qa.py']:
   p=subprocess.run([sys.executable,str(root/filename)],text=True,capture_output=True,timeout=120);(args.output/(filename+'.stdout.txt')).write_text(p.stdout);(args.output/(filename+'.stderr.txt')).write_text(p.stderr);assert p.returncode==0,'QA harness failed: see logs'
  for filename in ['ordinary-toolbox-qa-results.json','continuation-qa-results.json']:shutil.copyfile(root/filename,args.output/filename)
  a=json.loads((root/'ordinary-toolbox-qa-results.json').read_text());b=json.loads((root/'continuation-qa-results.json').read_text());summary={'regression':a['totals'],'continuation':{'passed':b['passed'],'failed':b['failed']},'actual_prod_cache_card_DB_write':False,'market_calls':0,'model_calls':0,'credentials_copied':False,'source_unchanged':True,'actual_class_model_multi_turn_latency_or_TTL_test':False,'source_auth_or_checkout_complete_claim':False};(args.output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n');print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':main()
