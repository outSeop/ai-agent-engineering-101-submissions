"""Staged host plumbing only. No loop, daemon, publication implementation or market selection."""
from copy import deepcopy
from hashlib import sha256,sha1
from importlib.util import module_from_spec,spec_from_file_location
import inspect,json,math,re,sys
from pathlib import Path
from types import SimpleNamespace
import time

SLATE_RELEASE='forum_native_slate_runtime_v2_host3_20261126'
SLATE_MANIFEST='f1a3296e4260ae9b452b6dacc9190e9733a6a28623774eba69baffb2256d285b'
BACKGROUND_RELEASE='forum_official_background_runtime_v1'
BACKGROUND_MANIFEST='49854da01419b4a49b88a5d7123375ef03f1f7a182cceb3fe7b301c4d2594f2d'
CAMPAIGN_SHA='65d4a1e390e2fcac0f424d459562673bd06097105eeefbfa28e8acba17a83c54'
CANARY_DEP_SHA='4b773bec4dc06eb4905cbb03eb9817960ad653a9e40fb0f37afeb5af35d2c67c'
EXACT4={'logic.py','test.py','permission.yml','forge.json'}
FORMATTER3_PINS={'logic.py': '836bda781fcc11292b390872a720e2311589f6e94f4586462008e7a07d2514ce', 'test.py': '45b27d68309eb852220851988bf1314596c4a4e93749215bc4bf500055b482ea', 'permission.yml': '9e7b6d7c63beccaceb6e8811a7b33801e7b2aa7b1e57c113b4e4754d8719cb0c', 'forge.json': '31b65409af5d35ae152d7d6db352b9900d24dc9990d6c1f0b830ba58394eb39b'}
SOURCE_KEYS={'schema','observed_at','valid_until','spotlight_allowed','own_spotlight_history','items','reply_options'}
ITEM_KEYS={'sku','name','grade','price','category','expiry','certificate','spotlight_eligible'}
SENSITIVE=re.compile(r'-----BEGIN (?:[A-Z ]*)PRIVATE KEY-----|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|(?:gh[pousr]_|sk-)[A-Za-z0-9_-]{15,}|0x[0-9a-fA-F]{40,64}(?![0-9a-fA-F])')

def raw(path):
 path=Path(path)
 if path.resolve(strict=True)!=path or not path.is_file():raise ValueError('noncanonical artifact')
 return path.read_bytes()

def load(name,path):
 spec=spec_from_file_location(name,path);module=module_from_spec(spec);spec.loader.exec_module(module);return module

def package(operator,release,pin,key):
 root=operator/'deploy'/release;content=raw(root/'MANIFEST.json')
 if sha256(content).hexdigest()!=pin:raise ValueError('artifact manifest mismatch')
 files=json.loads(content)[key]
 for name,expected in files.items():
  leaf=Path(name)
  if leaf.is_absolute() or '..' in leaf.parts or sha256(raw(root/leaf)).hexdigest()!=expected:raise ValueError('artifact source mismatch')
 return root,files

def capture_original_sdk(official,operator):
 """Call BEFORE install mutates official.Mind/Toolbox; hold original class objects."""
 operator=Path(operator).resolve(strict=True);rows=json.loads(raw(operator/'sources/upstream.json'))['files']
 if len(rows)!=7:raise ValueError('SDK7 required')
 for row in rows:
  data=raw(operator/'kit'/row['name'])
  if sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()!=row['upstream_git_blob_sha']:raise ValueError('SDK source mismatch')
 expected=operator/'kit/agent_kit.py'
 for cls,method in [(official.Mind,'run_once'),(official.Toolbox,'run')]:
  if cls.__module__!='agent_kit' or Path(inspect.getsourcefile(cls.__dict__[method])).resolve()!=expected:raise ValueError('original SDK classes must be captured before managed install')
 return SimpleNamespace(Mind=official.Mind,Toolbox=official.Toolbox,sdk7_verified=True,run_once=official.Mind.run_once)

class PinnedBusinessTransport:
 """Same SDK toolbox+ctx for slate/reconcile/publish. No signer/pay capability."""
 def __init__(self,toolbox,source,pins,official):
  self.toolbox,self.source,self.pins=toolbox,Path(source).resolve(strict=True),dict(pins)
  self.official=official
  self.verify()
 def verify(self):
  if set(self.pins)!=EXACT4:raise ValueError('exact genuine four required')
  data={name:raw(self.source/name) for name in EXACT4}
  if {n:sha256(b).hexdigest() for n,b in data.items()}!=self.pins:raise ValueError('genuine source drift')
  record=json.loads(data['forge.json'])
  if record.get('tool')!='forum_marketing' or type(record.get('version')) is not int or record['version']<8 or record.get('sha256')!={n:h for n,h in self.pins.items() if n!='forge.json'}:raise ValueError('genuine provenance mismatch')
  permission=self.official.forge_runner.parse_permission(data['permission.yml'].decode())['permission']
  if (any(permission.get(k) for k in ['wallet','exec','handles']) or permission.get('pay_limit',0)!=0
      or set(permission.get('network',[]))!={'market.ourolabs.ai'} or permission.get('identity')!=['shop']
      or permission.get('write')!=['state/r4-benefits'] or permission.get('timeout')!=40):raise ValueError('unexpected business capability')
 def __call__(self,args):
  if not isinstance(args,dict) or args.get('action') not in ('slate_context','reconcile','publish'):raise ValueError('unsupported tool operation')
  if args['action']!='publish' and set(args)!={'action'}:raise ValueError('unexpected tool args')
  if args['action']=='publish' and set(args)!={'action','decision'}:raise ValueError('unexpected publish args')
  self.verify()
  result=self.toolbox.run('forum_marketing','call',deepcopy(args),d=self.source)
  if not result.get('ok') or not isinstance(result.get('result'),dict):return {'status':'forum_tool_unavailable'}
  value=result['result']
  return value if args['action']=='slate_context' else public_outcome(value)

def public_outcome(value):
 if (type(value) is not dict or not set(value)<={'status','post'} or type(value.get('status')) is not str
     or not re.fullmatch('[a-z][a-z0-9_]{0,79}',value['status'])
     or ('post' in value and value['post'] is not None and (type(value['post']) is not int or value['post']<=0))):raise ValueError('unexpected or private publication outcome')
 return deepcopy(value)

def public_source(envelope,now):
 """Protocol/privacy validation only; genuine tools own eligibility and matching."""
 if not isinstance(envelope,dict) or not isinstance(envelope.get('status'),str):raise ValueError('invalid source envelope')
 if envelope['status']!='options':
  if not re.fullmatch('[a-z][a-z0-9_]{0,79}',envelope['status']):raise ValueError('invalid blocked status')
  return {'status':envelope['status']}
 if set(envelope)!={'status','source'}:raise ValueError('unexpected source envelope keys')
 source=envelope['source']
 if not isinstance(source,dict) or set(source)!=SOURCE_KEYS or source['schema']!='outseop-r4.forum-candidates.v1':raise ValueError('unexpected public source schema')
 if (type(source['observed_at']) is not int or type(source['valid_until']) is not int
     or not source['observed_at']<=now<source['valid_until']<=source['observed_at']+150):raise ValueError('stale public source')
 if type(source['spotlight_allowed']) is not bool or type(source['items']) is not list or len(source['items'])>2000:raise ValueError('invalid public source lists')
 for row in source['items']:
  if type(row) is not dict or set(row)!=ITEM_KEYS:raise ValueError('private or unknown item fields')
 if type(source['reply_options']) is not list or len(source['reply_options'])>8:raise ValueError('invalid public replies')
 for row in source['reply_options']:
  if type(row) is not dict or set(row)!={'thread','request','eligible'} or type(row['eligible']) is not list:raise ValueError('unknown public reply fields')
  if any(type(pair) is not dict or set(pair)!={'sku','grade'} for pair in row['eligible']):raise ValueError('unknown reply pair fields')
 if type(source['own_spotlight_history']) is not list or len(source['own_spotlight_history'])>512:raise ValueError('invalid public history')
 for row in source['own_spotlight_history']:
  if type(row) is not dict or set(row)!={'grade','category','at'}:raise ValueError('unknown history fields')
 content=json.dumps(source,ensure_ascii=False,allow_nan=False,separators=(',',':'))
 if len(content.encode())>2*1024*1024 or SENSITIVE.search(content):raise ValueError('unsafe or oversized public context')
 return deepcopy(source)

def reviewed_formatter(source,pins):
 source=Path(source)
 if set(pins)!=EXACT4 or pins!=FORMATTER3_PINS:raise ValueError('reviewed formatter3 exact genuine four required')
 files={name:raw(source/name) for name in EXACT4}
 if {name:sha256(content).hexdigest() for name,content in files.items()}!=pins:raise ValueError('formatter source drift')
 record=json.loads(files['forge.json'])
 if (record.get('tool')!='prioritize_forum_candidates' or type(record.get('version')) is not int or record.get('version')!=3
     or record.get('sha256')!={n:h for n,h in pins.items() if n!='forge.json'}):raise ValueError('genuine formatter3 required')
 # Match the same read-only/no-identity capability contract used by ordinary_context.
 import forge_runner
 permission=forge_runner.parse_permission(files['permission.yml'].decode()).get('permission') or {}
 if any(permission.get(k) for k in ['network','write','identity','wallet','exec','handles']) or permission.get('pay_limit',0)!=0:raise ValueError('formatter must remain read-only without identity or wallet')
 return source

def build_stage(native_sdk,coordinator,operator,root,agent,model,ctx,*,execute,formatter_source,formatter_pins,runtime_operator=None,stock=None,clock=time.time):
 """Bind once. Does NOT call tick, start any loop, join, publish or modify live files."""
 operator=Path(operator).resolve(strict=True);root=Path(root).resolve(strict=True)
 if isinstance(execute,PinnedBusinessTransport):
  if Path(execute.toolbox.root).resolve()!=root or execute.toolbox.ctx is not ctx:raise ValueError('business transport must use the same root and ctx')
  execute.verify()
 elif runtime_operator is None:raise ValueError('unverified synthetic transport needs explicit isolated runtime root')
 if not getattr(native_sdk,'sdk7_verified',False) or native_sdk.Mind.run_once is not native_sdk.run_once:raise ValueError('original SDK run_once changed')
 bundle,pins=package(operator,SLATE_RELEASE,SLATE_MANIFEST,'file_sha256')
 background_root,_=package(operator,BACKGROUND_RELEASE,BACKGROUND_MANIFEST,'files')
 campaign_path=operator/'deploy/forum_campaign_operator.py'
 if sha256(raw(campaign_path)).hexdigest()!=CAMPAIGN_SHA:raise ValueError('campaign host source drift')
 scope=load('reviewed_native_forum_slate_request_glue',bundle/'host/r4_forum_slate_host.py')
 background=load('reviewed_official_background_request_glue',background_root/'r4_forum_official_background_host.py')
 dependency=operator/'deploy/forum_official_mind_canary.py'
 if sha256(raw(dependency)).hexdigest()!=CANARY_DEP_SHA:raise ValueError('campaign import dependency drift')
 prior=sys.modules.get('forum_official_mind_canary')
 try:
  sys.modules['forum_official_mind_canary']=load('verified_campaign_import_dependency',dependency)
  campaign=load('reviewed_campaign_request_glue',campaign_path)
 finally:
  if prior is None:sys.modules.pop('forum_official_mind_canary',None)
  else:sys.modules['forum_official_mind_canary']=prior
 source=reviewed_formatter(formatter_source,formatter_pins);exact=dict(formatter_pins)
 def acquire():return public_source(execute({'action':'slate_context'}),clock())
 def native(facts):
  reviewed_formatter(source,exact)
  return scope.ordinary_context(native_sdk,source,exact,facts)
 coordinator.execute=scope.ScopedExecutor(execute,acquire,native,clock=clock)
 hook=background.install_tick(native_sdk,coordinator,Path(runtime_operator or operator),root,agent,model,ctx,campaign=campaign,stock=stock)
 hook.now=clock;coordinator.execute.audit=hook.audit
 original_native=coordinator.execute.native_context
 def audited_native(facts):
  hook.audit('native_input',facts);result=original_native(facts);hook.audit('native_result',result);return result
 coordinator.execute.native_context=audited_native
 hook.staging_contract={'connected_to_running_main':False,'new_loop_created':False,'same_business_transport_for_source_reconcile_publish':True,'SDK7_verified':True,'original_run_once_preserved':True,'business_selection_or_match_rules_added_by_host':False,'business_genuine_pins_verified':isinstance(execute,PinnedBusinessTransport),'genuine_formatter_version':3,'producer_and_publisher_own_business_eligibility':True}
 return hook
