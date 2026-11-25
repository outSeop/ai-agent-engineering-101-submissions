"""Synthetic real-shaped Card -> genuine first apply -> handoff -> guard -> rollback."""
from copy import deepcopy
from hashlib import sha256
import json,sys,time,unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

HERE=Path(__file__).resolve().parent;WORK=HERE;OP=next(p for p in HERE.parents if (p/'kit/agent_kit.py').is_file())
sys.path.insert(0,str(HERE.parent))
sys.path.insert(0,str(WORK));sys.path.insert(0,str(OP/'kit'))
import agent_kit as official
import card_apply_canary_host as host
from card_apply_authority_host import StageOrigin,normalized_fresh
from card_offer_producer_host import produce_view
SOURCE=OP/'runtime/class-rebuild-reach-20261125'

class CanaryHostQA(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory(prefix='r4-card-canary-host-');self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.prod=self.base/'production-fixture';self.session=self.base/'controller-fixture'
        self.prod.mkdir();self.session.mkdir()
        for root in (self.prod,self.session):
            for relative in ('host_inputs','card_update_stage','card_publication'):(root/relative).mkdir(mode=0o700)
            (root/'card_publication/lock').touch(mode=0o600)
            for relative in host.PINS:
                directory=root/relative;directory.mkdir(parents=True)
                for name in host.FILES:(directory/name).write_bytes((SOURCE/relative/name).read_bytes())
        self.policies={'mileage':'모의 적립 약속','wait':'모의 대기 약속','refund':'모의 검토 약속'}
        self.before=json.dumps({'name':'outseop-r4','description':'기존 소개\nold sales copy\n기존 구매 안내',
          'skills':[{'id':'stock','description':'모의 공개 상품'}, {'id':'repeat-benefits','description':'모의 적립 약속. 모의 대기 약속.'},{'id':'refund-review','description':'모의 검토 약속.'}]},ensure_ascii=False).encode()
        for root in (self.prod,self.session):(root/'card.json').write_bytes(self.before)
        now=int(time.time())
        view=produce_view(self.before,'old sales copy',[{'sku':'G01234567','grade':'C','price':5100,'expiry':None}],
              [{'sku':'G01234567','name':'모의 상품','category':'모의 분류>하위'}],now)
        self.old=json.dumps(view,ensure_ascii=False).encode();(self.session/'host_inputs/card_offer_context.json').write_bytes(self.old)
        started=time.time_ns()
        response=host.toolbox(self.session,official).call('stage_representative_card',{'op':'stage','skus':['G01234567'],'view_sha256':host.sha(self.old)})
        self.assertTrue(response.get('ok'));self.assertEqual(response['result']['status'],'staged')
        self.origin=StageOrigin.capture(self.session/'card_update_stage',response['result'],self.old,
           host.PINS['tools/stage_representative_card'][2]['logic.py'],started,['G01234567'])
        while int(time.time())*10**9 < self.origin.mtime_ns:time.sleep(.015)
        fresh=deepcopy(view);fresh['observed_at']=int(time.time());fresh['valid_until']+=2;fresh['offers'][0]['valid_until']+=2
        self.fresh=json.dumps(normalized_fresh(self.origin,self.old,fresh,self.before,time.time_ns()),ensure_ascii=False).encode()
        self.options={'root':self.prod,'official':official,'stage_directory':self.session/'card_update_stage','origin':self.origin,
           'original_view_raw':self.old,'fresh_view_raw':self.fresh,'before_card_raw':self.before,'policy_anchors':self.policies}

    def tree(self):return {str(p.relative_to(self.prod)):p.read_bytes() for p in self.prod.rglob('*') if p.is_file()}

    def test_dry_default_changes_nothing(self):
        before=self.tree();result=host.apply_verified_stage(**self.options)
        self.assertEqual(result['status'],'dry');self.assertFalse(result['writes_performed']);self.assertEqual(self.tree(),before)
        self.assertFalse((self.prod/'tools/index.json').exists())

    def test_first_apply_handoff_guard_and_reviewed_rollback(self):
        lock_inode=(self.prod/'card_publication/lock').stat().st_ino
        result=host.apply_verified_stage(**self.options,allow_apply=True)
        self.assertEqual(result['status'],'applied');self.assertEqual(result['guard'],'skipped')
        self.assertEqual(host.sha((self.prod/'card.json').read_bytes()),result['card_sha256'])
        copied=self.prod/'card_update_stage'/(self.origin.record_id+'.json')
        self.assertEqual(copied.read_bytes(),self.origin.record_raw);self.assertEqual(copied.stat().st_mtime_ns,self.origin.mtime_ns)
        authority=json.loads((self.prod/'host_inputs/card_publication_authority.json').read_bytes())
        self.assertLessEqual(authority['valid_until']-authority['issued_at'],30)
        index=json.loads((self.prod/'tools/index.json').read_bytes())
        self.assertEqual(index['apply_staged_card']['uses'],1);self.assertEqual(index['publish_shop_info']['uses'],1)
        self.assertFalse((self.prod/'logs/forge.jsonl').exists())
        before=self.tree();dry=host.rollback_current(root=self.prod,official=official,event_id=result['event'])
        self.assertEqual(dry['status'],'dry_rollback');self.assertEqual(self.tree(),before)
        rolled=host.rollback_current(root=self.prod,official=official,event_id=result['event'],allow_rollback=True)
        self.assertEqual(rolled['status'],'rolled_back');self.assertEqual(rolled['guard'],'skipped')
        self.assertEqual((self.prod/'card.json').read_bytes(),self.before)
        self.assertEqual((self.prod/'card_publication/lock').stat().st_ino,lock_inode)
        self.assertEqual(host.verify_bundles(self.prod),host.verify_bundles(self.session))

    def test_wrong_skill_anchor_fails_before_writes(self):
        before=self.tree();options=dict(self.options,policy_anchors=dict(self.policies,refund='unapproved text'))
        with self.assertRaises(ValueError):host.apply_verified_stage(**options,allow_apply=True)
        self.assertEqual(self.tree(),before)

    def test_changed_card_or_stage_fails_without_native_state(self):
        (self.prod/'card.json').write_bytes(b'{}');before=self.tree()
        with self.assertRaises(ValueError):host.apply_verified_stage(**self.options,allow_apply=True)
        self.assertEqual(self.tree(),before)
        (self.prod/'card.json').write_bytes(self.before)
        (self.session/'card_update_stage'/(self.origin.record_id+'.json')).write_bytes(b'{}');before=self.tree()
        with self.assertRaises(ValueError):host.apply_verified_stage(**self.options,allow_apply=True)
        self.assertEqual(self.tree(),before)

    def test_expired_stage_is_not_resumed(self):
        until=json.loads(self.origin.record_raw)['valid_until'];before=self.tree()
        with patch.object(host.time,'time',return_value=until+1),self.assertRaises(ValueError):host.apply_verified_stage(**self.options,allow_apply=True)
        self.assertEqual(self.tree(),before)

    def test_bundle_tamper_rejected_before_publication(self):
        (self.prod/'tools/apply_staged_card/logic.py').write_bytes(b'changed');before=self.tree()
        with self.assertRaises(ValueError):host.apply_verified_stage(**self.options,allow_apply=True)
        self.assertEqual(self.tree(),before)

    def test_no_wallet_rejects_all_capability_requests(self):
        for field in ('wallet','identity','network','exec','handles'):
            with self.subTest(field=field),self.assertRaises(PermissionError):host.NoWallet().grant('apply_staged_card',{field:['forbidden']},30)

if __name__=='__main__':
    out=Path(__import__('tempfile').mkdtemp(prefix='r4-card-canary-public-host-'))
    with patch.object(official,'log'),patch.object(official.maroo.Wallet,'load',side_effect=AssertionError('KEY_LOAD_FORBIDDEN')),patch.object(official.maroo,'pay',side_effect=AssertionError('REAL_PAY_FORBIDDEN')),(out/'unittest-original.log').open('w') as log:
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CanaryHostQA))
    summary={'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'failed_tests':[test.id().split('.')[-1] for test,_ in result.failures+result.errors],
      'host_sha256':sha256((HERE/'card_apply_canary_host.py').read_bytes()).hexdigest(),'test_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),
      'ordinary_toolbox_call':True,'native_apply_handoff_guard_rollback_tested':True,'manual_index_edits':False,'forge_log_modified':False,
      'production_root_used':False,'production_keys_or_db_read':False,'real_network_or_wallet_pay':False,'manual_testing_flag':False,'live_installed':False,'output_directory':str(out)}
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary));raise SystemExit(not result.wasSuccessful())
