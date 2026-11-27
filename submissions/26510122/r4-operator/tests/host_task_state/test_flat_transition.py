"""Exact-rule migration safety with no root, services, network or financial DB."""
from pathlib import Path
from unittest.mock import patch,Mock,call
import sys,unittest
OP=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(OP/'src/r4_operator_host/front'),str(OP/'src/r4_operator_host')]
import flat_transition as guard

def state(current=0,maintenance=True):
    return {'maintenance':maintenance,'stats':{'current':current,'tasks':current,'legacy':41,'snapshots':41}}
class Tests(unittest.TestCase):
    def setUp(self):
        self.stack=[]
        for name in ('state_operation','router_card','postcheck'):
            manager=patch.object(guard,name);mock=manager.start();self.addCleanup(manager.stop);setattr(self,name,mock)
        for name in ('idle10','replace'):
            manager=patch.object(guard.legacy,name);mock=manager.start();self.addCleanup(manager.stop);setattr(self,name,mock)
        self.check=Mock();self.state_operation.return_value=state()
    def run_apply(self):return guard.activate_new_router(OP,OP/'runtime/fixture','https://fixture.invalid',self.check)
    def test_success_opens_only_after_strict_postcheck(self):
        events=[];self.replace.side_effect=lambda *args:events.append(('replace',args))
        self.postcheck.side_effect=lambda *args:events.append(('postcheck',args))
        self.state_operation.side_effect=lambda *args,**kw:events.append(('state',kw)) or state(maintenance=kw.get('enable',True))
        result=self.run_apply();self.assertFalse(result['maintenance'])
        self.assertEqual(events[-3:],[('replace',('18810','18811')),('postcheck',('https://fixture.invalid',)),('state',{'enable':False})])
    def test_failed_postcheck_reverses_only_closed_pristine_current_engine(self):
        self.postcheck.side_effect=ValueError('fixture postcheck failure')
        with self.assertRaises(ValueError):self.run_apply()
        self.assertEqual(self.replace.call_args_list,[call('18810','18811'),call('18811','18810')])
        self.assertFalse(any(x.kwargs for x in self.state_operation.call_args_list))
    def test_any_current_task_prevents_reverse_after_failed_postcheck(self):
        self.state_operation.side_effect=[state(),state(current=1)]
        self.postcheck.side_effect=ValueError('fixture postcheck failure')
        with self.assertRaises(ValueError):self.run_apply()
        self.replace.assert_called_once_with('18810','18811')
    def test_existing_current_or_open_state_refuses_initial_migration(self):
        for value in (state(current=1),state(maintenance=False)):
            self.state_operation.return_value=value
            with self.assertRaises(ValueError):self.run_apply()
        self.replace.assert_not_called();self.idle10.assert_not_called()
    def test_process_change_before_rule_write_never_replaces_rule(self):
        self.check.side_effect=ValueError('fixture PID changed')
        with self.assertRaises(ValueError):self.run_apply()
        self.replace.assert_not_called()
if __name__=='__main__':unittest.main()
