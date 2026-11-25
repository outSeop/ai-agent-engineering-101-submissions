import contextlib
import io
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import Mock,patch

import customer_native_context_canary_host as host
OP=next(p for p in Path(__file__).resolve().parents if (p/'kit/agent_kit.py').exists())
sys.path.insert(0,str(OP/'kit'));import agent_kit as sdk
SNAP=Path(__file__).parent/'validation/customer-native-v4-canary-20261125/build_customer_context'

class CanaryTests(unittest.TestCase):
    def setUp(self):
        self.t=TemporaryDirectory(dir=SNAP.parent);self.addCleanup(self.t.cleanup)
        self.session=Path(self.t.name)/'session';now=int(time.time())
        offers=[{'sku':sku,'_unit':'fixture-unit-'+str(i),'grade':'B','price':20+i,'expiry':now+600} for i,sku in enumerate((*host.SCOPE,'G00000001'))]
        catalog=[{'sku':r['sku'],'name':'Synthetic food '+str(i),'category':'food>fruit'} for i,r in enumerate(offers)]
        self.facts=(now,offers,catalog)
        self.view=host.scoped_context(offers,catalog,now)
        self.target,self.inputs=host.install_inputs(self.session,host.load_bundle(SNAP),self.view)
        self.ctx={'name':'outseop-r4','market':'http://127.0.0.1:1','tokens':{},'addresses':{},'signer':host.NoWallet()}
        sdk.mk.LOG_FILE=self.session/'logs/agent-kit.log'
        self.box=sdk.Toolbox(self.session,self.ctx)
        self.gate=host.NativeGate(self.box,self.target,self.inputs)
    def test_exact_sources_scope_and_synthetic_base(self):
        self.assertEqual(host.load_bundle(self.target),host.load_bundle(SNAP))
        self.assertEqual({r['sku'] for r in self.view['units']},set(host.SCOPE))
        self.assertNotIn('fixture-unit',json.dumps(self.view))
        self.assertEqual(json.loads((self.session/'host_inputs/broker_context_base.json').read_bytes()),host.GUEST)
        self.assertEqual(self.ctx['tokens'],{});self.assertEqual(self.ctx['addresses'],{})
    def test_normal_sdk_call_raw_response_and_native_errors(self):
        out=self.gate.call(host.TOOL,{'op':'context'})
        self.assertTrue(out['ok']);self.assertIn('verified_context',out['result'])
        self.assertEqual(len(out['result']['verified_context']['inventory']['rows']),3)
        self.assertEqual(self.box.stats[host.TOOL]['uses'],1)
        wrong=self.gate.call(host.TOOL,{'op':'context','skus':list(host.SCOPE)})
        self.assertTrue(wrong['ok']);self.assertIn('error',wrong['result'])
        self.assertEqual(self.gate.actions[-1]['native_error'],True)
    def test_description_byte_content_and_no_old_adapter(self):
        desc=self.box.tools[host.TOOL]['description']
        self.assertEqual(len(desc),600);self.assertTrue(desc.endswith('next'))
        self.assertIn(desc,self.gate.listing());self.assertIn('detail_pin',desc)
        self.assertIn('error',self.gate.call('read_customer_offers',{'op':'next'}))
        self.assertIn('error',self.gate.forge({}));self.assertIn('error',self.gate.read(host.TOOL))
    def test_fixed_file_tamper_fails_before_sdk(self):
        p=next(iter(self.inputs));p.chmod(0o600);p.write_text('{}')
        with patch.object(self.box,'call') as called:
            with self.assertRaises(ValueError):self.gate.call(host.TOOL,{'op':'context'})
            called.assert_not_called()
    def test_source_tamper_fails_before_sdk(self):
        p=self.target/'logic.py';p.chmod(0o600);p.write_text('# changed')
        with patch.object(self.box,'call') as called:
            with self.assertRaises(ValueError):self.gate.call(host.TOOL,{'op':'context'})
            called.assert_not_called()
    def test_official_mind_mock_model_context_details_local_reply(self):
        calls=[]
        def model_step(messages):
            step=len(calls);calls.append(True)
            if step==0:return json.dumps({'action':host.TOOL,'args':{'op':'context'}})
            if step==1:
                raw=messages[-1]['content'].split('Observation: ',1)[1]
                result=json.loads(raw)['result']
                table=result['verified_context']['inventory'];row=table['rows'][0]
                packed=dict(table['common']);packed.update(zip(table['columns'],row))
                if 'sku' in table['lookup']:packed['sku']=table['lookup']['sku'][packed['sku']]
                args={k:result[k] for k in ('snapshot','detail_pin','as_of')}
                args.update(op='details',row=0,sku=packed['sku'])
                return json.dumps({'action':host.TOOL,'args':args})
            if step==2:
                event=json.loads(messages[1]['content'].split('Messages waiting for you (answer with reply):\n')[1])[0]
                return json.dumps({'action':'reply','args':{'to':event['id'],'text':'합성 공개 세 SKU의 확인된 정보를 읽었습니다.'}})
            return json.dumps({'action':'sleep','args':{'seconds':30}})
        model=Mock();model.complete.side_effect=model_step
        result=host.dialogue(sdk,self.session,self.ctx['market'],self.gate,self.ctx,model)
        self.assertEqual(result['status'],'local_reply_complete')
        self.assertTrue(result['native_context_called'])
        self.assertEqual([a['op'] for a in self.gate.actions],['context','details'])
        self.assertFalse(any(a['native_error'] for a in self.gate.actions))
        self.assertEqual(len(calls),4)
    def test_prepare_default_never_constructs_model(self):
        class Registered:
            market='http://127.0.0.1:1'
            def token(self,*a):raise AssertionError('prepare must not request inference token')
        session=OP/'runtime'/('customer-native-v4-canary-synthetic-'+str(os.getpid())+'-'+str(time.time_ns()))
        try:
            with patch.object(host,'acquire',return_value=(Registered(),*self.facts)),patch.object(sdk,'Model',side_effect=AssertionError('no inference')),contextlib.redirect_stdout(io.StringIO()):
                result=host.main(['--operator',str(OP),'--session',str(session)])
            self.assertEqual(result['status'],'prepared');self.assertFalse(result['official_market_model_called'])
            self.assertFalse(result['wallet_loaded']);self.assertEqual(result['tool_tokens_count'],0)
        finally:
            # only this explicitly fresh synthetic path is removed
            import shutil
            if session.exists():shutil.rmtree(session)

if __name__=='__main__':unittest.main()
