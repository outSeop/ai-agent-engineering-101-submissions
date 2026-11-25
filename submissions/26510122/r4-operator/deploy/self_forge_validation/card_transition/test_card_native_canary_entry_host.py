"""Entry default/no-live gating QA on the already-tested synthetic fixture."""
from contextlib import redirect_stdout,redirect_stderr
from hashlib import sha256
import io,json,unittest
from pathlib import Path
from unittest.mock import patch
from test_card_apply_canary_host import CanaryHostQA,official
import card_native_canary_entry_host as entry
import card_stage_recheck_controller as controller

HERE=Path(__file__).resolve().parent
class EntryQA(unittest.TestCase):
    def setUp(self):
        self.fixture=CanaryHostQA('test_dry_default_changes_nothing');self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        target=self.fixture.base/'round-4';self.fixture.prod.rename(target);self.fixture.prod=target
        self.op=self.fixture.base/'operator';self.op.mkdir()
    def test_default_plan_has_no_model_or_file_writes(self):
        before=self.fixture.tree()
        with patch.object(official,'Model',side_effect=AssertionError('MODEL_FORBIDDEN')),redirect_stdout(io.StringIO()):
            result=entry.main(['--operator',str(self.op)])
        self.assertEqual(result['status'],'source_plan_only');self.assertFalse(result['writes_performed']);self.assertFalse(result['model_called']);self.assertEqual(self.fixture.tree(),before)
    def test_allow_apply_without_controller_is_rejected(self):
        before=self.fixture.tree()
        with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):entry.main(['--operator',str(self.op),'--allow-apply'])
        self.assertEqual(self.fixture.tree(),before)
    def test_live_object_continuation_defaults_to_no_apply(self):
        anchors=self.fixture.base/'anchors.json';anchors.write_text(json.dumps(self.fixture.policies))
        span=self.fixture.base/'span.txt';span.write_text('old sales copy');before=self.fixture.tree()
        receipt={}
        def same_run(argv,*,continuation):
            receipt.update(continuation(origin=self.fixture.origin,original_view_raw=self.fixture.old,fresh_view_raw=self.fixture.fresh,before_card_raw=self.fixture.before))
        with patch.object(controller,'main',side_effect=same_run) as invoked,patch.object(official,'Model',side_effect=AssertionError('MODEL_FORBIDDEN')),redirect_stdout(io.StringIO()):
            result=entry.main(['--operator',str(self.op),'--session',str(self.fixture.session),'--replace-text-file',str(span),'--policy-anchors',str(anchors),'--run-controller'])
        invoked.assert_called_once();self.assertEqual(receipt,result);self.assertEqual(result['status'],'dry');self.assertEqual(self.fixture.tree(),before)
        self.assertTrue((self.fixture.session/'canary-host-result.json').exists())
if __name__=='__main__':
    out=Path(__import__('tempfile').mkdtemp(prefix='r4-card-canary-public-entry-'))
    with patch.object(official,'log'),patch.object(official.maroo.Wallet,'load',side_effect=AssertionError('KEY_LOAD_FORBIDDEN')),patch.object(official.maroo,'pay',side_effect=AssertionError('REAL_PAY_FORBIDDEN')),(out/'unittest-original.log').open('w') as log:
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(EntryQA))
    report={'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'entry_sha256':sha256((HERE/'card_native_canary_entry_host.py').read_bytes()).hexdigest(),'synthetic_only':True,'real_model_invoked':False,'production_root_used':False,'manual_testing_flag':False,'output_directory':str(out)}
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report));raise SystemExit(not result.wasSuccessful())
