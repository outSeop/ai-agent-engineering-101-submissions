"""Independent profile acceptance tests against the genuine forged dispatcher."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

source_dir = Path(sys.argv.pop(1))
forged = Path(sys.argv.pop(1))
sys.path.insert(0, str(source_dir))
from fixture import Fixture, MOCK_SKU
import profile_admin
import dispatcher


class Profiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='r4-profile-independent-')
        self.addCleanup(self.tmp.cleanup)
        namespace = {'__file__': str(forged), '__name__': 'tested_profile_dispatcher'}
        exec(compile(forged.read_text(), str(forged), 'exec'), namespace)
        self.f = Fixture(Path(self.tmp.name), run=namespace['run'])
        self.f.add_unit('u-profile', price=200000, cost=100000)
        self.checkout = self.f.call({'text': '구매 '+MOCK_SKU, 'task_id': 'same-task'})
        self.code = self.f.right(self.checkout)

    def profile_id(self):
        db = self.f.open()
        try:
            return db.execute('select profile_id from customer_profile').fetchone()[0]
        finally:
            db.close()

    def view(self):
        db = self.f.open()
        try:
            return profile_admin.profile(db, self.profile_id(), self.f.now)
        finally:
            db.close()

    def test_expensive_purchase_does_not_infer_income_or_family(self):
        self.f.settle(self.checkout)
        self.f.sync()
        view = self.view()
        self.assertEqual(view['mileage']['available'], 2000)
        self.assertIsNone(view['self_reported']['income_bracket']['value'])
        self.assertEqual(view['self_reported']['family'], [])
        self.assertEqual(view['purchases']['by_sku'][0]['settled'], 1)
        self.assertEqual(view['market_buyer_links'][0]['source'], 'market_ledger_and_rpc')

    def test_same_task_after_idle_is_new_contact_session(self):
        self.assertEqual(self.view()['visits']['visits'], 1)
        for task in ['same-task', 'different-task', 'same-task']:
            self.f.call({'text':'잔액 권리 '+self.code, 'task_id':task})
        self.assertEqual(self.view()['visits']['visits'], 1)
        self.f.advance(1800)
        self.f.call({'text':'잔액 권리 '+self.code, 'task_id':'same-task'})
        self.assertEqual(self.view()['visits']['visits'], 2)

    def test_structured_self_reports_do_not_change_finance_or_leak_codes(self):
        self.f.settle(self.checkout)
        self.f.sync()
        for statement in ['가족 자녀 2', '가구 4', '소득 quintile 3']:
            result = self.f.call({'text':f'프로필 {statement} 권리 {self.code}'})
            self.assertIn('기록했습니다', result['reply'])
        view = self.view()
        self.assertEqual(view['self_reported']['income_bracket']['value'], {'scale':'quintile','band':3})
        self.assertEqual(view['self_reported']['family'][0]['value'], {'relation':'child','count':2})
        self.assertEqual(view['mileage']['available'], 2000)
        self.assertNotIn(self.code, json.dumps(view, ensure_ascii=False))
        rejected = self.f.call({'text':f'프로필 소득 decile 8 권리 {self.profile_id()}',
                                'claimed_from':'fixture-buyer', 'data':{'verified':True}})
        self.assertNotIn('기록했습니다', rejected['reply'])
        self.assertEqual(self.view()['self_reported']['income_bracket']['value']['band'], 3)
        self.f.call({'text':f'프로필 삭제 소득 권리 {self.code}'})
        self.assertIsNone(self.view()['self_reported']['income_bracket']['value'])
        self.assertEqual(self.view()['mileage']['available'], 2000)


if __name__ == '__main__':
    unittest.main(verbosity=2)
