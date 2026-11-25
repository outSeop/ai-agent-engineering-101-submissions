"""Mock producer only; exact genuine keeper tools on synthetic Card roots."""
from copy import deepcopy
from hashlib import sha256
import json,time,unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from qa_card_renewal_apply3_independent import RenewalIntegrationQA,official,infrastructure
import card_keeper_same_choice_host_candidate as keeper

HERE=Path(__file__).resolve().parent
class KeeperQA(unittest.TestCase):
    def setUp(self):
        self.fixture=RenewalIntegrationQA('test_actual_clock_old_ttl_past_refresh2_apply3_guard');self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        temporary=TemporaryDirectory(prefix='r4-keeper-operator-');self.addCleanup(temporary.cleanup);self.operator=Path(temporary.name);(self.operator/'runtime').mkdir()
        self.root=self.fixture.root;self.calls=0
        self.args={'operator':self.operator,'official':official,'_production':self.root,'policy_anchors':self.fixture.policies}
    def tree(self):return {str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
    def acquire(self,root,mutate=None):
        self.calls+=1
        _,event=infrastructure.committed(root)
        while int(time.time())<=event['recorded_at']:time.sleep(.015)
        view=json.loads((root/'host_inputs/card_offer_original'/(event['view_sha256']+'.json')).read_bytes())
        offers=[{'sku':r['sku'],'grade':r['grade'],'price':r['price_credits'],'expiry':r['expires_at']} for r in view['offers']]
        catalog=[{'sku':r['sku'],'name':r['name'],'category':'>'.join(r['category_path'])} for r in view['offers']]
        if mutate:mutate(offers)
        return None,int(time.time()),offers,catalog
    def test_default_dry_performs_no_producer_or_writes(self):
        before=self.tree()
        with patch.object(keeper.producer,'acquire') as mocked:result=keeper.run_once(**self.args)
        self.assertEqual(result['status'],'dry');mocked.assert_not_called();self.assertEqual(self.tree(),before)
        self.assertFalse((self.operator/'runtime/card-keeper-native').exists())
    def test_prepare_only_has_no_production_mutation(self):
        before=self.tree()
        with patch.object(keeper.producer,'acquire',side_effect=self.acquire):result=keeper.run_once(**self.args,prepare_only=True)
        self.assertEqual(result['status'],'prepared_only',result);self.assertEqual(self.calls,2);self.assertEqual(self.tree(),before)
    def test_two_successful_same_choice_cycles(self):
        start_id,start=infrastructure.committed(self.root);length=len(json.loads(start['after_card_json'])['description']);receipts=[]
        with patch.object(keeper.producer,'acquire',side_effect=self.acquire):
            for _ in range(2):
                result=keeper.run_once(**self.args,allow_refresh=True);self.assertEqual(result['status'],'applied',result);self.assertEqual(result['guard'],'skipped')
                _,event=infrastructure.committed(self.root,result['event']);self.assertEqual(event['skus'],self.fixture.selection);self.assertEqual(len(json.loads(event['after_card_json'])['description']),length)
                self.assertFalse(result['wallet_loaded']);self.assertFalse(result['orders_or_inventory_written']);receipts.append(result['receipt_sha256'])
        self.assertEqual(self.calls,4);self.assertEqual(len(set(receipts)),2)
    def test_changed_price_grade_or_stock_requires_class_selection(self):
        for field,value in (('price',9999),('grade','C'),('expiry',1)):
            before=self.tree()
            def changed(root,field=field,value=value):return self.acquire(root,lambda rows:rows[0].update({field:value}))
            with self.subTest(field=field),patch.object(keeper.producer,'acquire',side_effect=changed):
                result=keeper.run_once(**self.args,allow_refresh=True);self.assertEqual(result['status'],'requires_class_selection',result)
                self.assertEqual(self.tree(),before)
    def test_fresh_requery_change_requires_selection_without_repost(self):
        before=self.tree()
        def changed_after_stage(root):
            return self.acquire(root,(lambda rows:rows[0].update(price=9999)) if self.calls else None)
        with patch.object(keeper.producer,'acquire',side_effect=changed_after_stage):result=keeper.run_once(**self.args,allow_refresh=True)
        self.assertEqual(result['status'],'requires_class_selection',result);self.assertEqual(self.calls,2);self.assertEqual(self.tree(),before)
    def test_failed_read_does_not_repost_stale_card(self):
        before=self.tree()
        with patch.object(keeper.producer,'acquire',side_effect=TimeoutError('synthetic private error text not emitted')):result=keeper.run_once(**self.args,allow_refresh=True)
        self.assertEqual(result['status'],'read_or_recheck_unavailable');self.assertEqual(result['error_type'],'TimeoutError');self.assertNotIn('synthetic private',json.dumps(result));self.assertEqual(self.tree(),before)
    def test_private_oneshot_lock_prevents_overlap(self):
        with keeper.oneshot(self.operator),patch.object(keeper.producer,'acquire') as mocked:
            result=keeper.run_once(**self.args,allow_refresh=True)
        self.assertEqual(result['status'],'busy');mocked.assert_not_called()

if __name__=='__main__':
    output=HERE/'validation/card-keeper-host-synthetic-20261125';output.mkdir(exist_ok=False)
    with patch.object(official,'log'),patch.object(official.maroo.Wallet,'load',side_effect=AssertionError('KEY_LOAD_FORBIDDEN')),patch.object(official.maroo,'pay',side_effect=AssertionError('PAY_FORBIDDEN')),(output/'unittest-original.log').open('w') as log:
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(KeeperQA))
    report={'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'failed_tests':[test.id().split('.')[-1] for test,_ in result.failures+result.errors],
      'keeper_sha256':sha256((HERE/'card_keeper_same_choice_host_candidate.py').read_bytes()).hexdigest(),'authority_helper_sha256':sha256((HERE/'card_apply_v3_authority_host_candidate.py').read_bytes()).hexdigest(),
      'pins_manifest_sha256':sha256((HERE/'card_keeper_native_pins.json').read_bytes()).hexdigest(),
      'producer_mocked':True,'genuine_tool_calls_ordinary':True,'two_successful_cycles_tested':True,'actual_root_used':False,'model_wallet_keys_db_calls':False,'timer_installed':False,'manual_testing_flag':False}
    (output/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report));raise SystemExit(not result.wasSuccessful())
