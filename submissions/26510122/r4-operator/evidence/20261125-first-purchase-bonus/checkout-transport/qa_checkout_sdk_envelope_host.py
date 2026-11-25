"""Single synthetic ordinary SDK ASGI signed-checkout transport regression."""
from pathlib import Path
from hashlib import sha256
from contextlib import redirect_stdout,redirect_stderr
from copy import deepcopy
from unittest.mock import patch
import json,sys,time,socket
import sys
sys.path.insert(0,str(next(p for p in Path(__file__).resolve().parents if (p/'kit/agent_kit.py').exists())/'runtime/r3-stock-20261124-204104/agent-work/host'))
import public_catalogue_class_canary_host as host
OP=next(p for p in Path(__file__).resolve().parents if (p/'kit/agent_kit.py').exists())
import os
OUT=Path(os.environ['CHECKOUT_QA_ROOT']).resolve();OUT.mkdir(mode=0o700,parents=True,exist_ok=False)
BUNDLE=OP/'deploy/public_catalogue_runtime_v2';PIN=sha256((BUNDLE/'MANIFEST.json').read_bytes()).hexdigest()
def main():
    sys.path[:0]=[str(OP.parent/'round-4/codex-r4'),str(OP/'kit')]
    import dispatcher
    from fixture import Fixture,MOCK_SKU,MOCK_MARKET,MOCK_SHOP
    from e2e import no_network,customer_module
    now=int(time.time());source=OUT/'synthetic-public-source.json'
    source.write_bytes(host.encode({'schema':'outseop-r4.customer-offers.v1','shop':'outseop-r4','observed_at':now,'valid_until':now+150,'units':[{'unit_ref':'synthetic-checkout-unit','sku':MOCK_SKU,'name':'합성 식품','category_path':['식품'],'state':'available','grade':'A','price_credits':4500,'standard_fee_credits':None,'expires_at':now+3600}]}));source.chmod(0o400)
    session=OUT/'session';raw,snapshot=host.prepare(OP,session,source,BUNDLE,PIN)
    runtime=session/'runtime';sys.path.insert(0,str(runtime));broker=host.module('broker',runtime/'broker_public_catalogue_host_candidate.py');sys.modules['broker_public_catalogue_host_candidate']=broker
    managed=host.module('checkout_managed',runtime/'managed_runtime_public_catalogue_host_candidate.py')
    worker=host.module('checkout_worker',runtime/'bounded_public_catalogue_host.py');protocol=host.module('checkout_protocol',runtime/'public_catalogue_protocol.py');request=host.module('checkout_request',runtime/'public_catalogue_request_host.py');composition=host.module('checkout_composition',runtime/'public_catalogue_composition_candidate.py')
    import agent_kit as official
    from starlette.testclient import TestClient
    prepared=json.loads((session/'PREPARED.json').read_bytes());sealed=worker.BoundedPublicCatalogue(runtime/'catalogue',OP/'kit',session/'scratch',prepared['genuine_exact4']);calls=[]
    def invoke(**kwargs):
        calls.append(kwargs['args']['op']);assert kwargs['snapshot']==raw;return sealed(**kwargs)
    def factory(execute):return request.ScopedPublicCatalogue(lambda:(raw,deepcopy(snapshot)),invoke,protocol.CatalogueProtocol(broker.mask),composition.SEARCH_INSTRUCTION)
    box_class,mind_class,app_factory=managed.managed_classes(official,catalogue_source_factory=factory)
    f=Fixture(session,run=dispatcher.run);f.now=float(now);f.add_unit('synthetic-checkout-unit',price=4500,grade='A');original=[];actions=[]
    class NoWallet:
        def grant(self,*a,**kw):raise AssertionError('unexpected original capability execution')
    class Box(box_class):
        def decision_tool(self,details):
            actions.append(details['action']);answer=f.call({'_broker':details})
            if 'checkout_jwt' in answer.get('data',{}):original.append(deepcopy(answer))
            return answer
    ctx={'name':f.kit.name,'market':MOCK_MARKET,'tokens':{},'addresses':{},'signer':NoWallet()};official.mk.LOG_FILE=session/'logs/SDK-private.log';box=Box(session,ctx);box.validate()
    class Model:
        calls=0
        def complete(self,messages,**kwargs):
            self.calls+=1;return json.dumps({'action':'quote_and_send','args':{'sku':MOCK_SKU,'proposed_price':4500}})
    model=Model();mind=mind_class(session,{'max_steps':3},model,box,ctx,[]);app=app_factory(session,f.kit.name,mind,box,[MOCK_SHOP])
    payload={'jsonrpc':'2.0','id':1,'method':'SendMessage','params':{'message':{'messageId':'synthetic-checkout-transport','role':'ROLE_USER','parts':[{'text':'구매 '+MOCK_SKU}],'metadata':{'from':'synthetic-local-guest'}}}}
    with patch.object(socket,'getaddrinfo',no_network),patch.object(socket.socket,'connect',no_network),TestClient(app,base_url=MOCK_SHOP) as client:response=client.post('/',headers={'A2A-Version':'1.0'},json=payload)
    value=response.json();(session/'logs/asgi-response-private.json').write_text(json.dumps(value));task=value['result'].get('task',value['result']);parts=task['artifacts'][0]['parts'];data=[p['data'] for p in parts if 'data'in p][0]
    assert response.status_code==200 and len(original)==1;assert data==original[0]['data'];assert data['checkout_jwt']==original[0]['data']['checkout_jwt']
    token=customer_module().jwt_payload(data['checkout_jwt'],f.kit.address('shop'))
    with f.open() as db:sale=dict(db.execute('SELECT * FROM sale').fetchone())
    assert token['item']==MOCK_SKU and token['claim']=='A' and token['price']==4500 and token['unit']=='synthetic-checkout-unit';assert sale['unit']==token['unit'] and sale['base']==token['price'] and sale['status']=='issued'
    assert f.sends==0 and not f.entries and model.calls==1 and actions==['context','quote_and_send'] and calls==['context']
    safe={'case':'genuine dispatcher checkout to final official SDK ASGI artifacts','passed':True,'HTTP':response.status_code,'final_jwt_byte_identical':True,'final_data_exact_original':True,'sku_grade_price_unit_unchanged':True,'fake_checkout_status':sale['status'],'real_Model_calls':0,'mock_Model_calls':model.calls,'real_network_payment_calls':0,'settlements':0,'fake_pay_attempts':f.sends,'catalogue_ops':calls,'legacy_actions':actions,'runtime_manifest_sha256':PIN,'source_hashes':prepared['runtime_source_hashes'],'genuine_catalogue_exact4':prepared['genuine_exact4'],'official_SDK7':prepared['official_SDK7'],'dispatcher_sha256':sha256(Path(dispatcher.__file__).read_bytes()).hexdigest(),'production_state_modified':False,'private_response_exported':False}
    (OUT/'safe-result.json').write_text(json.dumps(safe,indent=2));return safe
if __name__=='__main__':
    with (OUT/'private-console.log').open('w') as log,redirect_stdout(log),redirect_stderr(log):result=main()
    print(json.dumps({'passed':result['passed'],'final_jwt_byte_identical':result['final_jwt_byte_identical'],'real_Model_calls':0,'real_network_payment_calls':0}))
