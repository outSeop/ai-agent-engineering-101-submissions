"""Review-only cold-start host wrapper. No reload, service operation or task migration."""
from hashlib import sha256
from importlib.util import module_from_spec,spec_from_file_location
import argparse,json,sys
from pathlib import Path
from types import SimpleNamespace
OP=Path('/home/seop/.local/share/ourolabs-r4-checkout/submissions/26510122/r4-operator')
PROD=OP.parent/'round-4'
SCOPE=OP/'runtime/marketing-request-20261127-method/scope2-formatter3'
SCOPE_MANIFEST='dde805dbc592e7323a22e5790c1553282bdacc3741c6202c891431cf0095eb21'
LAUNCHER_SHA='831fa941b826ff0bd06b373ed05a2e48732bf9238d62ce38f5996e3de093445d'
OPERATOR_RUNNER_SHA='ea82f78946d14beceaa55f71ee26411a070a0d7e6df37c1f3808c99ecf21907e'
SLATE_SHA='f1a3296e4260ae9b452b6dacc9190e9733a6a28623774eba69baffb2256d285b'

def read(path):
 if path.resolve(strict=True)!=path or not path.is_file():raise ValueError('noncanonical reviewed input')
 return path.read_bytes()
def load(name,path):
 spec=spec_from_file_location(name,path);m=module_from_spec(spec);spec.loader.exec_module(m);return m

def reviewed_glue():
 raw=read(SCOPE/'MANIFEST.json')
 if sha256(raw).hexdigest()!=SCOPE_MANIFEST:raise ValueError('reviewed scope manifest changed')
 m=json.loads(raw)
 if m['connected_to_cached_production_loop'] is not False:raise ValueError('unexpected scope admission')
 for name,pin in m['files'].items():
  rel=Path(name)
  if rel.is_absolute() or '..' in rel.parts or sha256(read(SCOPE/rel)).hexdigest()!=pin:raise ValueError('reviewed host file drift')
 return load('cold_start_reviewed_marketing_glue',SCOPE/'marketing_request_glue.py')

def binding(path,expected,glue,official):
 data=read(path)
 if sha256(data).hexdigest()!=expected:raise ValueError('marketing binding manifest mismatch')
 value=json.loads(data)
 if set(value)!={'version','scope_manifest_sha256','original_launcher_sha256','native2_manifest_sha256','tool_source','tool_exact4','genuine_tool_version','formatter_source','formatter_exact4','genuine_formatter_version'}:raise ValueError('unexpected cold-start binding schema')
 if (type(value['version']) is not int or value['version']!=1 or value['scope_manifest_sha256']!=SCOPE_MANIFEST or value['original_launcher_sha256']!=LAUNCHER_SHA
     or value['native2_manifest_sha256']!=SLATE_SHA or value['tool_source']!=str(PROD/'tools/forum_marketing')
     or type(value['genuine_tool_version']) is not int or value['genuine_tool_version']<8):raise ValueError('unreviewed cold-start binding')
 source=Path(value['tool_source']);glue.PinnedBusinessTransport(SimpleNamespace(),source,value['tool_exact4'],official)
 if json.loads(read(source/'forge.json'))['version']!=value['genuine_tool_version']:raise ValueError('wrong new genuine tool version')
 formatter=Path(value['formatter_source'])
 if (not (formatter.is_relative_to(OP/'runtime') or formatter.is_relative_to(OP/'deploy'))
     or type(value['genuine_formatter_version']) is not int or value['genuine_formatter_version']!=3):raise ValueError('unreviewed formatter binding')
 glue.reviewed_formatter(formatter,value['formatter_exact4'])
 glue.package(OP,glue.SLATE_RELEASE,SLATE_SHA,'file_sha256')
 return value

def wrap_install(original,glue,tool_source,pins,*,formatter_source,formatter_pins,operator=OP):
 original_install=original.install
 def install(official,**options):
  sdk=glue.capture_original_sdk(official,operator)
  # Keep original stock/customer/app/loop definitions; skip old startup-cached slate binding only.
  original_install(official,**{**options,'forum_operator':None})
  base=official.Mind
  class ColdStartMarketingMind(base):
   def __init__(self,root,agent,model,toolbox,ctx,roles):
    super().__init__(root,agent,model,toolbox,ctx,roles)
    if self.marketing_coordinator is None:return
    transport=glue.PinnedBusinessTransport(toolbox,tool_source,pins,official)
    self.official_forum_background=glue.build_stage(sdk,self.marketing_coordinator,operator,Path(root),agent,model,ctx,
      execute=transport,formatter_source=formatter_source,formatter_pins=formatter_pins,stock=self.stock_coordinator)
  official.Mind=ColdStartMarketingMind
 original.install=install
 return original_install

def validate_forward(forward):
 if not forward or forward[0] not in ('check','run'):raise ValueError('original launcher check or explicit run required')
 for option,wanted in [('--operator-dir',str(OP)),('--agent-root',str(PROD)),('--owner-file','/home/seop/.config/ourolabs-market/owner-code'),('--port','18805')]:
  if forward.count(option)!=1:raise ValueError('preserved original root/identity/port args required')
  index=forward.index(option)
  if index+1>=len(forward) or forward[index+1]!=wanted:raise ValueError('cannot change original root/identity/port')

def main(argv=None):
 parser=argparse.ArgumentParser(add_help=False);parser.add_argument('--wrapper-manifest-sha',required=True);parser.add_argument('--marketing-binding',type=Path,required=True);parser.add_argument('--marketing-binding-sha',required=True);parser.add_argument('--verify-wrapper-only',action='store_true');args,forward=parser.parse_known_args(argv)
 own=Path(__file__).resolve().parent;manifest=read(own/'MANIFEST.json')
 if sha256(manifest).hexdigest()!=args.wrapper_manifest_sha:raise ValueError('cold wrapper package manifest mismatch')
 for name,pin in json.loads(manifest)['files'].items():
  rel=Path(name)
  if rel.is_absolute() or '..' in rel.parts or sha256(read(own/rel)).hexdigest()!=pin:raise ValueError('cold wrapper source drift')
 glue=reviewed_glue();launcher=PROD/'codex-r4/managed_launcher.py'
 if sha256(read(launcher)).hexdigest()!=LAUNCHER_SHA:raise ValueError('original managed launcher drift')
 sys.path[:0]=[str(OP/'kit'),str(PROD/'codex-r4')];import agent_kit as official
 glue.capture_original_sdk(official,OP)
 cfg=binding(args.marketing_binding.resolve(strict=True),args.marketing_binding_sha,glue,official)
 runner=OP/'run_r4.py'
 if sha256(read(runner)).hexdigest()!=OPERATOR_RUNNER_SHA:raise ValueError('original operator check drift')
 load('reviewed_original_operator_check',runner).check()
 if args.verify_wrapper_only:
  print(json.dumps({'status':'cold_start_sources_verified_only','SDK7_verified':True,'join_or_wallet_or_Model_or_POST':False,'task_migration_or_URL_preservation_guaranteed':False}));return
 validate_forward(forward)
 original=load('reviewed_original_managed_launcher',launcher)
 wrap_install(original,glue,Path(cfg['tool_source']),cfg['tool_exact4'],formatter_source=Path(cfg['formatter_source']),formatter_pins=cfg['formatter_exact4'])
 sys.argv=[str(launcher),*forward];original.main()
if __name__=='__main__':main()
