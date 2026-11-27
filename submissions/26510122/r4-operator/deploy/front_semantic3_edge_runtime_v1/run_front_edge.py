"""Listener-only assembly; serve requires explicit opt-in. Never joins or starts a Mind loop."""
import argparse,importlib.util,json,os,stat,sys,time
from pathlib import Path
from hashlib import sha256,sha1
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parent))

OPERATOR=Path('/home/seop/.local/share/ourolabs-r4-checkout/submissions/26510122/r4-operator')
MARKET='https://market.ourolabs.ai';NAME='outseop-r4'
SHARED={'dispatcher.py':'84e0eca3a0211e80772ed78f2ba3c166902ba0125577e7153b06cc5bb13de0cd','worker_bootstrap.py':'083e127a2e08aa17949aaa808e61b859cee988389afc2073a6aa1b39de612514','refund_admin.py':'d1d5026ceef7f5f9b2e63a81c3c56f459cd708e1d0fd75c560171614520ce80d'}
def protected(path,maximum=4*1024*1024):
 path=Path(path);item=path.lstat()
 if path.resolve(strict=True)!=path or not stat.S_ISREG(item.st_mode) or item.st_uid!=os.getuid() or item.st_nlink!=1 or item.st_mode&0o022 or item.st_size>maximum:raise ValueError('unprotected edge input')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 with os.fdopen(fd,'rb') as stream:return stream.read(maximum+1)
def verify(op,bundle,pin):
 if op!=OPERATOR:raise ValueError('unexpected registered operator')
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

def assemble(official,op,bundle,pin,ctx,model,*,trace=None,old_request=None,options_override=None,toolbox_factory=None,_front=None):
 if _front is None:raise ValueError('reviewed edge module required before app assembly')
 meta=verify(op,bundle,pin);root=op.parent/'round-4';sys.path[:0]=[str(bundle),str(root/'codex-r4'),str(op/'kit')]
 broker=load('broker_public_catalogue_host_candidate',bundle/'broker_public_catalogue_host_candidate.py');managed=load('edge_managed_public_catalogue',bundle/'managed_runtime_public_catalogue_host_candidate.py');
 class EdgeBudgetBroker(broker.Broker):
  def __init__(self,*args,**kwargs):
   kwargs.update(seconds=40,model_seconds=30,max_steps=1)
   super().__init__(*args,**kwargs)
 managed.Broker=EdgeBudgetBroker
 if options_override is None:
  composition=load('edge_catalogue_composition',bundle/'public_catalogue_composition_candidate.py');toolpins={Path(n).name:v for n,v in meta['file_sha256'].items() if n.startswith('catalogue/')};options=composition.managed_options(op,bundle,official,toolpins)
 else:options=options_override
 box_class,mind_class,app_factory=managed.managed_classes(official,enable_stock=False,**options)
 box=box_class(root,ctx) if toolbox_factory is None else toolbox_factory(box_class,root,ctx)
 agent=json.loads(protected(root/'agent.json'));agent['llm']={'base':'market'}
 mind=mind_class(root,agent,_front.OneDecisionModel(model),box,ctx,['shop'])
 app,store=_front.capture_sdk_app(app_factory,root,NAME,mind,box,[ctx['shop_url']])
 edge=_front.FrontEdge(app,store,trace=trace,old_request=old_request);edge.signer=ctx.get('signer');edge.background_loops_started=0;return edge

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--operator',type=Path,required=True);p.add_argument('--runtime-bundle',type=Path,required=True);p.add_argument('--runtime-manifest-sha',required=True);p.add_argument('--edge-manifest-sha',required=True);p.add_argument('--port',type=int,default=18808);p.add_argument('--serve',action='store_true');args=p.parse_args();os.umask(0o077)
 front=reviewed_front(args.edge_manifest_sha);op=args.operator.resolve(strict=True);bundle=args.runtime_bundle.resolve(strict=True);verify(op,bundle,args.runtime_manifest_sha);url,address=current_identity(op)
 if not args.serve:print(json.dumps({'status':'verified_only','SDK7':True,'original_financial_sources_same':True,'registered_old_URL_wallet_matches':True,'Signer_created':False,'Model_called':False,'joined':False,'listener_started':False}));return
 if args.port!=18808:p.error('reviewed edge listener is127.0.0.1:18808')
 sys.path[:0]=[str(op/'kit'),str(op.parent/'round-4/codex-r4')];import agent_kit as official
 for name in ('AGENT_LLM_BASE','AGENT_LLM_MODEL','AGENT_LLM_KEY'):os.environ.pop(name,None)
 root=op.parent/'round-4';token=protected(root/'.kit/worker-token',2048).decode().strip()
 if not 16<=len(token)<=1024:raise ValueError('invalid private inference/tool auth')
 # Wallet.from_hex is read-only; Wallet.load would chmod or create a key.
 key=official.maroo.Wallet.from_hex(protected(root/'shop_wallet.key',2048).decode());signer=official.Signer({'shop':key},root)
 state=op/'runtime/front-semantic3-edge';state.mkdir(mode=0o700,exist_ok=True)
 if state.resolve()!=state or state.stat().st_uid!=os.getuid() or state.stat().st_mode&0o077:raise ValueError('unprotected edge state')
 official.mk.LOG_FILE=state/'agent-kit-private.log'
 ctx={'market':MARKET,'name':NAME,'shop_url':url,'tokens':{'shop':token},'addresses':{'shop':key.address},'signer':signer}
 model=official.Model({'llm':{'base':'market'}},MARKET,{'tokens':ctx['tokens']})
 try:
  app=assemble(official,op,bundle,args.runtime_manifest_sha,ctx,model,trace=state/'edge-trace-private.jsonl',_front=front)
  def refresh_auth():
   if not original_card_matches(url,key.address):raise ValueError('original main URL or wallet changed')
   latest=protected(root/'.kit/worker-token',2048).decode().strip()
   if not 16<=len(latest)<=1024:raise ValueError('private authentication unavailable')
   ctx['tokens']['shop']=latest
  app.before_new=refresh_auth
  import uvicorn
  uvicorn.run(app,host='127.0.0.1',port=args.port,log_level='warning',access_log=False,timeout_keep_alive=5)
 finally:signer.http.shutdown();signer.http.server_close()
if __name__=='__main__':main()
