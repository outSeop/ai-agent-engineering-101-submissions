"""Listener-only assembly; serve requires explicit opt-in. Never joins or starts a Mind loop."""
import argparse,importlib.util,json,os,stat,sys,time
from pathlib import Path
from hashlib import sha256,sha1
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parent))

MARKET='https://market.ourolabs.ai';NAME='outseop-r4'
SHARED={'dispatcher.py':'84e0eca3a0211e80772ed78f2ba3c166902ba0125577e7153b06cc5bb13de0cd','worker_bootstrap.py':'083e127a2e08aa17949aaa808e61b859cee988389afc2073a6aa1b39de612514','refund_admin.py':'d1d5026ceef7f5f9b2e63a81c3c56f459cd708e1d0fd75c560171614520ce80d'}
def protected(path,maximum=4*1024*1024):
 path=Path(path);item=path.lstat()
 if path.resolve(strict=True)!=path or not stat.S_ISREG(item.st_mode) or item.st_uid!=os.getuid() or item.st_nlink!=1 or item.st_mode&0o022 or item.st_size>maximum:raise ValueError('unprotected edge input')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 with os.fdopen(fd,'rb') as stream:return stream.read(maximum+1)
def verify(op,bundle,pin,config):
 if op.resolve(strict=True)!=op or op!=config.operator_root or bundle!=config.runtime_path or pin!=config.runtime_manifest_sha256:raise ValueError('unexpected canonical operator/runtime binding')
 if not (bundle.is_relative_to(op/'runtime') or bundle.is_relative_to(op/'deploy')):raise ValueError('bundle outside operator staging/deploy')
 raw=protected(bundle/'MANIFEST.json')
 if sha256(raw).hexdigest()!=pin:raise ValueError('unreviewed runtime manifest')
 meta=json.loads(raw)
 for name,digest in meta['file_sha256'].items():
  part=Path(name)
  if part.is_absolute() or '..' in part.parts or sha256(protected(bundle/part)).hexdigest()!=digest:raise ValueError('runtime source drift')
 root=op.parent/'round-4'
 for name,digest in SHARED.items():
  if sha256(protected(root/'codex-r4'/name)).hexdigest()!=digest:raise ValueError('original financial dependency drift')
 entries=json.loads(protected(op/'sources/upstream.json'))['files']
 if len(entries)!=7:raise ValueError('SDK7 required')
 for e in entries:
  b=protected(op/'kit'/e['name'])
  if sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()!=e['upstream_git_blob_sha']:raise ValueError('SDK drift')
 return meta

def reviewed_front(pin):
 folder=Path(__file__).resolve().parent;raw=protected(folder/'MANIFEST.json')
 if sha256(raw).hexdigest()!=pin:raise ValueError('unreviewed edge manifest')
 for name,digest in json.loads(raw)['files'].items():
  part=Path(name)
  if part.is_absolute() or '..' in part.parts or sha256(protected(folder/part)).hexdigest()!=digest:raise ValueError('edge source drift')
 source=folder/'front_edge_app.py';raw=protected(source);spec=importlib.util.spec_from_file_location('reviewed_front_edge_app',source);module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;exec(compile(raw,str(source),'exec'),module.__dict__);return module

def original_card_matches(url,address):
 transport=httpx.HTTPTransport(local_address='127.0.0.2',retries=0)
 with httpx.Client(transport=transport,trust_env=False,timeout=2) as c:r=c.get('http://127.0.0.1:18805/.well-known/agent-card.json');r.raise_for_status();card=r.json()
 interfaces=card.get('supportedInterfaces',[])
 return card.get('name')==NAME and 'shop' in card.get('roles',[]) and str(card.get('wallets',{}).get('shop','')).lower()==address.lower() and len(interfaces)==1 and interfaces[0].get('url','').rstrip('/')==url.rstrip('/')

def current_identity(op):
 # Read only; key bytes never copied to a file/env or returned from this function.
 from eth_account import Account
 root=op.parent/'round-4';address=Account.from_key(protected(root/'shop_wallet.key',2048).decode().strip()).address.lower()
 transport=httpx.HTTPTransport(local_address='127.0.0.2',retries=0)
 with httpx.Client(transport=transport,trust_env=False,timeout=8) as c:r=c.get('http://127.0.0.1:18805/.well-known/agent-card.json');r.raise_for_status();card=r.json()
 if card.get('name')!=NAME or 'shop' not in card.get('roles',[]) or str(card.get('wallets',{}).get('shop','')).lower()!=address:raise ValueError('old card identity drift')
 interfaces=card.get('supportedInterfaces',[])
 if len(interfaces)!=1 or interfaces[0].get('protocolBinding')!='JSONRPC':raise ValueError('unexpected old interface')
 url=interfaces[0]['url'].rstrip('/')
 if not url.startswith('https://'):raise ValueError('registered public HTTPS required')
 r=httpx.get(MARKET+'/api/shops',trust_env=False,timeout=12);r.raise_for_status();registry=r.json();rows=[x for x in registry.get('shops',[]) if x.get('name')==NAME]
 if registry.get('round')!=4 or len(rows)!=1 or rows[0].get('url','').rstrip('/')!=url or str(rows[0].get('pubkey','')).lower()!=address:raise ValueError('registry/old-card mismatch')
 return url,address

def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);return module

def assemble(official,op,bundle,pin,ctx,model,*,trace=None,old_request=None,options_override=None,toolbox_factory=None,_front=None,admission=None,config=None,isolated_root=None,host_state_db=None,persistent_engine=False):
 if _front is None or config is None:raise ValueError('reviewed edge module and configuration required before app assembly')
 meta=verify(op,bundle,pin,config);source_root=op.parent/'round-4';root=source_root
 if isolated_root is not None:
  root=Path(isolated_root);info=root.lstat()
  if (not root.is_relative_to(op/'runtime') or root.resolve(strict=True)!=root or not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o700
      or ctx.get('tokens')!={} or ctx.get('addresses')!={} or options_override is None or toolbox_factory is None):raise ValueError('isolated HOST assembly requires owned runtime fixture, empty tool auth and explicit test callbacks')
 sys.path[:0]=[str(bundle),str(source_root/'codex-r4'),str(op/'kit')]
 broker=load('broker_public_catalogue_host_candidate',bundle/'broker_public_catalogue_host_candidate.py')
 if config.semantic_instruction is not None:
  if not isinstance(getattr(broker,'SEMANTIC_INSTRUCTION',None),str):raise ValueError('runtime semantic instruction interface drift')
  broker.SEMANTIC_INSTRUCTION=config.semantic_instruction
 managed=load('edge_managed_public_catalogue',bundle/'managed_runtime_public_catalogue_host_candidate.py')
 class EdgeBudgetBroker(broker.Broker):
  def __init__(self,*args,**kwargs):
   kwargs.update(seconds=40,model_seconds=30,max_steps=1)
   super().__init__(*args,**kwargs)
 managed.Broker=EdgeBudgetBroker
 if options_override is None:
  composition=load('edge_catalogue_composition',bundle/'public_catalogue_composition_candidate.py');toolpins={Path(n).name:v for n,v in meta['file_sha256'].items() if n.startswith('catalogue/')};options=composition.managed_options(op,bundle,official,toolpins)
 else:options=options_override
 auxiliary=json.loads(protected(bundle/'HOST-CONTEXT.json')).get('native_tools',{}) if options_override is None else {}
 if 'public_alternatives' in auxiliary and options_override is None:
  alternative_module=load('verified_public_alternatives_host',bundle/'public_alternatives_host.py')
  from card_source_read_lane import safe_directory
  data_state=op/'runtime/native-customer-context'
  scratch=safe_directory(safe_directory(data_state)/'scratch')
  catalogue_pins={Path(n).name:v for n,v in meta['file_sha256'].items() if n.startswith('catalogue/')}
  record=auxiliary['public_alternatives']
  worker=alternative_module.BoundedAlternatives(bundle/'catalogue',catalogue_pins,bundle/record['directory'],record['files'],op/'kit',scratch)
  worker.verify(official)
  factory=options['catalogue_source_factory']
  def alternatives_factory(execute):
   scope=factory(execute)
   scope.alternatives=alternative_module.ScopedAlternatives(scope,worker,data_state/'stock-state.json')
   return scope
  options={**options,'catalogue_source_factory':alternatives_factory}
 state_db=None;task_store=None
 if persistent_engine and host_state_db is None:raise ValueError('persistent engine requires private HOST database')
 if host_state_db is not None:
  state_path=Path(getattr(host_state_db,'path',host_state_db))
  allowed=root if isolated_root is not None else op/'runtime'
  if not state_path.is_absolute() or not state_path.is_relative_to(allowed):raise ValueError('HOST state outside isolated fixture or operator runtime')
  if persistent_engine and isolated_root is None and state_path!=op/'runtime/a2a-host/state.sqlite3':raise ValueError('live persistent engine must share the router HOST database')
  support=Path(__file__).resolve().parent
  if not (support/'task_state.py').is_file():support=support.parent
  state_module=load('verified_front_task_state',support/'task_state.py')
  continuity_module=load('verified_front_public_continuity',support/'durable_public_continuity.py')
  state_db=state_module.TaskStateDB(state_path);task_store=state_module.SQLiteTaskStore(state_db)
  original_continuity=managed.PublicContinuity
  managed.PublicContinuity=lambda:continuity_module.DurablePublicContinuity(state_db,original_continuity)
 box_class,mind_class,app_factory=managed.managed_classes(official,enable_stock=False,**options)
 box=box_class(root,ctx) if toolbox_factory is None else toolbox_factory(box_class,root,ctx)
 if isolated_root is not None and Path(box.root).resolve()!=root:raise ValueError('isolated toolbox must use the same fixture root')
 agent=json.loads(protected(root/'agent.json'));agent['llm']={'base':'market'}
 mind=mind_class(root,agent,_front.OneDecisionModel(model),box,ctx,['shop'])
 capture_args=(app_factory,root,NAME,mind,box,[ctx['shop_url']])
 app,store=_front.capture_sdk_app(*capture_args) if task_store is None else _front.capture_sdk_app(*capture_args,task_store=task_store)
 edge_args=dict(trace=trace,old_request=old_request,admission=admission,config=config)
 if persistent_engine:edge_args.update(persistent_engine=True,state_db=state_db)
 edge=_front.FrontEdge(app,store,**edge_args);edge.signer=ctx.get('signer');edge.background_loops_started=0;edge.loaded_broker=broker;edge.host_state_db=state_db;edge._runtime_components=(official,root,agent,model,box,ctx);return edge

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--operator',type=Path,required=True);p.add_argument('--edge-manifest-sha',required=True);p.add_argument('--serve',action='store_true');p.add_argument('--sources-only',action='store_true');p.add_argument('--host-state-db',type=Path);p.add_argument('--persistent-engine',action='store_true');args=p.parse_args();os.umask(0o077)
 if args.persistent_engine and args.host_state_db is None:p.error('--persistent-engine requires --host-state-db')
 front=reviewed_front(args.edge_manifest_sha);folder=Path(__file__).resolve().parent;own=protected(folder/'MANIFEST.json')
 if sha256(own).hexdigest()!=args.edge_manifest_sha:raise ValueError('own manifest changed')
 op=args.operator
 if not op.is_absolute() or op.resolve(strict=True)!=op:raise ValueError('canonical operator path required')
 if args.persistent_engine and args.host_state_db!=op/'runtime/a2a-host/state.sqlite3':raise ValueError('live engine requires exact shared router HOST database')
 config_module=load('verified_front_config',folder/'config.py');config=config_module.load_pinned(folder,json.loads(own),operator=op)
 bundle=config.runtime_path.resolve(strict=True);pin=config.runtime_manifest_sha256;verify(op,bundle,pin,config)
 if args.sources_only:
  if args.serve:raise ValueError('sources-only forbids serving')
  print(json.dumps({'status':'sources_verified_only','keys_read':False,'listener_started':False}));return
 if args.serve and json.loads(own).get('sources_only'):raise ValueError('preliminary sources-only package cannot serve')
 url,address=current_identity(op)
 if not args.serve:print(json.dumps({'status':'verified_only','SDK7':True,'original_financial_sources_same':True,'registered_old_URL_wallet_matches':True,'Signer_created':False,'Model_called':False,'joined':False,'listener_started':False}));return
 sys.path[:0]=[str(op/'kit'),str(op.parent/'round-4/codex-r4')];import agent_kit as official
 for name in ('AGENT_LLM_BASE','AGENT_LLM_MODEL','AGENT_LLM_KEY'):os.environ.pop(name,None)
 root=op.parent/'round-4';token=protected(root/'.kit/worker-token',2048).decode().strip()
 if not 16<=len(token)<=1024:raise ValueError('invalid private inference/tool auth')
 key=official.maroo.Wallet.from_hex(protected(root/'shop_wallet.key',2048).decode());signer=official.Signer({'shop':key},root)
 state=op/config.state_dir;state.mkdir(mode=0o700,parents=True,exist_ok=True)
 if state.resolve()!=state or state.stat().st_uid!=os.getuid() or state.stat().st_mode&0o077:raise ValueError('unprotected edge state')
 from admission_gate import AdmissionGate
 gate=None
 if not args.persistent_engine:gate=AdmissionGate(state/'admission.json');gate.initialize_closed()
 official.mk.LOG_FILE=state/'agent-kit-private.log'
 ctx={'market':MARKET,'name':NAME,'shop_url':url,'tokens':{'shop':token},'addresses':{'shop':key.address},'signer':signer}
 model=official.Model({'llm':{'base':'market'}},MARKET,{'tokens':ctx['tokens']})
 try:
  app=assemble(official,op,bundle,pin,ctx,model,trace=state/'edge-trace-private.jsonl',_front=front,admission=gate,config=config,host_state_db=args.host_state_db,persistent_engine=args.persistent_engine)
  def refresh_auth():
   if not original_card_matches(url,key.address):raise ValueError('original main URL or wallet changed')
   latest=protected(root/'.kit/worker-token',2048).decode().strip()
   if not 16<=len(latest)<=1024:raise ValueError('private authentication unavailable')
   ctx['tokens']['shop']=latest
  app.before_new=refresh_auth
  if 'MARKETING-BINDING.json' in json.loads(own)['files']:
   bridge=load('verified_seller_marketing_handoff',folder/'seller_marketing_host.py')
   app=bridge.configured_app(app,op,bundle,folder,json.loads(own),refresh_auth)
  import uvicorn
  uvicorn.run(app,host='127.0.0.1',port=config.new_port,log_level='warning',access_log=False,timeout_keep_alive=5)
 finally:signer.http.shutdown();signer.http.server_close()
if __name__=='__main__':main()
