"""Replay v2 external QA with anonymous synthetic capacity stand-in; preserve failures."""
from pathlib import Path
import argparse,hashlib,json,subprocess,sys,tempfile

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--operator',type=Path,required=True);p.add_argument('--sources',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args();operator=args.operator.resolve(strict=True);src=args.sources.resolve(strict=True);here=Path(__file__).resolve().parent
 if not (src/'logic.py').is_file():src=src/'tools/build_customer_context'
 m=json.loads((src/'forge.json').read_text());assert m['version']==2 and m['sha256']['logic.py']=='5c4619d71ffa496c180667f2754c229f48a376dd7b43a5466b4c30c8c67c0c18';assert (operator/'kit').is_dir();args.output.mkdir(parents=True,exist_ok=False)
 with tempfile.TemporaryDirectory(prefix='builder-v2-anonymous-QA-') as temp:
  op=Path(temp)/'operator';root=op/'runtime/qa-build-customer-context-v2-20261125';root.mkdir(parents=True);(op/'kit').symlink_to(operator/'kit',target_is_directory=True);dst=root/'tools/build_customer_context';dst.mkdir(parents=True)
  for n in ['logic.py','test.py','permission.yml','forge.json']:
   b=(src/n).read_bytes()
   if n!='forge.json':assert hashlib.sha256(b).hexdigest()==m['sha256'][n]
   (dst/n).write_bytes(b)
  standin=op/'runtime/customer-offer-canary-class-food-factored-20261125/host_inputs/customer_offer_context.json';standin.parent.mkdir(parents=True);standin.write_bytes((here/'anonshape-fixture.json').read_bytes())
  for n in ['ordinary_toolbox_qa.py','details_qa.py']:(root/n).write_bytes((here/'originals'/n).read_bytes())
  for n in ['ordinary_toolbox_qa.py','details_qa.py']:
   done=subprocess.run([sys.executable,str(root/n)],text=True,capture_output=True,timeout=180);(args.output/(n+'.stdout.txt')).write_text(done.stdout);(args.output/(n+'.stderr.txt')).write_text(done.stderr);assert done.returncode==0,'QA script error: see logs'
  for n in ['ordinary-toolbox-qa-results.json','details-qa-results.json']:(args.output/n).write_bytes((root/n).read_bytes())
  a=json.loads((root/'ordinary-toolbox-qa-results.json').read_text());b=json.loads((root/'details-qa-results.json').read_text());summary={'baseline':a['totals'],'details':b['totals'],'all_inputs_synthetic_including_capacity_standin':True,'actual_expired_capture_read':False,'generated_source_changed':False,'actual_model_market_calls':0,'production_DB_card_wallet_changed':False};(args.output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n');print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':main()
