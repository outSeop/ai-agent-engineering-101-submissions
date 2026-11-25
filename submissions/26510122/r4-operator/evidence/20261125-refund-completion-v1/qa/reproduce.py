"""External host/test adapter. Selects tracked dependencies; adds no refund policy or fixture schema."""
from pathlib import Path
from contextlib import redirect_stdout
from hashlib import sha256
import io,json,sys,tempfile,types,unittest,socket
from unittest.mock import patch

PACKAGE=Path(__file__).resolve().parents[1]
OP=PACKAGE.parents[1]
REPO=OP.parents[2]
LEGACY=OP.parent/'round-4/codex-r4'
SHARED=OP/'evidence/20261125-self-forge/qa/legacy_refund_fixture.py'
VERSION=int(PACKAGE.name[-1])
SOURCE=PACKAGE/'qa'/('qa_refund_complete_legacy_v'+str(VERSION)+'.py')
GENERATED=PACKAGE/'generated/refund_complete_legacy'
for name in ('dispatcher.py','price_policy.py','procurement.py','fixture.py'):
    if not (LEGACY/name).is_file():raise SystemExit('Tracked legacy dependency unavailable')
sys.path.insert(0,str(LEGACY))
helper=types.ModuleType('legacy_refund_fixture')
# The helper's only __file__-relative operation selects literal procurement DDL.
# Resolve it against the tracked legacy source directory without copying or modifying business code.
helper.__file__=str(LEGACY/'legacy_refund_fixture.py')
exec(compile(SHARED.read_bytes(),str(SHARED),'exec'),helper.__dict__)
sys.modules['legacy_refund_fixture']=helper
scope={'__name__':'independent_qa_original','__file__':str(SOURCE)}
exec(compile(SOURCE.read_bytes(),str(SOURCE),'exec'),scope)
output=Path(tempfile.mkdtemp(prefix='r4-refund-completion-public-qa-'))
scope['OUT']=output
scope['SNAP']=GENERATED
# Only official-kit discovery uses HERE during tests; literal source schema is exported separately below.
scope['HERE']=OP/'runtime/reproduction/agent-work/codex-r4'
with (output/'unittest.log').open('w') as log, redirect_stdout(log), patch.object(socket.socket,'connect',side_effect=AssertionError('NETWORK_FORBIDDEN')):
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(scope['CompletionQA'])
    result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
failed_method_names={case.id().split('.')[-1].split(' ')[0] for case,_ in result.failures+result.errors}
report={'version':VERSION,'test_methods':result.testsRun,'passing_methods':result.testsRun-len(failed_method_names),
        'failing_methods':len(failed_method_names),'unittest_failure_records':len(result.failures),'harness_errors':len(result.errors),
        'failed_test_records':[case.id().split('.')[-1] for case,_ in result.failures],
        'candidate_logic_sha256':sha256((GENERATED/'logic.py').read_bytes()).hexdigest(),
        'qa_original_sha256':sha256(SOURCE.read_bytes()).hexdigest(),
        'adapter_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),
        'tracked_dependency_sha256':{name:sha256((LEGACY/name).read_bytes()).hexdigest() for name in ('dispatcher.py','price_policy.py','procurement.py','fixture.py')},
        'synthetic_only':True,'schema_added_by_adapter':False,'refund_policy_added_by_adapter':False,'production_ready':False,'output_directory':str(output)}
(output/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
(output/'source-schema-metadata.json').write_text(json.dumps(helper.source_contract(LEGACY),indent=2)+'\n')
print(json.dumps(report))
raise SystemExit(0 if result.wasSuccessful() else 1)
