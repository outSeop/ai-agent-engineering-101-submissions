import importlib.util,json,sys,unittest,io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from contextlib import redirect_stdout
spec=importlib.util.spec_from_file_location('guard_tested',Path(__file__).with_name('route_guard.py'));g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
class Tests(unittest.TestCase):
 def invoke(self,mode,bad_public=False,pending=True):
  commands=[];present=[mode=='--rollback'];same={'name':'outseop-r4','roles':['shop'],'wallets':{'shop':'SYNTHETIC_PUBLIC_WALLET'},'description':'fixture','supportedInterfaces':[{'url':'https://example.invalid'}]}
  def run(args,**kwargs):
   commands.append(args)
   if '-I' in args:present[0]=True
   if '-D' in args:present[0]=False
   return SimpleNamespace(returncode=0,stdout='')
  def card(url):return same,{'x-r4-edge':'r4-front-v1'} if ':18806' in url or (url.startswith('https://') and not bad_public) else {}
  args=['route_guard.py','--package-manifest-sha','synthetic','--expected-main-pid','123','--expected-public-url','https://example.invalid',mode]
  with patch.object(sys,'argv',args),patch.object(g,'verify_package'),patch.object(g.os,'geteuid',return_value=0),patch.object(g,'iptables',return_value='/usr/sbin/iptables'),patch.object(g,'exists',side_effect=lambda binary:present[0]),patch.object(g,'run',side_effect=run),patch.object(g,'card',side_effect=card),patch.object(g,'service_pid',return_value=123),patch.object(g,'idle10',return_value=21),patch.object(g,'pending_matches',return_value=pending),redirect_stdout(io.StringIO()):
   if bad_public or not pending:
    with self.assertRaises(ValueError):g.main()
   else:g.main()
  return commands,present[0]
 def test_exact_apply_rule_only(self):
  commands,present=self.invoke('--apply');self.assertTrue(present);self.assertIn(['/usr/sbin/iptables','-t','nat','-I','OUTPUT','1',*g.SPEC],commands);self.assertFalse(any('-F' in c for c in commands))
 def test_exact_rollback_only(self):
  commands,present=self.invoke('--rollback');self.assertFalse(present);self.assertEqual(commands,[['/usr/sbin/iptables','-t','nat','-D','OUTPUT',*g.SPEC]])
 def test_failed_public_probe_rolls_back_exact_rule(self):
  commands,present=self.invoke('--apply',bad_public=True);self.assertFalse(present);self.assertIn(['/usr/sbin/iptables','-t','nat','-D','OUTPUT',*g.SPEC],commands)
 def test_pending_URL_mismatch_blocks_before_rule(self):
  commands,present=self.invoke('--apply',pending=False);self.assertFalse(present);self.assertEqual(commands,[])
 def test_fixed_scope(self):
  self.assertIn('127.0.0.1/32',g.SPEC);self.assertEqual(g.SPEC.count('127.0.0.1/32'),2);self.assertIn('--uid-owner',g.SPEC);self.assertIn('1000',g.SPEC);self.assertIn('18805',g.SPEC);self.assertIn('18806',g.SPEC)
if __name__=='__main__':unittest.main()
