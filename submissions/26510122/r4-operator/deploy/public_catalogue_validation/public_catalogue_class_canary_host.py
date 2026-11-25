"""Host-only single-catalogue SDK ASGI canary. Prepare only by default; root calls Model."""
import argparse
from contextlib import redirect_stdout,redirect_stderr
from copy import deepcopy
from hashlib import sha256,sha1
import importlib.util
import json,os,stat,sys,time
from pathlib import Path
from uuid import uuid4

QUESTION='식품 재고 가격 등급 유통기한'
GUEST={'outcome':'context','inventory':[],'verified_account':False,'redeemable_mileage':0,'preferences':[],
       'wait':None,'wait_discount':0,'prior_offer':None,'transfer_reference_present':False}


def encode(value):return (json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode()
def digest(raw):return sha256(raw).hexdigest()
def fixed(path,raw):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with path.open('xb') as stream:stream.write(raw)
    path.chmod(0o400)
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);obj=importlib.util.module_from_spec(spec)
    sys.modules[name]=obj;spec.loader.exec_module(obj);return obj


def verify_bundle(source,pin):
    if source.is_symlink():raise ValueError('runtime bundle symlink')
    source=source.resolve(strict=True);raw=(source/'MANIFEST.json').read_bytes()
    if digest(raw)!=pin:raise ValueError('unreviewed runtime manifest')
    manifest=json.loads(raw)
    if manifest.get('builder_dependency') is not False:raise ValueError('old builder dependency forbidden')
    files={}
    for name,expected in manifest['file_sha256'].items():
        rel=Path(name);path=source/rel
        if rel.is_absolute() or '..' in rel.parts or path.resolve()!=path or path.is_symlink():raise ValueError('unsafe package path')
        data=path.read_bytes()
        if digest(data)!=expected:raise ValueError('runtime source changed')
        if 'builder' in rel.parts:raise ValueError('old builder source forbidden')
        files[name]=data
    required={'catalogue/'+n for n in ('logic.py','permission.yml','test.py','forge.json')}
    if not required<=set(files):raise ValueError('single genuine catalogue source missing')
    record=json.loads(files['catalogue/forge.json'])
    pins={n:digest(files['catalogue/'+n]) for n in ('logic.py','permission.yml','test.py','forge.json')}
    if record.get('tool')!='public_catalogue' or record.get('sha256')!={n:d for n,d in pins.items() if n!='forge.json'}:raise ValueError('genuine source manifest conflict')
    return source,manifest,files,pins,raw


def public_fixture(snapshot,normalizer):
    rows=[]
    for row in snapshot['units'][:30]:
        price=row['price_credits'];state=row['state']
        rows.append({'sku':row['sku'],'name':normalizer(row['name']),'grade':row['grade'],'category':None,
          'reference_price':price,'min_base':price,'preferred_price':price,'stock_status':state,
          'available':state=='available','wait_eligible':False})
    return {**deepcopy(GUEST),'inventory':rows}


def prepare(op,session,source,bundle,bundle_pin):
    bundle,manifest,files,pins,manifest_raw=verify_bundle(bundle,bundle_pin)
    if source.is_symlink() or stat.S_IMODE(source.lstat().st_mode)!=0o400:raise ValueError('owned0400 source required')
    loader=module('catalogue_input_preflight',bundle/'public_catalogue_snapshot_host.py')
    raw,snapshot=loader.read_snapshot(source.resolve(strict=True))
    sys.path.insert(0,str(op.parent/'round-4/codex-r4'));import dispatcher
    if Path(dispatcher.__file__).resolve()!=(op.parent/'round-4/codex-r4/dispatcher.py').resolve():raise ValueError('unexpected existing name normalizer')
    base=public_fixture(snapshot,dispatcher.public_product_name)
    sdk={}
    for entry in json.loads((op/'sources/upstream.json').read_bytes())['files']:
        data=(op/'kit'/entry['name']).read_bytes()
        if sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()!=entry['upstream_git_blob_sha']:raise ValueError('official SDK changed')
        sdk[entry['name']]=digest(data)
    if len(sdk)!=7:raise ValueError('expected seven original SDK files')
    session.mkdir(mode=0o700)
    for n in ('logs','.kit','scratch','runtime','tools','host_inputs'):(session/n).mkdir(mode=0o700)
    fixed(session/'host_inputs/customer_offer_context.json',raw)
    fixed(session/'host_inputs/broker_context_base.json',encode(base))
    for name,data in files.items():fixed(session/'runtime'/name,data)
    fixed(session/'runtime/MANIFEST.json',manifest_raw)
    boundary={}
    for name in ('a2a_info','shop_info'):
        origin=op.parent/'round-4/tools'/name;parts={n:(origin/n).read_bytes() for n in ('logic.py','permission.yml','test.py','forge.json')};record=json.loads(parts['forge.json'])
        if record['sha256']!={n:digest(d) for n,d in parts.items() if n!='forge.json'}:raise ValueError('boundary forge conflict')
        for n,data in parts.items():fixed(session/'tools'/name/n,data)
        boundary[name]={n:digest(d) for n,d in parts.items()}
    fixed(session/'driver-source.py',Path(__file__).read_bytes())
    metadata={'schema':'single-public-catalogue-canary.v1','runtime_manifest_sha256':bundle_pin,'genuine_exact4':pins,
      'genuine_version':json.loads(files['catalogue/forge.json'])['version'],'source_snapshot_sha256':digest(raw),
      'source_unit_count':len(snapshot['units']),'source_bytes':len(raw),'legacy_fixture_rows':len(base['inventory']),
      'source_timestamps_not_rebased':True,'native_source_truncated':False,'old_builder_dependency':False,
      'fixture':'synthetic guest first30 public legacy rows; categoryNone/public name normalizer/publicprice floors; false/null rights',
      'runtime_source_hashes':manifest['file_sha256'],'boundary_original_hashes':boundary,'official_SDK7':sdk,
      'driver_source_sha256':digest(Path(__file__).read_bytes()),'Model_called':False,'wallet_loaded':False,'actual_DB_opened':False}
    fixed(session/'PREPARED.json',encode(metadata));return raw,snapshot


def pages_in(value):
    pages=[]
    if isinstance(value,dict):
        if 'public_catalogue' in value and isinstance(value['public_catalogue'],dict):pages.append(value['public_catalogue'])
        for key,item in value.items():
            if key!='public_catalogue':pages+=pages_in(item)
    elif isinstance(value,list):
        for item in value:pages+=pages_in(item)
    return pages


def run_asgi(op,session,raw,snapshot,model,question=QUESTION,legacy_fixture=None):
    runtime=session/'runtime';sys.path[:0]=[str(runtime),str(op.parent/'round-4/codex-r4'),str(op/'kit')]
    import agent_kit as official
    broker=module('broker',runtime/'broker_public_catalogue_host_candidate.py')
    sys.modules['broker_public_catalogue_host_candidate']=broker
    managed=module('catalogue_canary_managed',runtime/'managed_runtime_public_catalogue_host_candidate.py')
    worker=module('catalogue_canary_worker',runtime/'bounded_public_catalogue_host.py')
    protocol_mod=module('catalogue_canary_protocol',runtime/'public_catalogue_protocol.py')
    request_mod=module('catalogue_canary_request',runtime/'public_catalogue_request_host.py')
    composition=module('catalogue_canary_composition',runtime/'public_catalogue_composition_candidate.py')
    from starlette.testclient import TestClient
    prepared=json.loads((session/'PREPARED.json').read_bytes());pins=prepared['genuine_exact4']
    worker.instruction_from(runtime/'catalogue',pins,official)
    sealed=worker.BoundedPublicCatalogue(runtime/'catalogue',op/'kit',session/'scratch',pins)
    original=deepcopy(legacy_fixture) if legacy_fixture is not None else json.loads((session/'host_inputs/broker_context_base.json').read_bytes())
    original_hash=digest(encode(original));legacy_calls=[];catalogue_calls=[];Model_metrics=[];phases=[];supplier_calls=[];native_results=[];page_violations=[]
    def supply():
        supplier_calls.append(True)
        if (session/'host_inputs/customer_offer_context.json').read_bytes()!=raw:raise ValueError('fixed source changed')
        return raw,deepcopy(snapshot)
    def invoke(**kwargs):
        if kwargs['snapshot']!=raw:raise ValueError('request snapshot changed')
        begin=time.monotonic();result=sealed(**kwargs);native_results.append((kwargs['args']['op'],result))
        page=result if isinstance(result,dict) and 'catalogue' in result else None
        catalogue_calls.append({'op':kwargs['args']['op'],'seconds':round(time.monotonic()-begin,4),
          'snapshot_sha256':digest(kwargs['snapshot']),'status':result.get('status'),'fixed_reason':result.get('reason'),
          'page_rows':len(page['rows']) if page is not None else None,
          'page_characters':len(json.dumps(page,ensure_ascii=False,separators=(',',':'))) if page is not None else None,
          'source_count':page['catalogue']['source_count'] if page is not None else None,
          'offset':page['catalogue']['offset'] if page is not None else None,
          'args_sha256':digest(encode(kwargs['args']))})
        return result
    def factory(_execute):return request_mod.ScopedPublicCatalogue(supply,invoke,protocol_mod.CatalogueProtocol(broker.mask),composition.SEARCH_INSTRUCTION)
    box_class,mind_class,app_factory=managed.managed_classes(official,catalogue_source_factory=factory,public_phase_report=phases.append)
    class NoWallet:
        def grant(self,name,permission,timeout):raise PermissionError('no original financial/network tool execution in canary')
    class FixtureToolbox(box_class):
        def decision_tool(self,details):
            legacy_calls.append(deepcopy(details))
            if details.get('action')!='context':raise PermissionError('financial executor forbidden in canary')
            return deepcopy(original)
    ctx={'name':'outseop-r4','market':'https://market.ourolabs.ai','tokens':{},'addresses':{},'signer':NoWallet()}
    official.mk.LOG_FILE=session/'logs/agent-kit-private.log';box=FixtureToolbox(session,ctx);box.validate()
    class ModelInstrument:
        def complete(self,messages,**kwargs):
            current=[]
            for message in messages:
                if message['role']=='system':continue
                try:document=json.loads(message['content'])
                except (ValueError,TypeError):continue
                current+=pages_in(document)
            ready=[p for p in current if p.get('status')=='ready']
            sizes=[len(json.dumps(p,ensure_ascii=False,separators=(',',':'))) for p in ready]
            rows=[len(p['rows']) for p in ready]
            if any(n>8 for n in rows) or any(n>5500 for n in sizes):
                page_violations.append(True);raise AssertionError('Model page bound violated')
            Model_metrics.append({'prompt_characters':sum(len(m['content']) for m in messages),'page_count_in_history':len(ready),
              'page_rows_in_history':rows,'page_characters_in_history':sizes,'timeout':kwargs.get('timeout'),'max_tokens':kwargs.get('max_tokens')})
            return model.complete(messages,**kwargs)
    mind=mind_class(session,{'llm':{'base':'market'},'max_steps':3},ModelInstrument(),box,ctx,[])
    app=app_factory(session,'outseop-r4',mind,box,['https://synthetic-local-only.invalid'])
    payload={'jsonrpc':'2.0','id':1,'method':'SendMessage','params':{'message':{'messageId':uuid4().hex,'role':'ROLE_USER','parts':[{'text':question}],'metadata':{'from':'synthetic-local-guest'}}}}
    begin=time.monotonic()
    with TestClient(app,base_url='https://synthetic-local-only.invalid') as client:response=client.post('/',headers={'A2A-Version':'1.0'},json=payload)
    elapsed=time.monotonic()-begin;body=response.json();result=body.get('result',{});task=result.get('task',result);reply=task.get('status',{}).get('message',{}).get('parts',[{}])[0].get('text')
    verified=[(op,r) for op,r in native_results if op in ('render','fallback') and isinstance(r,dict) and r.get('status')=='rendered']
    exact=bool(verified and verified[-1][1]['reply']==reply);financial=sum(x.get('action')!='context' for x in legacy_calls)
    safe={'status':'verified_catalogue_final_reply' if response.status_code==200 and exact and not financial and not page_violations else 'no_verified_catalogue_final_reply',
      'http_status':response.status_code,'final_reply_matches_genuine':exact,'final_reply_sha256':digest(reply.encode()) if isinstance(reply,str) else None,
      'final_reply_characters':len(reply) if isinstance(reply,str) else 0,'final_genuine_operation':verified[-1][0] if exact else None,
      'source_count':len(snapshot['units']),'source_bytes':len(raw),'source_snapshot_sha256':digest(raw),
      'catalogue_calls':catalogue_calls,'supplier_calls':len(supplier_calls),'legacy_context_calls':sum(x.get('action')=='context' for x in legacy_calls),
      'financial_executor_attempts':financial,'legacy_fixture_unchanged':digest(encode(original))==original_hash,
      'Model_page_bound_violations':len(page_violations),'Model_metrics':Model_metrics,'phase_metrics':phases,'total_transport_seconds':round(elapsed,4),
      'old_builder_invocations':0,'old_builder_source_present':any('builder' in p.parts for p in runtime.rglob('*')),
      'tool_tokens_count':0,'tool_addresses_count':0,'wallet_loaded':False,'actual_customers_contacted':False,
      'actual_DB_opened':False,'server_listener_started':False,'production_installed':False,'raw_reason_reply_exported':False}
    fixed(session/'logs/asgi-response-private.json',encode(body));fixed(session/'logs/catalogue-results-private.json',encode(native_results));fixed(session/'safe-result.json',encode(safe));return safe


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--operator',type=Path,required=True);p.add_argument('--session',type=Path,required=True)
    p.add_argument('--public-snapshot',type=Path,required=True);p.add_argument('--runtime-bundle',type=Path,required=True);p.add_argument('--runtime-manifest-sha',required=True)
    p.add_argument('--run-class',action='store_true');p.add_argument('--inference-token-file',type=Path);p.add_argument('--question-file',type=Path)
    a=p.parse_args(argv);op=a.operator.resolve(strict=True);session=a.session.resolve()
    if session.parent!=(op/'runtime').resolve() or not session.name.startswith('public-catalogue-class-canary-') or session.exists():p.error('fresh isolated catalogue canary session required')
    if a.run_class and a.inference_token_file is None:p.error('explicit existing inference auth required')
    os.umask(0o077);raw,snapshot=prepare(op,session,a.public_snapshot,a.runtime_bundle,a.runtime_manifest_sha)
    result={'status':'prepared','actual_class_called':False,'source_count':len(snapshot['units']),'old_builder_invocations':0}
    if a.run_class:
        if a.inference_token_file.is_symlink():raise ValueError('credential symlink')
        info=a.inference_token_file.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o600 or info.st_nlink!=1:raise ValueError('unsafe inference auth')
        token=a.inference_token_file.read_text().strip()
        if not 16<=len(token)<=1024:raise ValueError('invalid inference auth')
        question=a.question_file.read_text().strip() if a.question_file else QUESTION
        if not 0<len(question)<=1500:raise ValueError('synthetic question too long')
        for key in ('AGENT_LLM_BASE','AGENT_LLM_MODEL','AGENT_LLM_KEY'):os.environ.pop(key,None)
        sys.path.insert(0,str(op/'kit'));import agent_kit as official
        official.mk.LOG_FILE=session/'logs/agent-kit-private.log';model=official.Model({'llm':{'base':'market'}},'https://market.ourolabs.ai',{'tokens':{'shop':token}})
        with (session/'logs/console-private.log').open('x') as log,redirect_stdout(log),redirect_stderr(log):result=run_asgi(op,session,raw,snapshot,model,question)
        result['actual_class_called']=True;fixed(session/'ROOT-RUN-SUMMARY.json',encode(result))
    print(json.dumps(result,ensure_ascii=False));return result

if __name__=='__main__':main()
