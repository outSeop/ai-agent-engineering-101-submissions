"""공통 front의 stub 배선/일반 SDK ASGI 회귀. 실제 모델 의미 검증이 아니다."""
from pathlib import Path
from types import SimpleNamespace
import argparse,hashlib,json,os,sys,tempfile,time,unittest
from contextlib import redirect_stdout,redirect_stderr
import catalogue_asgi_support as support

CONTEXT=None
class FixtureClockContract(unittest.TestCase):
 def test_fixture_timestamp_is_explicit_and_serialization_stable(self):
  # Fixture-only determinism. Real SDK/tool clock is intentionally unchanged.
  self.assertEqual(hashlib.sha256(support.CASES['unsupported-compound-repeat'].encode()).hexdigest(),'0d0e2a5afabbd2c631be6a553469aef348a5fefac775d2df499f331be6119434')
  stamp=1700000000
  raw,a=support.public_source(stamp);same,b=support.public_source(stamp);later,c=support.public_source(stamp+1)
  self.assertEqual(raw,same)
  self.assertEqual(a,b)
  self.assertNotEqual(raw,later)
  self.assertEqual(a['units'][0]['expires_at']+1,c['units'][0]['expires_at'])

class CatalogueASGIRegression(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  if CONTEXT is None:raise unittest.SkipTest('explicit --operator/--output and pinned build required')
 def setUp(self):
  # setUp failures are normal errors, never swallowed by expectedFailure.
  self.unsupported_result=None
  if self._testMethodName=='test_original_unsupported_compound_plus_repeat_expected_failure':
   self.unsupported_result=self.replay('unsupported-compound-repeat')
   if self.unsupported_result['status']!='verified_genuine_ASGI_final_reply':
    self.assertEqual(self.unsupported_result['semantic_native_status'],'unavailable')
    self.assertEqual(self.unsupported_result['semantic_native_reason'],'unsupported_request')
 def replay(self,case):
  c=CONTEXT
  with (c.output/(case+'-console-private.log')).open('x') as private,redirect_stdout(private),redirect_stderr(private):
   result=support.run_case(c.operator,c.workspace/case,case,c.build,c.runtime,c.front,c.runner,c.edge,c.config,c.fixture_clock)
  c.case_results.append(result)
  self.assertEqual(result['http_status'],200)
  self.assertEqual(result['model_calls'],1)
  self.assertEqual(result['financial_executor_attempts'],0)
  self.assertTrue(result['maintenance_closed_503_without_Model'])
  self.assertFalse(result['legacy_admission_used'])
  self.assertEqual(result['legacy_admission_count'],0)
  self.assertTrue(result['durable_current_owner_indexed'])
  self.assertTrue(result['stub_wiring']['actual_native_groups_equal_stub'])
  self.assertTrue(result['stub_wiring']['complete_original_text_forwarded'])
  self.assertFalse(result['stub_wiring']['actual_Model_semantic_interpretation_tested'])
  self.assertTrue(result['isolated_root_for_agent_mind_app_toolbox'])
  return result
 def test_supported_compound_stub_wires_two_groups_to_genuine_ASGI(self):
  result=self.replay('compound')
  self.assertEqual(result['status'],'verified_genuine_ASGI_final_reply')
  self.assertTrue(result['final_reply_exact_genuine'])
 def test_supported_repeat_stub_wires_one_group_to_genuine_ASGI(self):
  result=self.replay('repeated-positive')
  self.assertEqual(result['status'],'verified_genuine_ASGI_final_reply')
  self.assertTrue(result['final_reply_exact_genuine'])
 @unittest.expectedFailure
 def test_original_unsupported_compound_plus_repeat_expected_failure(self):
  # Original overscoped fixture is unchanged. If supported later, unittest marks
  # unexpected success as a failure so the documented contract must be reviewed.
  result=self.unsupported_result
  self.assertEqual(result['status'],'verified_genuine_ASGI_final_reply')
  self.assertTrue(result['final_reply_exact_genuine'])

def main(argv=None):
 global CONTEXT
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--operator',type=Path,required=True)
 p.add_argument('--output',type=Path,required=True)
 p.add_argument('--build-receipt',type=Path,required=True)
 p.add_argument('--build-sha256',required=True)
 p.add_argument('--expected-semantic-version',type=int,default=9)
 p.add_argument('--fixture-now',type=int,help='Optional shared timestamp; must remain fresh for unchanged native SDK TTL150')
 a=p.parse_args(argv);operator=a.operator.expanduser().resolve(strict=True)
 if a.expected_semantic_version<=0:p.error('positive exact semantic version required')
 output=a.output.expanduser().resolve()
 forbidden=[operator.parent/'round-4',operator/'deploy',operator/'runtime/releases',operator/'src',operator/'evidence']
 if any(output.is_relative_to(path) for path in forbidden):p.error('QA output cannot be in production/source/immutable artifact directories')
 if output.exists():p.error('fresh --output required; existing artifacts are never overwritten')
 output.mkdir(mode=0o700,parents=True)
 if output.resolve()!=output or output.stat().st_uid!=os.getuid():p.error('owned canonical output required')
 if {l.split(':')[0].strip() for l in Path('/proc/net/dev').read_text().splitlines()[2:]}!={'lo'}:p.error('stub replay requires network isolation: unshare -Urn')
 build,runtime,front,runner,edge,config=support.verify_build(operator,a.build_receipt.expanduser().absolute(),a.build_sha256,a.expected_semantic_version)
 clock=int(time.time()) if a.fixture_now is None else a.fixture_now
 if not 0<=time.time()-clock<120:p.error('fixture timestamp must be current within original TTL; no SDK clock is spoofed')
 workspace=Path(tempfile.mkdtemp(prefix='host-front-test-',dir=operator/'runtime'));workspace.chmod(0o700)
 CONTEXT=SimpleNamespace(operator=operator,output=output,workspace=workspace,build=build,runtime=runtime,front=front,runner=runner,edge=edge,config=config,fixture_clock=clock,case_results=[])
 suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(FixtureClockContract),unittest.defaultTestLoader.loadTestsFromTestCase(CatalogueASGIRegression)])
 result=unittest.TextTestRunner(verbosity=2).run(suite)
 safe={'scope':'Official SDK ASGI with predetermined Model stub; Model semantics/provider/runtime inference NOT evaluated','tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'expected_failures':len(result.expectedFailures),'unexpected_successes':len(result.unexpectedSuccesses),'was_successful':result.wasSuccessful(),'case_results':CONTEXT.case_results,'fixture_observed_at':clock,'fixture_food_expires_at':clock+86400,'SDK_wall_clock_unchanged':True,'cross_run_reply_hash_fixed':False,'hash_clock_explanation':'Input asof/expiry are shared within a run; unchanged native render reads real clock, so remaining seconds and reply SHA may differ across runs. Compare final text to genuine output within the same request.','build_sha256':a.build_sha256,'runtime_manifest_sha256':build['runtime_manifest_sha256'],'front_manifest_sha256':build['front_manifest_sha256'],'fixture_workspace_relative':str(workspace.relative_to(operator)),'actual_Model_API_DB_key_production_log_service_POST_pay_calls':0,'old_evidence_modified':False}
 (output/'safe-result.json').write_text(json.dumps(safe,indent=2))
 print(json.dumps({'tests_run':safe['tests_run'],'expected_failures':safe['expected_failures'],'unexpected_successes':safe['unexpected_successes'],'was_successful':safe['was_successful'],'safe_result':str(output/'safe-result.json')}))
 return 0 if result.wasSuccessful() else 1
if __name__=='__main__':raise SystemExit(main())
