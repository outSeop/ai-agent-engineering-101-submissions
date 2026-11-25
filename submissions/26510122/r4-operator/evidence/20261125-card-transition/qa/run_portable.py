"""Replay external QA infrastructure in temporary Fake-only roots; never run tools on production card."""
from pathlib import Path
import argparse,hashlib,json,shutil,subprocess,sys,tempfile

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--operator',required=True,type=Path,help='Operator checkout containing kit/; credentials and live state are not copied')
 parser.add_argument('--sources',required=True,type=Path,help='Source bundle containing tools/ and tools/.deprecated/apply_staged_card@1')
 parser.add_argument('--output',required=True,type=Path,help='New output directory for safe synthetic results')
 args=parser.parse_args();operator=args.operator.resolve(strict=True);sources=args.sources.resolve(strict=True);here=Path(__file__).resolve().parent
 assert (operator/'kit/agent_kit.py').is_file() or (operator/'kit/agent_kit').is_dir(), 'official kit path missing'
 expected={'apply_staged_card':('4fecb5a59aba74173e10f88a3c79171daa8f729c6ac37b2f037aa7d4ced05c90',2),'stage_representative_card':('e883b594583e1abf8587a963154d58020a0f0e214451dee1fa3c771d11514fbb',1),'publish_shop_info':('cb3c5a6e5c6ca36fb329e4b2279c2b718a304386665707ecaf9a7e21eb887dc2',1)}
 args.output.mkdir(parents=True,exist_ok=False)
 with tempfile.TemporaryDirectory(prefix='card-qa-Fake-only-') as temp:
  op=Path(temp)/'operator';root=op/'runtime/qa-apply-staged-card-v2-20261125';root.mkdir(parents=True);(op/'kit').symlink_to(operator/'kit',target_is_directory=True)
  for tool,(logicsha,version) in expected.items():
   src=sources/'tools'/tool;manifest=json.loads((src/'forge.json').read_text());assert manifest['version']==version and manifest['tool']==tool and manifest['sha256']['logic.py']==logicsha
   dst=root/'tools'/tool;dst.mkdir(parents=True)
   for filename in ['logic.py','test.py','permission.yml','forge.json']:
    raw=(src/filename).read_bytes()
    if filename!='forge.json':assert hashlib.sha256(raw).hexdigest()==manifest['sha256'][filename]
    (dst/filename).write_bytes(raw)
  archived=sources/'tools/.deprecated/apply_staged_card@1'
  if not archived.is_dir():archived=sources/'.deprecated/apply_staged_card@1'
  archived_dst=root/'.deprecated/apply_staged_card@1';archived_dst.mkdir(parents=True)
  for filename in ['logic.py','test.py','permission.yml','forge.json']:(archived_dst/filename).write_bytes((archived/filename).read_bytes())
  assert hashlib.sha256((archived_dst/'logic.py').read_bytes()).hexdigest()=='14143d58859493f56b3b736dab10fe384211d8c0c8b58a1b3db59a50a9d5500f'
  for filename in ['ordinary_toolbox_qa.py','lifecycle_qa.py']:(root/filename).write_bytes((here/'originals'/filename).read_bytes())
  for filename in ['ordinary_toolbox_qa.py','lifecycle_qa.py']:
   done=subprocess.run([sys.executable,str(root/filename)],capture_output=True,text=True,timeout=120)
   (args.output/(filename+'.stdout.txt')).write_text(done.stdout)
   (args.output/(filename+'.stderr.txt')).write_text(done.stderr)
   assert done.returncode==0, filename+' failed: see output logs'
  for filename in ['ordinary-toolbox-qa-results.json','lifecycle-qa-results.json']:shutil.copyfile(root/filename,args.output/filename)
  regression=json.loads((root/'ordinary-toolbox-qa-results.json').read_text());lifecycle=json.loads((root/'lifecycle-qa-results.json').read_text())
  summary={'regression':regression['totals'],'lifecycle':lifecycle['totals'],'actual_prod_card_write':False,'actual_market_calls':0,'actual_model_calls':0,'credentials_copied':False,'root':'Temporary Fake-only directories; op/kit is linked read-only by convention; original generated sources copied unchanged.'}
  (args.output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n');print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':main()
