from pathlib import Path
import argparse,hashlib,json,subprocess,sys,tempfile

def main():
 p=argparse.ArgumentParser(description='External QA adapter; temporary synthetic snapshot only.');p.add_argument('--operator',type=Path,required=True);p.add_argument('--sources',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args();operator=args.operator.resolve(strict=True);src=args.sources.resolve(strict=True);here=Path(__file__).resolve().parent
 if not (src/'logic.py').is_file():src=src/'tools/render_public_product_reply'
 m=json.loads((src/'forge.json').read_text());assert m['version']==2 and m['sha256']['logic.py']=='d6c78d2ba0b9db6023c9657c7878a927dd919b41adaca9b912580b56693bda2b';args.output.mkdir(parents=True,exist_ok=False)
 with tempfile.TemporaryDirectory(prefix='public-reply-synthetic-QA-') as temp:
  op=Path(temp)/'operator';root=op/'runtime/qa-render-public-product-reply-v2-20261125';root.mkdir(parents=True);(op/'kit').symlink_to(operator/'kit',target_is_directory=True);dst=root/'tools/render_public_product_reply';dst.mkdir(parents=True)
  for n in ['logic.py','test.py','permission.yml','forge.json']:
   b=(src/n).read_bytes()
   if n!='forge.json':assert hashlib.sha256(b).hexdigest()==m['sha256'][n]
   (dst/n).write_bytes(b)
  script=root/'ordinary_toolbox_qa.py';script.write_bytes((here/'originals/ordinary_toolbox_qa.py').read_bytes());p=subprocess.run([sys.executable,str(script)],text=True,capture_output=True,timeout=120);(args.output/'stdout.txt').write_text(p.stdout);(args.output/'stderr.txt').write_text(p.stderr);assert p.returncode==0,'QA harness error: see logs'
  data=(root/'ordinary-toolbox-qa-results.json').read_bytes();(args.output/'ordinary-toolbox-qa-results.json').write_bytes(data);r=json.loads(data);summary={'totals':r['totals'],'all_inputs_synthetic':True,'actual_Broker_classModel_finalHTTP_E2E_done':False,'actual_model_market_DB_wallet_calls':0,'generated_source_changed':False};(args.output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n');print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':main()
