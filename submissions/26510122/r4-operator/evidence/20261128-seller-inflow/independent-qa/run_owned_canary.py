"""Own-group bound wrapper for the explicit one-shot read-only market canary."""
import argparse,importlib.util,json
from pathlib import Path

def main():
 p=argparse.ArgumentParser();p.add_argument('--operator',type=Path,required=True);p.add_argument('--source',type=Path,required=True);p.add_argument('--dependency-dir',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--logic-sha',required=True);p.add_argument('--allow-read-only-market',action='store_true');p.add_argument('--verify-coverage',action='store_true');a=p.parse_args();assert a.allow_read_only_market
 op=a.operator.resolve(strict=True);output=a.output.resolve();output.relative_to(op/'runtime');logs=output.with_name(output.name+'-launcher');logs.mkdir(mode=0o700);path=op/'src/r4_operator_host/seller_marketing_host.py';spec=importlib.util.spec_from_file_location('bounded_readonly_canary_host',path);host=importlib.util.module_from_spec(spec);spec.loader.exec_module(host)
 command=[str(op/'.venv/bin/python'),'-B',str(Path(__file__).with_name('live_readonly_sdk_canary.py')),'--operator',str(op),'--source',str(a.source.resolve(strict=True)),'--dependency-dir',str(a.dependency_dir.resolve(strict=True)),'--output',str(output),'--logic-sha',a.logic_sha,'--allow-read-only-market']
 if a.verify_coverage:command.append('--verify-coverage')
 result=host.run_owned(command,75,logs);(logs/'safe-result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result));raise SystemExit(0 if result.get('passed') is True else 1)
if __name__=='__main__':main()
