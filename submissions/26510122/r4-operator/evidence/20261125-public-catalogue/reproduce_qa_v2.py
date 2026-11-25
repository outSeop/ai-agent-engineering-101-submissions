from pathlib import Path
import argparse,subprocess,sys,tempfile
P=argparse.ArgumentParser();P.add_argument('--operator-kit',required=True);P.add_argument('--version',choices=('v1','v2'),default='v1');P.add_argument('--kind',choices=('ordinary','lifetime','targeted'),required=True);P.add_argument('--output',required=True);a=P.parse_args()
root=Path(__file__).resolve().parent;op=Path(a.operator_kit).resolve().parent;Path(a.output).mkdir(parents=True,exist_ok=True)
if not (op/'kit/agent_kit.py').is_file():raise SystemExit('operator-kit must contain agent_kit.py')
name={'ordinary':'ordinary_toolbox_qa.py','lifetime':'independent_lifetime_qa.py','targeted':'targeted_v2_qa.py'}[a.kind]
source=root/('qa-'+a.version)/'original'/name;text=source.read_text()
old="Path('/home/seop/.local/share/ourolabs-r4-checkout/submissions/26510122/r4-operator')"
if text.count(old)!=1:raise SystemExit('unexpected QA adapter source shape')
text=text.replace(old,'Path('+repr(str(op))+')')
with tempfile.TemporaryDirectory(prefix='public-catalogue-QA-adapter-') as temp:
 script=Path(temp)/name;script.write_text(text)
 raise SystemExit(subprocess.call([sys.executable,str(script),'--sources',str(root/('sources-'+a.version)/'tools/public_catalogue'),'--output',a.output]))
