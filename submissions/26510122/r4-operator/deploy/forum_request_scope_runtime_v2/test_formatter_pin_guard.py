"""New exact formatter pin guards only; no Model or SDK business call."""
from pathlib import Path
import importlib.util,sys,hashlib,shutil,tempfile,unittest,json
OP=Path('/home/seop/.local/share/ourolabs-r4-checkout/submissions/26510122/r4-operator');sys.path.insert(0,str(OP/'kit'))
spec=importlib.util.spec_from_file_location('scope2_pin_guard',Path(__file__).with_name('marketing_request_glue.py'));h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
SOURCE=OP/'runtime/class-rebuild-forum-formatter-20261127/tools/prioritize_forum_candidates'
class Pins(unittest.TestCase):
 def test_exact_actual3_admitted(self):self.assertEqual(h.reviewed_formatter(SOURCE,h.FORMATTER3_PINS),SOURCE)
 def test_original2_cannot_substitute(self):
  old=OP/'deploy/forum_native_slate_runtime_v2_host3_20261126/tools/prioritize_forum_candidates';pins={n:hashlib.sha256((old/n).read_bytes()).hexdigest() for n in h.EXACT4}
  with self.assertRaises(ValueError):h.reviewed_formatter(old,pins)
 def test_pinned3_drift_rejected(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t)
   for n in h.EXACT4:shutil.copyfile(SOURCE/n,root/n)
   (root/'logic.py').write_bytes((root/'logic.py').read_bytes()+b'\n# synthetic unauthorized drift\n')
   with self.assertRaises(ValueError):h.reviewed_formatter(root,h.FORMATTER3_PINS)
 def test_prior_frozen_packages_preserved(self):
  base=OP/'runtime/marketing-request-20261127-method'
  self.assertEqual(hashlib.sha256((base/'MANIFEST.json').read_bytes()).hexdigest(),'a4d70b23223c2751489b67e331abdbb329086190da2a9306f1a11e0d9e738fbb')
  self.assertEqual(hashlib.sha256((base/'cold-start-host-v1/MANIFEST.json').read_bytes()).hexdigest(),'477f9f1e7e7bc6043e87362f755c436ec48d860dc477eaaf89aeb9a18e127f34')
if __name__=='__main__':
 result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Pins))
 Path(__file__).with_name('PIN-GUARD-QA.json').write_text(json.dumps({'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'actual_Model_or_business_calls':0,'change_after_class_canary':'Added fixed exact3 pin constant/guard only; same actual business+formatter4 and input code unchanged; no extra class call'},indent=2));raise SystemExit(not result.wasSuccessful())
