from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys,unittest
sys.path.insert(0,str(Path(__file__).parent))
import transition_guard as g
LINE='-A OUTPUT '+' '.join(g.BASE)+' '
def response(port='18806',extra=''):return SimpleNamespace(returncode=0,stdout='-P OUTPUT ACCEPT\n'+LINE+port+'\n'+extra)
class QA(unittest.TestCase):
 def test_exact_old_and_new(self):
  for port in ('18806','18807'):
   with patch.object(g,'run',return_value=response(port)):self.assertEqual(g.chain(),port)
 def test_selector_and_extra_rule_rejected(self):
  for raw in (response().stdout.replace('--uid-owner 1000','--uid-owner 0'),response().stdout.replace('127.0.0.1/32','0.0.0.0/0'),response().stdout+'-A OUTPUT -j ACCEPT\n'):
   with patch.object(g,'run',return_value=SimpleNamespace(returncode=0,stdout=raw)):
    with self.assertRaises(ValueError):g.chain()
 def test_replace_preserves_own_rule(self):
  with patch.object(g,'chain',side_effect=['18806','18807']),patch.object(g,'run',return_value=SimpleNamespace(returncode=0)) as r:
   g.replace('18806','18807')
   self.assertEqual(r.call_args.args[0],[g.IPTABLES,'-w','3','-t','nat','-R','OUTPUT','1',*g.BASE,'18807'])
 def test_wrong_prestate_no_mutation(self):
  with patch.object(g,'chain',return_value='18807'),patch.object(g,'run') as r:
   with self.assertRaises(ValueError):g.replace('18806','18807')
   r.assert_not_called()
 def test_rollback_exact_reverse(self):
  with patch.object(g,'chain',side_effect=['18807','18806']),patch.object(g,'run',return_value=SimpleNamespace(returncode=0)) as r:
   g.replace('18807','18806');args=r.call_args.args[0];self.assertEqual(args[-1],'18806');self.assertIn('-R',args);self.assertNotIn('-D',args);self.assertNotIn('-F',args)
 def test_source_bind_only_fixed_loopback(self):
  calls=[]
  class Client:
   def __init__(self,**kw):pass
   def __enter__(self):return self
   def __exit__(self,*a):pass
   def get(self,url):return SimpleNamespace(raise_for_status=lambda:None,json=lambda:{},headers={})
  with patch.object(g.httpx,'HTTPTransport',side_effect=lambda **kw:calls.append(kw) or object()),patch.object(g.httpx,'Client',Client):
   g.card('http://127.0.0.1:18806/.well-known/agent-card.json');g.card('https://public-fixture.invalid/.well-known/agent-card.json')
  self.assertEqual(calls,[{'local_address':'127.0.0.2','retries':0},{'local_address':None,'retries':0}])
if __name__=='__main__':unittest.main()
