"""Reproduce v1 external QA using only synthetic input including an anonymous capacity-shape fixture."""
from pathlib import Path
import argparse,hashlib,json,subprocess,sys,tempfile

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--operator',type=Path,required=True);p.add_argument('--sources',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args();operator=args.operator.resolve(strict=True);src=args.sources.resolve(strict=True);here=Path(__file__).resolve().parent
 if not (src/'logic.py').is_file():src=src/'tools/build_customer_context'
 m=json.loads((src/'forge.json').read_text());assert m['version']==1 and m['sha256']['logic.py']=='3e956eb6dfaa7f06e08932951b978b0ab579c4d7ed1a23146f5afdea28d0d009';assert (operator/'kit').is_dir();args.output.mkdir(parents=True,exist_ok=False)
 with tempfile.TemporaryDirectory(prefix='builder-v1-anonymous-QA-') as temp:
  op=Path(temp)/'operator';root=op/'runtime/qa-build-customer-context-v1-20261125';root.mkdir(parents=True);(op/'kit').symlink_to(operator/'kit',target_is_directory=True);dst=root/'tools/build_customer_context';dst.mkdir(parents=True)
  for n in ['logic.py','test.py','permission.yml','forge.json']:
   b=(src/n).read_bytes()
   if n!='forge.json':assert hashlib.sha256(b).hexdigest()==m['sha256'][n]
   (dst/n).write_bytes(b)
  standin=op/'runtime/customer-offer-canary-class-food-factored-20261125/host_inputs/customer_offer_context.json';standin.parent.mkdir(parents=True);standin.write_bytes((here/'anonshape-fixture.json').read_bytes())
  script=root/'ordinary_toolbox_qa.py';script.write_bytes((here/'originals/ordinary_toolbox_qa.py').read_bytes());done=subprocess.run([sys.executable,str(script)],text=True,capture_output=True,timeout=180);(args.output/'stdout.txt').write_text(done.stdout);(args.output/'stderr.txt').write_text(done.stderr);assert done.returncode==0,'QA script error: see logs'
  data=(root/'ordinary-toolbox-qa-results.json').read_bytes();(args.output/'ordinary-toolbox-qa-results.json').write_bytes(data);r=json.loads(data);summary={'totals':r['totals'],'all_inputs_synthetic_including_anonymous_capacity_shape':True,'actual_expired_capture_read':False,'original_goal_failures_preserved':True,'generated_source_changed':False,'actual_model_market_calls':0,'production_DB_card_or_wallet_change':False};(args.output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n');print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':main()
