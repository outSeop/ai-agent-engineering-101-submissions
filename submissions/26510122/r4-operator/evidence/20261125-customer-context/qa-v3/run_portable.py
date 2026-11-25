from pathlib import Path
import argparse,hashlib,json,subprocess,sys,tempfile

def main():
 p=argparse.ArgumentParser(description='External QA adapter; all inputs anonymous/synthetic, no live market/model.');p.add_argument('--operator',type=Path,required=True);p.add_argument('--sources',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args();operator=args.operator.resolve(strict=True);src=args.sources.resolve(strict=True);here=Path(__file__).resolve().parent
 if not (src/'logic.py').is_file():src=src/'tools/build_customer_context'
 m=json.loads((src/'forge.json').read_text());assert m['version']==3 and m['sha256']['logic.py']=='095dc600fe30958759a058b093ee1c210fb9b3f1f7c3157dcd034061e70dcf84';args.output.mkdir(parents=True,exist_ok=False)
 with tempfile.TemporaryDirectory(prefix='builder-v3-anonymous-QA-') as temp:
  op=Path(temp)/'operator';root=op/'runtime/qa-build-customer-context-v3-20261125';root.mkdir(parents=True);(op/'kit').symlink_to(operator/'kit',target_is_directory=True);dst=root/'tools/build_customer_context';dst.mkdir(parents=True)
  for n in ['logic.py','test.py','permission.yml','forge.json']:
   b=(src/n).read_bytes()
   if n!='forge.json':assert hashlib.sha256(b).hexdigest()==m['sha256'][n]
   (dst/n).write_bytes(b)
  for rel in ['runtime/customer-offer-canary-class-food-factored-20261125/host_inputs/customer_offer_context.json','runtime/qa-build-customer-context-v1-20261125/anonshape-fixture.json']:
   target=op/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((here/'anonshape-fixture.json').read_bytes())
  for n in ['ordinary_toolbox_qa.py','details_qa.py','capacity86_qa.py']:(root/n).write_bytes((here/'originals'/n).read_bytes())
  for n in ['ordinary_toolbox_qa.py','details_qa.py','capacity86_qa.py']:
   done=subprocess.run([sys.executable,str(root/n)],text=True,capture_output=True,timeout=180);(args.output/(n+'.stdout.txt')).write_text(done.stdout);(args.output/(n+'.stderr.txt')).write_text(done.stderr);assert done.returncode==0,'QA harness error: see logs'
  names=['ordinary-toolbox-qa-results.json','details-qa-results.json','anonymous86-capacity-qa-results.json']
  for n in names:(args.output/n).write_bytes((root/n).read_bytes())
  a,b,c=[json.loads((root/n).read_text()) for n in names];summary={'baseline':a['totals'],'details':b['totals'],'anonymous86':{'passed':c['passed'],'failed':c['failed']},'all_inputs_anonymous_synthetic':True,'actual70_capture_read':False,'actual_market_model_calls':0,'production_changed':False,'actual86_claim':False};(args.output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n');print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':main()
