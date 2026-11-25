"""Ephemeral keys + mocked maroo.pay + loopback HTTP only. No testing flags."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from hashlib import sha256
import base64,json,socket,sys,time,unittest,urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier,Event,Lock
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
OP=HERE.parents[3]
sys.path.insert(0,str(OP/'kit'))
import agent_kit as official
import serialized_signer as adapter

TX='0x'+'a'*64
RECIPIENT='0x'+'2'*40


class SerializedSignerQA(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(official,'log'))
        self.temp=self.stack.enter_context(TemporaryDirectory(prefix='r4-host-signer-qa-'))
        self.root=Path(self.temp)
        self.original_do=official.Signer.do
        self.adapter_class=adapter.serialized_signer_class(official.Signer)
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.signers=[]
        self.sdk_hashes={p.name:sha256(p.read_bytes()).hexdigest() for p in (OP/'kit').glob('*.py')}

    def tearDown(self):
        for signer in self.signers:
            signer.http.shutdown();signer.http.server_close()
        self.assertIs(official.Signer.do,self.original_do)
        self.assertEqual({p.name:sha256(p.read_bytes()).hexdigest() for p in (OP/'kit').glob('*.py')},self.sdk_hashes)

    def signer(self,keys=None):
        keys=keys or {'shop':official.maroo.Wallet.generate()}
        signer=self.adapter_class(keys,self.root)
        self.signers.append(signer)
        return signer

    def cap(self,signer,roles=('shop',),ops=('pay',),limit=1):
        return signer.grant('synthetic_host_qa',{'wallet':list(ops),'identity':list(roles),'pay_limit':limit},60)

    def request(self,cap,role='shop',**changes):
        req={'cap':cap,'op':'pay','role':role,'wei':1,'to':RECIPIENT,'data':'0x'}
        req.update(changes);return req

    def rpc(self,signer,req):
        self.assertNotIn('testing',req)
        request=urllib.request.Request(signer.url,data=json.dumps(req).encode(),headers={'content-type':'application/json'})
        with self.opener.open(request,timeout=5) as response:return json.load(response)

    def measured_pay(self,tracker):
        guard=Lock()
        def pay(*args):
            with guard:
                tracker['active']+=1;tracker['maximum']=max(tracker['maximum'],tracker['active']);tracker['calls']+=1
            try:time.sleep(.025);return TX
            finally:
                with guard:tracker['active']-=1
        return pay

    def test_same_wallet_http_maximum_inflight_one(self):
        signer=self.signer();tracker={'active':0,'maximum':0,'calls':0}
        requests=[self.request(self.cap(signer)) for _ in range(8)]
        with patch.object(official.maroo,'pay',side_effect=self.measured_pay(tracker)):
            with ThreadPoolExecutor(max_workers=8) as pool:outcomes=list(pool.map(lambda req:self.rpc(signer,req),requests))
        self.assertEqual(outcomes,[{'result':TX}]*8)
        self.assertEqual(tracker,{'active':0,'maximum':1,'calls':8})

    def test_same_address_different_roles_share_lock(self):
        wallet=official.maroo.Wallet.generate();signer=self.signer({'shop':wallet,'buyer':wallet})
        tracker={'active':0,'maximum':0,'calls':0}
        requests=[self.request(self.cap(signer,('shop','buyer')),'shop' if i%2 else 'buyer') for i in range(8)]
        with patch.object(official.maroo,'pay',side_effect=self.measured_pay(tracker)):
            with ThreadPoolExecutor(max_workers=8) as pool:outcomes=list(pool.map(lambda req:self.rpc(signer,req),requests))
        self.assertEqual(outcomes,[{'result':TX}]*8);self.assertEqual(tracker['maximum'],1);self.assertEqual(tracker['calls'],8)

    def test_same_address_case_variants_share_lock(self):
        wallet=official.maroo.Wallet.generate()
        import copy
        alias=copy.copy(wallet);alias.address=wallet.address.lower()
        signer=self.signer({'shop':wallet,'buyer':alias});tracker={'active':0,'maximum':0,'calls':0}
        requests=[self.request(self.cap(signer,('shop','buyer')),role) for role in ('shop','buyer')]
        with patch.object(official.maroo,'pay',side_effect=self.measured_pay(tracker)):
            with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(lambda req:self.rpc(signer,req),requests))
        self.assertEqual(tracker['maximum'],1);self.assertEqual(tracker['calls'],2)

    def test_different_wallets_can_pay_concurrently(self):
        signer=self.signer({'shop':official.maroo.Wallet.generate(),'buyer':official.maroo.Wallet.generate()});gate=Barrier(2,timeout=3)
        def pay(*args):gate.wait();return TX
        with patch.object(official.maroo,'pay',side_effect=pay):
            with ThreadPoolExecutor(max_workers=2) as pool:
                jobs=[pool.submit(self.rpc,signer,self.request(self.cap(signer,('shop','buyer')),role)) for role in ('shop','buyer')]
                self.assertEqual([job.result(timeout=5) for job in jobs],[{'result':TX}]*2)

    def waiting_capability(self,kind):
        signer=self.signer();entered=Event();release=Event();waiting=Event();count=0;count_lock=Lock()
        original=adapter._lock_for_address
        def observed_lock(address):
            nonlocal count
            with count_lock:
                count+=1
                if count==2:waiting.set()
            return original(address)
        def pay(*args):entered.set();self.assertTrue(release.wait(3));return TX
        first=self.cap(signer);second=self.cap(signer)
        with patch.object(adapter,'_lock_for_address',side_effect=observed_lock),patch.object(official.maroo,'pay',side_effect=pay) as mocked:
            with ThreadPoolExecutor(max_workers=2) as pool:
                active=pool.submit(self.rpc,signer,self.request(first));self.assertTrue(entered.wait(2))
                queued=pool.submit(self.rpc,signer,self.request(second));self.assertTrue(waiting.wait(2))
                self.assertEqual(mocked.call_count,1)
                if kind=='revoked':self.assertEqual(signer.revoke(second),[])
                else:signer.caps[second]['until']=time.time()-1
                release.set()
                self.assertEqual(active.result(timeout=4),{'result':TX})
                outcome=queued.result(timeout=4)
                self.assertIn('PermissionError',outcome.get('error',''));self.assertEqual(mocked.call_count,1)

    def test_waiting_revoked_capability_cannot_pay(self):self.waiting_capability('revoked')
    def test_waiting_expired_capability_cannot_pay(self):self.waiting_capability('expired')

    def test_original_capability_role_operation_and_limit_checks_remain(self):
        signer=self.signer({'shop':official.maroo.Wallet.generate(),'buyer':official.maroo.Wallet.generate()})
        valid=self.cap(signer);sign_only=self.cap(signer,ops=('sign',))
        expired=self.cap(signer);signer.caps[expired]['until']=time.time()-1
        requests=[self.request(None),self.request('not-a-capability'),self.request(expired),
                  self.request(valid,role='buyer'),self.request(valid,role='missing'),self.request(sign_only),
                  self.request(valid,wei=-1),self.request(valid,wei=official.maroo.CREDIT_WEI+1)]
        with patch.object(official.maroo,'pay') as pay:
            for index,req in enumerate(requests):
                with self.subTest(check=index):self.assertIn('PermissionError',self.rpc(signer,req).get('error',''))
            pay.assert_not_called()

    def test_exception_releases_address_lock_and_original_sent_order(self):
        signer=self.signer();cap=self.cap(signer)
        with patch.object(official.maroo,'pay',side_effect=[RuntimeError('synthetic failure'),TX]):
            self.assertIn('RuntimeError',self.rpc(signer,self.request(cap)).get('error',''))
            self.assertEqual(signer.caps[cap]['sent'],[])
            self.assertEqual(self.rpc(signer,self.request(cap)),{'result':TX})
        self.assertEqual(len(signer.caps[cap]['sent']),1)
        self.assertEqual(signer.caps[cap]['sent'][0]['tx_hash'],TX)

    def test_sign_and_sign_jwt_unchanged_and_not_blocked_by_pay(self):
        signer=self.signer();cap=self.cap(signer,ops=('pay','sign','sign_jwt'));entered=Event();release=Event()
        obj={'synthetic':True}
        def pay(*args):entered.set();self.assertTrue(release.wait(3));return TX
        with patch.object(official.maroo,'pay',side_effect=pay):
            with ThreadPoolExecutor(max_workers=1) as pool:
                paying=pool.submit(self.rpc,signer,self.request(cap));self.assertTrue(entered.wait(2))
                signed=self.rpc(signer,{'cap':cap,'op':'sign','role':'shop','obj':obj})
                jwt=self.rpc(signer,{'cap':cap,'op':'sign_jwt','role':'shop','payload':obj})
                self.assertTrue(official.maroo.verify(signer.keys['shop'].address,signed['result'],official.mk.canon(obj)))
                self.assertEqual(jwt['result'],official.mk.jwt_sign(signer.keys['shop'],obj))
                self.assertFalse(paying.done());release.set();self.assertEqual(paying.result(timeout=4),{'result':TX})

    def test_original_inflight_revoke_sent_timing_limit_is_preserved(self):
        signer=self.signer();cap=self.cap(signer);entered=Event();release=Event()
        def pay(*args):entered.set();self.assertTrue(release.wait(3));return TX
        with patch.object(official.maroo,'pay',side_effect=pay):
            with ThreadPoolExecutor(max_workers=1) as pool:
                paying=pool.submit(self.rpc,signer,self.request(cap));self.assertTrue(entered.wait(2))
                self.assertEqual(signer.revoke(cap),[])
                release.set();self.assertEqual(paying.result(timeout=4),{'result':TX})
        self.assertNotIn(cap,signer.caps)

    def test_repeated_factory_selection_cannot_double_lock(self):
        self.adapter_class=adapter.serialized_signer_class(self.adapter_class)
        signer=self.signer()
        with patch.object(official.maroo,'pay',return_value=TX) as pay:
            self.assertEqual(self.rpc(signer,self.request(self.cap(signer))),{'result':TX})
            pay.assert_called_once()

    def test_factory_does_not_modify_official_class_or_install_it(self):
        self.assertIs(official.Signer.do,self.original_do)
        self.assertIsNot(self.adapter_class,official.Signer)
        self.assertTrue(issubclass(self.adapter_class,official.Signer))


if __name__=='__main__':
    output=HERE/'validation';output.mkdir(exist_ok=True)
    real_connect=socket.socket.connect
    def local_only(sock,address):
        if isinstance(address,tuple) and address[0] not in ('127.0.0.1','::1'):raise AssertionError('NONLOCAL_NETWORK_FORBIDDEN')
        return real_connect(sock,address)
    with patch.object(socket.socket,'connect',local_only), (output/'serialized-signer-final.log').open('w') as log:
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SerializedSignerQA))
    summary={'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
             'failed_tests':[test.id().split('.')[-1] for test,_ in result.failures+result.errors],
             'module_sha256':sha256((HERE/'serialized_signer.py').read_bytes()).hexdigest(),
             'test_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),
             'ephemeral_keys_only':True,'mocked_maroo_pay_only':True,'localhost_http_only':True,
             'manually_set_testing_flags':False,'real_key_files_read':False,'production_db_read':False,
             'original_sdk_files_unchanged':True,'installed_live':False,'durable_send_recovery_implemented':False}
    (output/'serialized-signer-final-summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary))
    raise SystemExit(not result.wasSuccessful())
