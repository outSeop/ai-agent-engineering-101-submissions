"""Host-only dual-genuine catalogue SDK ASGI canary. Prepare only by default; root calls Model."""
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
    pinsets={}
    for folder,tool in (('catalogue','public_catalogue'),('semantic','semantic_candidates')):
        required={folder+'/'+n for n in ('logic.py','permission.yml','test.py','forge.json')}
        if not required<=set(files):raise ValueError('dual genuine source missing')
        record=json.loads(files[folder+'/forge.json'])
        current={n:digest(files[folder+'/'+n]) for n in ('logic.py','permission.yml','test.py','forge.json')}
        if record.get('tool')!=tool or record.get('sha256')!={n:d for n,d in current.items() if n!='forge.json'}:raise ValueError('dual genuine source manifest conflict')
        pinsets[folder]=current
    pins=pinsets['catalogue']
    expected8={'logic.py':'01a4a0dc912e02679091a3f6c98df3f0450ca2581b920d1d650e2fa0fa2a4c89','test.py':'1da5431683f6515799dbb769660187d467f4ac9a0a1a1bd280bfdca683a19e5a','permission.yml':'f69e6c375d5586dea1bb8ff701f977a07d475e9d88033e5dce4acf123ababcc4','forge.json':'5e19ba19f264b231d12e1570188f189cc5b7f770e2cbea810b343fc2b364f6bb'}
    if pins!=expected8:raise ValueError('exact original catalogue8 dependency required')
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
    metadata={'schema':'dual-genuine-public-catalogue-canary.v1','runtime_manifest_sha256':bundle_pin,'genuine_exact4':pins,
      'genuine_version':json.loads(files['catalogue/forge.json'])['version'],'genuine_semantic_exact4':{n:digest(files['semantic/'+n]) for n in ('logic.py','permission.yml','test.py','forge.json')},'genuine_semantic_version':json.loads(files['semantic/forge.json'])['version'],'source_snapshot_sha256':digest(raw),
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


def run_asgi(op,session,raw,snapshot,model,question=QUESTION,legacy_fixture=None,scenario="followup"):
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
    semantic_pins=prepared['genuine_semantic_exact4']
    worker.instruction_from(runtime/'semantic',semantic_pins,official,tool_name='semantic_candidates')
    sealed=worker.BoundedPublicCatalogue(runtime/'catalogue',op/'kit',session/'scratch',pins,semantic_source=runtime/'semantic',semantic_pins=semantic_pins)
    original=deepcopy(legacy_fixture) if legacy_fixture is not None else json.loads((session/'host_inputs/broker_context_base.json').read_bytes())
    original_hash=digest(encode(original));legacy_calls=[];catalogue_calls=[];Model_metrics=[];phases=[];supplier_calls=[];native_results=[];page_violations=[];raw_history_marker_seen=[]
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
    def stock_state_fixture(raw,document):
        return [{'sku':row['sku'],'grade':row['grade'],'stock_status':row['state'],'expires_at':row['expires_at'],'preferred_price':row['price_credits']} for row in document['units']]
    def factory(_execute):return request_mod.ScopedPublicCatalogue(supply,invoke,protocol_mod.CatalogueProtocol(broker.mask),composition.SEARCH_INSTRUCTION,stock_state_supplier=stock_state_fixture)
    class NoWallet:
        def grant(self,name,permission,timeout):raise PermissionError('No financial or network signer capability in canary')
    def fixture_toolbox(base,registered_root,ctx):
        class FixtureToolbox(base):
            def decision_tool(self,details):
                legacy_calls.append(deepcopy(details))
                if details.get('action')!='context':
                    if scenario=='checkout' and details.get('action')=='quote_and_send':
                        return {'outcome':'canary_quote_selected','reply':'합성 점검에서 견적 선택만 기록했습니다. 실제 결제권 발급과 송금은 수행하지 않았습니다.'}
                    raise PermissionError('financial executor forbidden in canary')
                return deepcopy(original)
        # Critical: all metrics/decision trace writes stay in the isolated canary root.
        return FixtureToolbox(session,ctx)
    ctx={'name':'outseop-r4','market':'https://market.ourolabs.ai','shop_url':'https://synthetic-local-only.invalid','tokens':{},'addresses':{},'signer':NoWallet()}
    fixed(session/'agent.json',encode({'llm':{'base':'market'},'goal':'isolated no-wallet canary'}))
    official.mk.LOG_FILE=session/'logs/agent-kit-private.log'
    class ModelInstrument:
        def complete(self,messages,**kwargs):
            flow=[]
            for message in messages:
                if message.get('role')=='user':
                    try:parsed_flow=json.loads(message['content'])
                    except (ValueError,TypeError):continue
                    if isinstance(parsed_flow,dict) and 'host_readonly_flow' in parsed_flow:flow.append(parsed_flow['host_readonly_flow'])
            current=[]
            raw_history_marker_seen.append(any('SYNTHETIC_DO_NOT_FORWARD_RAW_HISTORY' in message.get('content','') for message in messages))
            try:remembered=json.loads(messages[1]['content']).get('verified_context',{}).get('remembered_public_products_unverified',[])
            except (ValueError,TypeError,KeyError):remembered=[]
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
            Model_metrics.append({'host_readonly_flow':flow,'remembered_public_count':len(remembered),'remembered_public_skus':[x.get('sku') for x in remembered], 'prompt_characters':sum(len(m['content']) for m in messages),'page_count_in_history':len(ready),
              'page_rows_in_history':rows,'page_characters_in_history':sizes,'timeout':kwargs.get('timeout'),'max_tokens':kwargs.get('max_tokens')})
            try:
                return model.complete(messages,**kwargs)
            except Exception as error:
                kind=type(error).__name__
                metadata={'error_type':kind if len(kind)<=80 and kind.isascii() and kind.replace('_','').isalnum() else 'ModelError'}
                status=getattr(getattr(error,'response',None),'status_code',None)
                if type(status) is not int:status=getattr(error,'code',None)
                if type(status) is not int:
                    match=__import__('re').match(r'^HTTP ([1-5][0-9]{2}):',str(error)[:16])
                    if match:status=int(match[1])
                if type(status) is int and 100<=status<=599:metadata['http_status']=status
                Model_metrics[-1]['model_error']=metadata
                fixed(session/'logs'/('model-error-'+str(len(Model_metrics))+'-private.json'),encode(metadata))
                raise

    edge_release=op/'deploy/front_semantic3_edge_runtime_v1'
    edge_host=module('exact_front_edge_runner',edge_release/'run_front_edge.py')
    front=edge_host.reviewed_front('25d099830f88215ffebc37c41fd9cef8c3a28d0206f411ab9488c646a62980d9')
    async def old_backend_stub(scope,body):
        return 503,[(b'content-type',b'application/json')],b'{"error":"old backend forbidden in isolated canary"}'
    app=edge_host.assemble(official,op,runtime,prepared['runtime_manifest_sha256'],ctx,ModelInstrument(),
        trace=session/'logs/front-route-private.jsonl',old_request=old_backend_stub,
        options_override={'catalogue_source_factory':factory,'public_phase_report':phases.append},
        toolbox_factory=fixture_toolbox,_front=front)
    def unpack(response):
        body=response.json();result=body.get('result',{});task=result.get('task',result)
        reply=task.get('status',{}).get('message',{}).get('parts',[{}])[0].get('text')
        return body,task,reply
    def send(client,text,*,task=None,context=None,marker=False,claim='synthetic-local-guest'):
        message={'messageId':uuid4().hex,'role':'ROLE_USER','parts':[{'text':text}],'metadata':{'from':claim}}
        if task:message['taskId']=task
        if context:message['contextId']=context
        if marker:message['parts'].append({'data':{'history_marker':'SYNTHETIC_DO_NOT_FORWARD_RAW_HISTORY'}})
        payload={'jsonrpc':'2.0','id':uuid4().hex,'method':'SendMessage','params':{'message':message}}
        native_before=len(native_results);legacy_before=len(legacy_calls);model_before=len(Model_metrics)
        response=client.post('/',headers={'A2A-Version':'1.0'},json=payload)
        body,taskobj,reply=unpack(response)
        turn_native=native_results[native_before:];turn_legacy=legacy_calls[legacy_before:]
        turn_verified=[r for op,r in turn_native if op in ('render','fallback','prepared_fallback','semantic_candidates') and isinstance(r,dict) and r.get('status')=='rendered']
        turn_exact=bool(turn_verified and turn_verified[-1].get('reply')==reply)
        transport_turns.append({'genuine_final_reply_match':turn_exact,'genuine_reply_exact_suffix':bool(turn_verified and isinstance(reply,str) and reply.endswith(turn_verified[-1].get('reply',''))),'model_memory_counts':[x.get('remembered_public_count') for x in Model_metrics[model_before:]],'legacy_action_selections':[x.get('action') for x in turn_legacy if x.get('action')!='context'],'task_state':taskobj.get('status',{}).get('state'),'http_status':response.status_code,'has_error':'error' in body,'task':taskobj.get('id'),'context':taskobj.get('contextId') or taskobj.get('context_id'),'reply':reply,'body':body})
        return response,body,taskobj,reply
    transport_turns=[];begin=time.monotonic()
    with TestClient(app,base_url='https://synthetic-local-only.invalid') as client:
        response,body,task,reply=send(client,question,marker=scenario=='followup')
        first_task=task.get('id');first_context=task.get('contextId') or task.get('context_id')
        if scenario=='followup' and first_task:
            response,body,task,reply=send(client,'그 상품 남은 소비기한을 다시 알려 주세요.',task=first_task,claim='different-unverified-claim')
            # Same public context but a NEW task must not inherit task-scoped hints.
            response,body,task,reply=send(client,'그 상품 남은 소비기한을 다시 알려 주세요.',context=first_context,claim='synthetic-local-guest')
    elapsed=time.monotonic()-begin
    verified=[(op,r) for op,r in native_results if op in ('render','fallback','prepared_fallback','semantic_candidates') and isinstance(r,dict) and r.get('status')=='rendered']
    exact=bool(verified and verified[-1][1]['reply']==reply);financial=sum(x.get('action')!='context' for x in legacy_calls)
    safe={'status':'verified_catalogue_final_reply' if response.status_code==200 and exact and not financial and not page_violations else 'no_verified_catalogue_final_reply',
      'http_status':response.status_code,'final_reply_matches_genuine':exact,'final_reply_sha256':digest(reply.encode()) if isinstance(reply,str) else None,
      'final_reply_characters':len(reply) if isinstance(reply,str) else 0,'final_genuine_operation':verified[-1][0] if exact else None,
      'source_count':len(snapshot['units']),'source_bytes':len(raw),'source_snapshot_sha256':digest(raw),
      'catalogue_calls':catalogue_calls,'supplier_calls':len(supplier_calls),'legacy_context_calls':sum(x.get('action')=='context' for x in legacy_calls),
      'financial_executor_attempts':financial,'actual_financial_execution_count':0,'financial_executor_is_stub':True,'scenario':scenario,'raw_history_marker_forwarded':any(raw_history_marker_seen),'transport_turn_count':len(transport_turns),'per_turn_safe':[dict(index=i,http_status=x['http_status'],has_error=x['has_error'],task_state=x['task_state'],genuine_final_reply_match=x['genuine_final_reply_match'],genuine_reply_exact_suffix=x['genuine_reply_exact_suffix'],model_memory_counts=x['model_memory_counts'],legacy_action_selections=x['legacy_action_selections']) for i,x in enumerate(transport_turns)],'same_task_continuation_accepted':len(transport_turns)>1 and not transport_turns[1]['has_error'] and transport_turns[1]['task']==transport_turns[0]['task'],'cross_task_id_is_different':len(transport_turns)>2 and transport_turns[2]['task']!=transport_turns[0]['task'],'legacy_fixture_unchanged':digest(encode(original))==original_hash,
      'Model_page_bound_violations':len(page_violations),'model_error_metadata':[x['model_error'] for x in Model_metrics if 'model_error' in x],'Model_metrics':Model_metrics,'phase_metrics':phases,'total_transport_seconds':round(elapsed,4),
      'old_builder_invocations':0,'old_builder_source_present':any('builder' in p.parts for p in runtime.rglob('*')),
      'dual_genuine_sources_verified':True,'semantic_execution_uses_actual_dual_worker':True,'semantic_native_call_count':sum(op=='semantic_candidates' for op,result in native_results),'actual_frozen_front_wrapper':True,'front_edge_manifest_sha256':'25d099830f88215ffebc37c41fd9cef8c3a28d0206f411ab9488c646a62980d9','toolbox_root_isolated_session':True,'production_trace_writes_expected':0,'prepared_mode_enabled':True,'strict_Model_decision_limit':1,'calibrated_local_Model_wait_seconds':30,'calibrated_request_budget_seconds':40,'calibration_max_tokens':800,'stock_state_source':'controlled public snapshot metadata fixture, not production reservation join','tool_tokens_count':0,'tool_addresses_count':0,'wallet_loaded':False,'actual_customers_contacted':False,
      'actual_DB_opened':False,'server_listener_started':False,'production_installed':False,'raw_reason_reply_exported':False}
    if scenario=='checkout':
        quote_calls=[x for x in legacy_calls if x.get('action')=='quote_and_send']
        expected=set(__import__('re').findall(r'G[0-9a-f]{8}',question))
        safe.update(status='verified_quote_action_stub' if len(quote_calls)==1 and len(expected)==1 and quote_calls[0].get('sku') in expected else 'no_verified_quote_action_stub',quote_action_count=len(quote_calls),quote_target_matches_current_request=len(quote_calls)==1 and quote_calls[0].get('sku') in expected,signed_checkout_issued=False)
    fixed(session/'logs/asgi-response-private.json',encode(body));fixed(session/'logs/all-transport-turns-private.json',encode(transport_turns));fixed(session/'logs/catalogue-results-private.json',encode(native_results));fixed(session/'safe-result.json',encode(safe));return safe


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--operator',type=Path,required=True);p.add_argument('--session',type=Path,required=True)
    p.add_argument('--public-snapshot',type=Path,required=True);p.add_argument('--runtime-bundle',type=Path,required=True);p.add_argument('--runtime-manifest-sha',required=True)
    p.add_argument('--scenario',choices=('alternatives','checkout'),default='alternatives');p.add_argument('--run-class',action='store_true');p.add_argument('--inference-token-file',type=Path);p.add_argument('--question-file',type=Path)
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
        first=next(row for row in snapshot['units'] if row.get('state')=='available')
        if a.question_file:question=a.question_file.read_text().strip()
        elif a.scenario=='followup':question=f"{first['sku']} 상품 이름, 가격, 등급, 남은 소비기한을 알려 주세요."
        elif a.scenario=='alternatives':
            missing=next(f'G{i:08x}' for i in range(0xffffffff,0xffffff00,-1) if f'G{i:08x}' not in {r['sku'] for r in snapshot['units']})
            question=f'{missing} 파스타 있나요? 없다면 지금 실제로 파는 같은 종류의 대안 상품을 확인해 알려 주세요.'
        else:question=f"{first['sku']} 상품가 {first['price_credits']} 크레딧 이내면 서명된 결제권을 보내 주세요. 실제 송금은 하지 마세요."
        if not 0<len(question)<=1500:raise ValueError('synthetic question too long')
        for key in ('AGENT_LLM_BASE','AGENT_LLM_MODEL','AGENT_LLM_KEY'):os.environ.pop(key,None)
        sys.path.insert(0,str(op/'kit'));import agent_kit as official
        official.mk.LOG_FILE=session/'logs/agent-kit-private.log';model=official.Model({'llm':{'base':'market'}},'https://market.ourolabs.ai',{'tokens':{'shop':token}})
        with (session/'logs/console-private.log').open('x') as log,redirect_stdout(log),redirect_stderr(log):result=run_asgi(op,session,raw,snapshot,model,question,scenario=a.scenario)
        result['actual_class_called']=True;fixed(session/'ROOT-RUN-SUMMARY.json',encode(result))
    print(json.dumps(result,ensure_ascii=False));return result

if __name__=='__main__':main()
