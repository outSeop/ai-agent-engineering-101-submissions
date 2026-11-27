from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from contextlib import ExitStack
import copy,sys,unittest,json
sys.path.insert(0,str(Path(__file__).parent))
import transition_guard as g
URL='https://synthetic-only.invalid'
def card(description='old'):
 return {'name':'outseop-r4','description':description,'roles':['shop'],'wallets':{'shop':'synthetic-fixture'},'supportedInterfaces':[{'url':URL,'protocolBinding':'JSONRPC'}]}
class RefreshQA(unittest.TestCase):
 def test_main_uses_post_idle_origin(self):
  old,new=card('before-idle'),card('after-idle')
  with ExitStack() as c:
   for name in ('verify_package','verify_original_front','preserve_processes'):c.enter_context(patch.object(g,name))
   c.enter_context(patch.object(g.os,'geteuid',return_value=0));c.enter_context(patch.object(Path,'stat',return_value=SimpleNamespace(st_uid=1000)))
   c.enter_context(patch.object(g,'chain',return_value=g.OLD_PORT));c.enter_context(patch.object(g,'identities',side_effect=[old,new]));c.enter_context(patch.object(g,'idle10',return_value=21));replace=c.enter_context(patch.object(g,'replace'));post=c.enter_context(patch.object(g,'public_matches',return_value={'ok':True}));c.enter_context(patch('builtins.print'))
   g.main(['--package-manifest-sha','fixture','--expected-main-pid','1','--expected-old-edge-pid','2','--expected-legacy-edge-pid','3','--expected-public-url',URL,'--apply'])
   self.assertEqual(post.call_args.args,(URL,new,g.NEW_MARKER));replace.assert_called_once_with(g.OLD_PORT,g.NEW_PORT)
 def test_description_changes_are_rebound_to_current(self):
  anchor,first,current=card('at-cutover'),card('new1'),card('new2')
  with patch.object(g,'identities',side_effect=[first,current]),patch.object(g,'card',side_effect=[(card('old-public'),{'x-r4-edge':g.NEW_MARKER}),(current,{'x-r4-edge':g.NEW_MARKER})]),patch.object(g,'pending_matches',return_value=True):
   out=g.public_matches(URL,anchor,g.NEW_MARKER)
  self.assertEqual(out['attempts'],2);self.assertEqual(out['description_refreshes'],1)
 def test_old_marker_waits_then_requires_exact_new_marker(self):
  value=card()
  with patch.object(g,'identities',return_value=value),patch.object(g,'card',side_effect=[(value,{'x-r4-edge':g.OLD_MARKER}),(value,{'x-r4-edge':g.NEW_MARKER})]),patch.object(g,'pending_matches',return_value=True),patch.object(g.time,'sleep') as sleep:
   out=g.public_matches(URL,value,g.NEW_MARKER)
  sleep.assert_called_once_with(6);self.assertEqual(out['old_marker_waits'],1)
 def test_persistent_old_marker_never_accepted(self):
  value=card()
  with patch.object(g,'identities',return_value=value),patch.object(g,'card',return_value=(value,{'x-r4-edge':g.OLD_MARKER})),patch.object(g,'pending_matches',return_value=True),patch.object(g.time,'sleep') as sleep:
   with self.assertRaisesRegex(ValueError,'public_marker_not_converged'):g.public_matches(URL,value,g.NEW_MARKER)
  self.assertEqual(sleep.call_count,2)
 def test_wallet_URL_or_name_change_fails_immediately(self):
  value=card()
  for field in ('wallets','supportedInterfaces','name'):
   bad=copy.deepcopy(value);bad[field]={'shop':'different'} if field=='wallets' else [{'url':'https://different.invalid'}] if field=='supportedInterfaces' else 'different'
   with patch.object(g,'identities',return_value=value),patch.object(g,'card',return_value=(bad,{'x-r4-edge':g.NEW_MARKER})),patch.object(g,'pending_matches',return_value=True),patch.object(g.time,'sleep') as sleep:
    with self.assertRaisesRegex(ValueError,'public_identity_changed'):g.public_matches(URL,value,g.NEW_MARKER)
    sleep.assert_not_called()
 def test_pending_URL_never_relaxed(self):
  value=card()
  with patch.object(g,'identities',return_value=value),patch.object(g,'card',return_value=(value,{'x-r4-edge':g.NEW_MARKER})),patch.object(g,'pending_matches',return_value=False):
   with self.assertRaisesRegex(ValueError,'pending_checkout_URL_drift'):g.public_matches(URL,value,g.NEW_MARKER)
 def test_late_HTTP_result_is_not_accepted(self):
  value=card()
  with patch.object(g,'identities',return_value=value),patch.object(g,'card',return_value=(value,{'x-r4-edge':g.NEW_MARKER})) as request,patch.object(g.time,'monotonic',side_effect=[0,19,20.1]):
   with self.assertRaisesRegex(ValueError,'public_postcheck_deadline'):g.public_matches(URL,value,g.NEW_MARKER)
  self.assertEqual(request.call_args.kwargs['timeout'],1)
 def test_sleep_never_exceeds_remaining_budget(self):
  value=card()
  with patch.object(g,'identities',return_value=value),patch.object(g,'card',return_value=(value,{'x-r4-edge':g.OLD_MARKER})),patch.object(g,'pending_matches',return_value=True),patch.object(g.time,'monotonic',side_effect=[0,15,15.1,15.2,15.3]),patch.object(g.time,'sleep') as sleep:
   with self.assertRaisesRegex(ValueError,'public_marker_not_converged'):g.public_matches(URL,value,g.NEW_MARKER)
  sleep.assert_not_called()
 def test_rollback_does_not_require_failed_new_listener(self):
  value=card()
  with patch.object(g,'identities',return_value=value) as identify,patch.object(g,'card',return_value=(value,{'x-r4-edge':g.OLD_MARKER})),patch.object(g,'pending_matches',return_value=True):g.public_matches(URL,value,g.OLD_MARKER)
  self.assertFalse(identify.call_args.kwargs['include_new'])
if __name__=='__main__':unittest.main()
