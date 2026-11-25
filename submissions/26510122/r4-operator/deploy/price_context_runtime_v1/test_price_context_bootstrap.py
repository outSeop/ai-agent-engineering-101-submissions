from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import importlib.util,json,os,sys,tempfile,unittest
OP=Path('/home/seop/.local/share/ourolabs-r4-checkout/submissions/26510122/r4-operator')
spec=importlib.util.spec_from_file_location('price_bootstrap_tested',Path(__file__).with_name('price_context_bootstrap.py'));h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
class Tests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.folder=Path(self.temp.name);self.root=self.folder/'registered';self.cwd=self.folder/'operator';(self.root/'codex-r4').mkdir(parents=True);(self.cwd/'codex-r4').mkdir(parents=True)
  self.raw=(OP.parent/'round-4/codex-r4/price_policy.py').read_bytes();(self.root/'codex-r4/price_policy.py').write_bytes(self.raw)
  def policy(name):return json.dumps({'policy_id':name,'starts_at':100,'ends_at':200,'total_loss_credits':1000,'per_deal_bps':100}).encode()
  self.actual=self.root/'codex-r4/launch-price-policy.json';self.actual.write_bytes(policy('registered_fixture'));self.decoy=self.cwd/'codex-r4/launch-price-policy.json';self.decoy.write_bytes(policy('wrong_cwd_fixture'))
  self.oldcwd=Path.cwd();os.chdir(self.cwd);self.addCleanup(os.chdir,self.oldcwd)
  self.oldmodule=sys.modules.pop('price_policy',None);self.addCleanup(self.restore)
 def restore(self):
  sys.modules.pop('price_policy',None)
  if self.oldmodule is not None:sys.modules['price_policy']=self.oldmodule
 def test_wrong_cwd_corrected_without_copy_or_global_chdir(self):
  scope={'__file__':str(self.root/'codex-r4/price_policy.py')};exec(compile(self.raw,scope['__file__'],'exec'),scope);self.assertEqual(scope['current'](150)['policy_id'],'wrong_cwd_fixture')
  before=self.actual.read_bytes(),self.decoy.read_bytes(),Path.cwd()
  with patch.object(h,'REGISTERED',self.root):m=h.bind_policy();self.assertEqual(m.current(150)['policy_id'],'registered_fixture');self.assertIs(sys.modules['price_policy'],m)
  self.assertEqual(before,(self.actual.read_bytes(),self.decoy.read_bytes(),Path.cwd()))
 def test_source_drift_rejected(self):
  (self.root/'codex-r4/price_policy.py').write_bytes(self.raw+b'\n')
  with patch.object(h,'REGISTERED',self.root),self.assertRaises(ValueError):h.bind_policy()
 def test_symlink_configuration_rejected(self):
  self.actual.unlink();self.actual.symlink_to(self.decoy)
  with patch.object(h,'REGISTERED',self.root),self.assertRaises(ValueError):h.bind_policy()
 def test_unreviewed_preloaded_module_rejected(self):
  sys.modules['price_policy']=SimpleNamespace(__file__=str(self.cwd/'fake.py'),POLICY_PATH=h.POLICY_RELATIVE)
  with patch.object(h,'REGISTERED',self.root),self.assertRaises(ValueError):h.bind_policy()
 def test_registered_binding_idempotent(self):
  with patch.object(h,'REGISTERED',self.root):first=h.bind_policy();self.assertIs(first,h.bind_policy());self.assertEqual(first.POLICY_PATH,self.actual)
 def test_real_fixed_targets_manifest_verified_and_other_rejected(self):
  for alias in ('catalogue','card'):self.assertTrue(h.verify_target(alias).is_file())
  with self.assertRaises(ValueError):h.verify_target('../anything.py')
 def test_original_target_filename_args_and_cwd_preserved_mock_runpy(self):
  target=OP/'deploy/public_catalogue_runtime_v3d/public_catalogue_snapshot_producer.py';args=['--operator',str(OP),'--manifest-sha256','818e94a3c7c845ed7b3b93afe41c0883e6eecda24b0b0bf960f5d87dc1efa094'];before=Path.cwd();oldargv=sys.argv[:];oldpath=sys.path[:]
  self.addCleanup(setattr,sys,'argv',oldargv);self.addCleanup(setattr,sys,'path',oldpath)
  with patch.object(h,'REGISTERED',self.root),patch.object(h.runpy,'run_path',return_value={}) as run:h.run('catalogue',args);run.assert_called_once_with(str(target),run_name='__main__')
  self.assertEqual(sys.argv,[str(target),*args]);self.assertEqual(Path.cwd(),before)
 def test_wrong_operator_rejected_before_target_execution(self):
  with patch.object(h,'REGISTERED',self.root),patch.object(h.runpy,'run_path') as run,self.assertRaises(ValueError):h.run('card',['--operator',str(self.cwd)])
  run.assert_not_called()
if __name__=='__main__':unittest.main()
