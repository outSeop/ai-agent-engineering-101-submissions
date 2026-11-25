"""Private host-only native customer-context canary; default prepare only.
No checkout/server/real customer. Native business source is copied byte for byte.
"""
import argparse
from contextlib import redirect_stderr, redirect_stdout
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys

HERE=Path(__file__).resolve().parent
WORK=HERE.parent/'codex-r4'
sys.path.insert(0,str(WORK))
from customer_offer_mind_canary import make_context
from card_offer_producer_host import acquire
from card_source_read_lane import PATTERN
from forum_official_mind_canary import NoWallet

TOOL='build_customer_context'
SCOPE=('G69567cbf','G9cdcfa8f','G56b67513')
QUESTION='공개 카드의 SKU G69567cbf, G9cdcfa8f, G56b67513 각각의 현재 등급, 상품가, 남은 유통시간을 알려 주세요. 이 세 SKU만 문의하며 구매·결제·계약에는 동의하지 않습니다.'
PINS={
 'permission.yml':'80e35a7ea33fe6213cd654fca245305acd6fe8a254b1bb0fec5e569733b5daf0',
 'logic.py':'095dc600fe30958759a058b093ee1c210fb9b3f1f7c3157dcd034061e70dcf84',
 'test.py':'5fe2120e534a28ec360e7c4fcacd332d70beca25b6f703c2afaaa0aeb875efdd',
 'forge.json':'b44e42586e1fb81558473c10ed8a8f66819bb8a99f225f9536400821f166f4bd',
}
GUEST={'outcome':'context','inventory':[],'verified_account':False,'redeemable_mileage':0,
 'preferences':[],'wait':None,'wait_discount':0,'prior_offer':None,'transfer_reference_present':False}


def load_bundle(directory):
    files={n:(directory/n).read_bytes() for n in PINS}
    if any(sha256(files[n]).hexdigest()!=v for n,v in PINS.items()):
        raise ValueError('unreviewed native bundle bytes')
    rec=json.loads(files['forge.json'])
    if (rec.get('tool'),rec.get('version'),rec.get('sha256'))!=(TOOL,4,{k:v for k,v in PINS.items() if k!='forge.json'}):
        raise ValueError('native origin mismatch')
    return files


def scoped_context(offers,catalog,observed):
    # Filtering is solely the question's explicit SKU scope. Projection is existing host code.
    return make_context([o for o in offers if o.get('sku') in SCOPE],
                        [r for r in catalog if r.get('sku') in SCOPE],observed)


def fixed_json(path,value):
    raw=json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
    if len(raw)>512*1024: raise ValueError('input exceeds native file contract')
    path.write_bytes(raw);path.chmod(0o400)
    return raw


def install_inputs(session,files,view):
    session.mkdir(mode=0o700)
    for name in ('logs','host_inputs','tools'): (session/name).mkdir(mode=0o700)
    target=session/'tools'/TOOL;target.mkdir(mode=0o700)
    for name,data in files.items():
        p=target/name;p.write_bytes(data);p.chmod(0o400)
    inputs={
      session/'host_inputs/customer_offer_context.json':fixed_json(session/'host_inputs/customer_offer_context.json',view),
      session/'host_inputs/broker_context_base.json':fixed_json(session/'host_inputs/broker_context_base.json',GUEST),
    }
    fixed_json(session/'INPUT-ORIGIN.json',{
      'schema':'native-customer-context-canary.v1','native_version':4,'exact_native_files':PINS,
      'scope':'question-explicit SKUs only; legacy representative offers, not complete stock census',
      'requested_skus':SCOPE,'base_origin':'synthetic guest fixture; not actual customer/account verification',
      'public_facts_origin':'existing read-only producer + unchanged make_context projection',
      'input_sha256':{p.name:sha256(raw).hexdigest() for p,raw in inputs.items()},
      'native_description_limit':'600 characters; fragment continuation sentence ends at next; normal details keys complete',
      'production_installed':False,'actual_customers_contacted':False,'wallet_loaded':False})
    return target,inputs


class NativeGate:
    def __init__(self,box,target,inputs):
        self.box,self.target,self.inputs=box,target,inputs
        self.tools={TOOL:box.tools[TOOL]}
        self.actions=[]
        perm=box.tools[TOOL]['perm']
        if any(perm.get(k) for k in ('wallet','identity','network','write','exec','handles')) or perm.get('pay_limit',0)!=0:
            raise ValueError('unexpected native permissions')
    def listing(self): return self.box.listing()
    def forge(self,args): return {'error':'disabled in read-only local canary'}
    def read(self,name): return {'error':'disabled; use native published tool description'}
    def call(self,name,args):
        if name!=TOOL or not isinstance(args,dict): return {'error':'invalid tool call'}
        load_bundle(self.target)
        if any(p.read_bytes()!=raw for p,raw in self.inputs.items()):
            raise ValueError('fixed input changed')
        # No host business answers, decoding, cursor fabrication or API adaptation.
        out=self.box.call(name,args)
        self.actions.append({'tool':name,'op':args.get('op'),'sdk_ok':out.get('ok') is True,
                             'native_error':isinstance(out.get('result'),dict) and 'error' in out['result']})
        return out


def dialogue(official,session,market,gate,ctx,model):
    agent={'llm':{'base':'market'},'max_steps':10,'run_minutes':3,
      'persona':'공개 사실만 읽어 안내하는 가상 문의 담당자',
      'goal':'고객은 명시한 세 SKU만 질문했다. build_customer_context를 직접 호출하고 실제 도구 description과 결과를 읽어 답한다. '
             '필요하면 명세대로 details를 호출한다. 입력은 공개 대표 재고 사실과 가상 비회원 기본값이며 실제 고객 권리 검증이 아니다. '
             '알 수 없는 값은 모른다고 답하고 유통시간을 보장하지 않는다. 매매 동의가 없으므로 거래하지 않는다. '
             '로컬 질문에 reply를 한 번 보내고 sleep한다.'}
    mind=official.Mind(session,agent,model,gate,ctx,[])
    event=official.Event('a2a','synthetic-guest-local-only',QUESTION)
    mind.pending[event.id]=event;mind.run_once([event])
    ans=event.answer
    safe=(isinstance(ans,dict) and ans.get('data') is None and isinstance(ans.get('reply'),str)
          and len(ans['reply'])<=2000 and not PATTERN.search(ans['reply'].encode())
          and not re.search(r'0x[a-fA-F0-9]{40,}',ans['reply']))
    result={'status':'local_reply_complete' if safe else 'no_safe_local_reply',
            'tool_calls':gate.actions,'native_context_called':any(a['op']=='context' and a['sdk_ok'] and not a['native_error'] for a in gate.actions)}
    if safe: result['local_public_reply']=ans['reply']
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--operator',type=Path,required=True)
    p.add_argument('--session',type=Path,required=True)
    p.add_argument('--run-class',action='store_true')
    a=p.parse_args(argv);op=a.operator.resolve(strict=True);session=a.session.resolve()
    runtime=(op/'runtime').resolve(strict=True)
    if session.parent!=runtime or not session.name.startswith('customer-native-v4-canary-') or session.exists():
        p.error('fresh isolated runtime/customer-native-v4-canary-* session required')
    files=load_bundle(runtime/'class-rebuild-customer-context-20261125/tools'/TOOL)
    sys.path.insert(0,str(op/'kit'));import agent_kit as official
    os.umask(0o077)
    # acquire is existing read-only host code. No real key or wallet signer is constructed.
    # All potentially sensitive SDK logging is private; stdout is only safe status below.
    session.mkdir(mode=0o700)
    log=session/'prepare-private.log'
    with log.open('x') as output,redirect_stdout(output),redirect_stderr(output):
        registered,observed,offers,catalog=acquire(op.parent/'round-4')
        view=scoped_context(offers,catalog,observed)
        # install_inputs requires a fresh directory, after acquire's private log exists.
        # Keep the directory and install into an empty child first, then move contents.
        scratch=session/'fixed';target,inputs=install_inputs(scratch,files,view)
        for child in tuple(scratch.iterdir()): child.rename(session/child.name)
        scratch.rmdir();target=session/'tools'/TOOL
        inputs={session/'host_inputs'/q.name:raw for q,raw in inputs.items()}
        official.mk.LOG_FILE=session/'logs/agent-kit.log'
        ctx={'name':'outseop-r4','market':registered.market,'tokens':{},'addresses':{},'signer':NoWallet()}
        box=official.Toolbox(session,ctx);gate=NativeGate(box,target,inputs)
        result={'status':'prepared','scoped_representative_rows':len(view['units'])}
        if a.run_class:
            for k in ('AGENT_LLM_BASE','AGENT_LLM_MODEL','AGENT_LLM_KEY'): os.environ.pop(k,None)
            # Inference authorization stays only in Model; never in tool context.
            model=official.Model({'llm':{'base':'market'}},registered.market,{'tokens':{'shop':registered.token('shop')}})
            result=dialogue(official,session,registered.market,gate,ctx,model)
    result.update({'official_market_model_called':a.run_class,'actual_customers_contacted':False,
      'wallet_loaded':False,'tool_tokens_count':0,'tool_addresses_count':0,'production_installed':False,
      'checkout_verified':False,'synthetic_guest_base':True,'scope':'question-explicit three SKUs only',
      'fragment_metadata_complete':False})
    (session/'summary.json').write_text(json.dumps(result,ensure_ascii=False)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='local_public_reply'},ensure_ascii=False))
    return result

if __name__=='__main__': main()
