"""Independent host cutover QA; temporary trees/processes only, no live actions."""
from contextlib import redirect_stdout
from hashlib import sha256
import io,json,os,signal,subprocess,sys,unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
WORK=HERE.parent/'codex-r4'
OP=HERE.parents[3]
sys.path.insert(0,str(WORK))
import card_guard_cutover_host as cut
import managed_runtime_card_guard_candidate as managed
REAL_RUNNING=cut.running_tool
GUARD=OP/'runtime/class-rebuild-reach-20261125/tools'/cut.NAME

class IndependentCutoverQA(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory(prefix='r4-card-cutover-independent-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.prod=self.root/'fixture-production';self.target=self.prod/'tools'/cut.NAME
        self.target.mkdir(parents=True);self.session=self.root/'session';self.session.mkdir()
        self.old=cut.bundle(OP.parent/'round-4/tools'/cut.NAME,cut.OLD);self.new=cut.bundle(GUARD,cut.NEW)
        for name,data in self.old.items():(self.target/name).write_bytes(data)
        (self.prod/'card.json').write_bytes(b'{"name":"synthetic-card"}')

    def invoke(self,**options):
        options.setdefault('sleep',lambda n:None);options.setdefault('probe',lambda *args:None)
        with patch.object(cut,'running_tool',return_value=False):
            return cut.fence(self.prod,self.session,self.new,OP/'kit',**options)

    def test_ten_second_drain_precedes_process_probe(self):
        observed=[]
        with patch.object(cut,'running_tool',side_effect=lambda _:observed.append('proc') or False):
            cut.fence(self.prod,self.session,self.new,OP/'kit',sleep=lambda n:observed.append(n),probe=lambda *a:observed.append('guard'))
        self.assertEqual(observed,[10,'proc','guard'])
        self.assertEqual(cut.bundle(self.target,cut.NEW),self.new)

    def test_proc_recognizes_actual_synthetic_runner(self):
        script=self.root/'forge_runner.py';script.write_text('import time\ntime.sleep(10)\n')
        child=subprocess.Popen([sys.executable,str(script),str(self.target),'call'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:self.assertTrue(REAL_RUNNING(self.target))
        finally:child.terminate();child.wait(timeout=3)

    def test_same_uid_proc_read_error_must_not_claim_quiescence(self):
        class Unreadable:
            def read_bytes(self):raise PermissionError('synthetic proc denial')
        class FakeProc:
            name='999999999'
            def stat(self):return SimpleNamespace(st_uid=os.getuid())
            def __truediv__(self,other):return Unreadable()
        with patch.object(Path,'iterdir',return_value=iter([FakeProc()])):
            with self.assertRaises((OSError,ValueError,RuntimeError),msg='UNREADABLE_SAME_UID_PROC_MUST_FAIL_CLOSED'):
                REAL_RUNNING(self.target)

    def test_atomic_exchange_and_exact_probe_rollback(self):
        before=(self.prod/'card.json').read_bytes()
        def fail(*a):raise ValueError('synthetic probe fault')
        with self.assertRaisesRegex(ValueError,'synthetic probe fault'):self.invoke(probe=fail)
        self.assertEqual(cut.bundle(self.target,cut.OLD),self.old);self.assertEqual((self.prod/'card.json').read_bytes(),before)

    def test_existing_native_event_blocks_fence(self):
        pub=self.prod/'card_publication';pub.mkdir();(pub/'head.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'native publication already started'):self.invoke()
        self.assertEqual(cut.bundle(self.target,cut.OLD),self.old)

    def test_native_event_during_probe_forbids_legacy_restore(self):
        def progress(*a):
            (self.prod/'card_publication/head.json').write_text('{}');raise ValueError('synthetic native event')
        with self.assertRaisesRegex(RuntimeError,'automatic restore refused'):self.invoke(probe=progress)
        self.assertEqual(cut.bundle(self.target,cut.NEW),self.new)

    def test_authority_file_during_probe_forbids_legacy_restore(self):
        def progress(*a):
            inputs=self.prod/'host_inputs';inputs.mkdir();(inputs/'card_publication_authority.json').write_text('{}');raise ValueError('synthetic authority')
        with self.assertRaisesRegex(RuntimeError,'automatic restore refused'):self.invoke(probe=progress)
        self.assertEqual(cut.bundle(self.target,cut.NEW),self.new)

    def test_unknown_runtime_after_failed_replace_keeps_guard(self):
        runtime=self.prod/'codex-r4/managed_runtime.py';runtime.parent.mkdir();runtime.write_bytes(b'old-runtime')
        def partial(path,raw):path.write_bytes(b'unexpected-runtime');raise OSError('synthetic partial replace')
        with patch.object(cut,'managed_replace',side_effect=partial):
            with self.assertRaisesRegex(RuntimeError,'automatic restore refused'):
                self.invoke(managed=(runtime,b'old-runtime',b'new-runtime'))
        self.assertEqual((self.target/'forge.json').read_bytes(),self.new['forge.json'],'UNSAFE_LEGACY_RESTORED_BEFORE_MANAGED_RUNTIME_VALIDATION')

    def test_replaced_new_runtime_can_rollback_exactly(self):
        runtime=self.prod/'codex-r4/managed_runtime.py';runtime.parent.mkdir();runtime.write_bytes(b'old-runtime');calls=[]
        def fail_after_replace(path,raw):
            path.write_bytes(raw);calls.append(raw)
            if len(calls)==1:raise OSError('synthetic fsync fault')
        with patch.object(cut,'managed_replace',side_effect=fail_after_replace):
            with self.assertRaisesRegex(OSError,'synthetic fsync fault'):self.invoke(managed=(runtime,b'old-runtime',b'new-runtime'))
        self.assertEqual(cut.bundle(self.target,cut.OLD),self.old);self.assertEqual(runtime.read_bytes(),b'old-runtime')

    def test_no_allow_fence_main_changes_no_files(self):
        fakeop=self.root/'student/operator';fakeprod=fakeop.parent/'round-4';runtime=fakeop/'runtime'
        olddir=fakeprod/'tools'/cut.NAME;newdir=runtime/'class-rebuild-reach-20261125/tools'/cut.NAME
        olddir.mkdir(parents=True);newdir.mkdir(parents=True)
        for directory,bundle in ((olddir,self.old),(newdir,self.new)):
            for name,data in bundle.items():(directory/name).write_bytes(data)
        def tree():
            return {str(p.relative_to(self.root)):(p.is_dir(),p.stat().st_mode,p.read_bytes() if p.is_file() else None) for p in self.root.rglob('*')}
        before=tree();args=['cutover','--operator',str(fakeop),'--session',str(runtime/'card-cutover-dry-synthetic')]
        with patch.object(sys,'argv',args),redirect_stdout(io.StringIO()) as capture:cut.main()
        self.assertEqual(json.loads(capture.getvalue())['status'],'dry');self.assertEqual(tree(),before)

    def test_startup_guard_exact_pins_and_permissions(self):
        directory=self.root/'new-guard';directory.mkdir()
        for name,data in self.new.items():(directory/name).write_bytes(data)
        perm={'write':['card_handoff_selftest'],'pay_limit':0}
        self.assertTrue(managed.card_publisher_allowed({'dir':directory,'perm':perm}))
        for field,value in (('write',['card.json','card_handoff_selftest']),('wallet',['pay']),('network',['invalid']),('identity',['shop']),('exec',True),('handles',['a2a']),('pay_limit',1)):
            with self.subTest(field=field):self.assertFalse(managed.card_publisher_allowed({'dir':directory,'perm':dict(perm,**{field:value})}))
        (directory/'logic.py').write_bytes(b'tampered')
        self.assertFalse(managed.card_publisher_allowed({'dir':directory,'perm':perm}))

    def test_startup_explicitly_keeps_unpinned_legacy_compatibility(self):
        self.assertTrue(managed.card_publisher_allowed({'perm':{'write':['card.json']}}))

if __name__=='__main__':
    out=HERE/'validation/card-cutover-independent-refined-20261125';out.mkdir(exist_ok=False)
    names=('card_guard_cutover_host.py','managed_runtime_card_guard_candidate.py','card_offer_producer_host.py','card_stage_recheck_controller.py','card_apply_authority_host.py')
    pins={name:sha256((WORK/name).read_bytes()).hexdigest() for name in names}
    snapshots=out/'source';snapshots.mkdir()
    for name in names:(snapshots/name).write_bytes((WORK/name).read_bytes())
    with (out/'unittest-original.log').open('w') as log:
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(IndependentCutoverQA))
    report={'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'failed_tests':[test.id().split('.')[-1] for test,_ in result.failures+result.errors],
            'source_sha256':pins,'source_unchanged_during_run':{name:sha256((WORK/name).read_bytes()).hexdigest()==pin for name,pin in pins.items()},
            'synthetic_trees_only':True,'synthetic_process_only':True,'production_files_modified':False,'service_db_wallet_calls':False,'live_cutover_performed':False}
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report));raise SystemExit(not result.wasSuccessful())
