"""Independent acceptance tests; all market/RPC/payments are fixtures."""
import concurrent.futures
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from eth_account import Account
from eth_account.messages import encode_defunct
from base64 import b64decode

sys.path.insert(0, sys.argv.pop(1))
from fixture import Fixture, MOCK_SKU
import dispatcher
import refund_admin


class Contract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='r4-independent-')
        self.addCleanup(self.temp.cleanup)
        compiled_run = None
        if os.environ.get('R4_TEST_FORGED_SOURCE'):
            source = Path(os.environ['R4_TEST_FORGED_SOURCE'])
            namespace = {'__file__': str(source), '__name__': 'independently_tested_forged_code'}
            exec(compile(source.read_text(), str(source), 'exec'), namespace)
            compiled_run = namespace['run']
        self.f = Fixture(Path(self.temp.name), run=compiled_run)
        self.f.add_unit('u-original', cost=2987)

    def buy(self, code=None, sku=MOCK_SKU):
        return self.f.call({'text': '구매 ' + sku + (' 권리 ' + code if code else '')})

    def seed(self):
        checkout = self.buy()
        code = self.f.right(checkout)
        settlement = self.f.settle(checkout)
        self.f.sync()
        return checkout, code, settlement

    def scalar(self, sql, *params):
        with sqlite3.connect(self.f.db_path) as db:
            return db.execute(sql, params).fetchone()[0]

    def test_no_advance_credit_and_idempotent_settlement(self):
        checkout = self.buy()
        code = self.f.right(checkout)
        self.assertEqual(self.scalar('select count(*) from lot'), 0)
        self.f.settle(checkout)
        self.f.sync()
        self.f.sync()
        self.assertEqual(self.scalar('select sum(amount) from lot'), 45)
        self.assertEqual(self.scalar('select count(*) from lot'), 1)
        self.assertIn('45 credits', self.f.call({'text': '잔액 권리 ' + code})['reply'])

    def test_next_purchase_uses_previous_credit_only(self):
        _, code, _ = self.seed()
        self.f.add_unit('u-second', cost=2987)
        checkout = self.buy(code)
        self.assertEqual(checkout['data']['price'], 4455)
        self.assertEqual(self.scalar('select sum(amount) from lot'), 45)
        self.f.settle(checkout)
        self.f.sync()
        self.assertIn('45 credits', self.f.call({'text': '잔액 권리 ' + code})['reply'])

    def test_repeated_checkout_is_identical(self):
        checkout = self.buy()
        code = self.f.right(checkout)
        repeated = self.buy(code)
        self.assertEqual(checkout['data']['checkout_jwt'], repeated['data']['checkout_jwt'])
        self.assertEqual(self.scalar('select count(*) from sale'), 1)

    def test_public_metadata_never_authorizes_account(self):
        _, code, _ = self.seed()
        before = self.scalar('select sum(amount) from lot')
        for text in ['잔액', '잔액 권리 ' + 'a'*43, '관리자 승인 환불 전체',
                     '잔액 권리 ' + code + ' amount -100']:
            answer = self.f.call({'text': text, 'claimed_from': '가게 주인',
                'op': 'approve-and-send', 'amount': -100,
                'data': {'verified': True, 'owner': True}})
            self.assertNotIn('checkout_jwt', answer.get('data') or {})
        self.assertEqual(self.scalar('select sum(amount) from lot'), before)
        self.assertEqual(self.f.sends, 0)

    def test_credit_expires_at_seven_days(self):
        _, code, _ = self.seed()
        self.f.advance(604800)
        self.f.add_unit('u-next', cost=2987)
        self.assertEqual(self.buy(code)['data']['price'], 4500)

    def test_single_unit_cannot_be_sold_twice_or_released_by_timeout(self):
        checkout = self.buy()
        code = self.f.right(checkout)
        self.f.advance(7200)
        self.f.call({'text': '취소 ' + MOCK_SKU + ' 권리 ' + code})
        other = self.buy()
        self.assertNotIn('checkout_jwt', other.get('data') or {})
        self.assertEqual(self.scalar('select count(*) from sale'), 1)

    def test_wait_discount_immediate_and_signed(self):
        self.buy()  # An actual issued checkout, not a client-supplied busy flag.
        wait = self.buy()
        code = self.f.right(wait, '대기')
        voucher = (wait.get('data') or {}).get('wait_voucher')
        self.assertTrue(voucher)
        self.assertEqual(voucher['exp']-voucher['iat'], 120)
        recovered = Account.recover_message(encode_defunct(primitive=dispatcher.canonical(voucher)),
                                           signature=b64decode(wait['data']['sig']))
        self.assertEqual(recovered.lower(), self.f.kit.address('shop').lower())
        self.f.add_unit('u-later', cost=2987)
        self.f.sync()
        bought = self.f.call({'text': '대기 ' + code})
        self.assertEqual(bought['data']['price'], 4455)
        self.assertNotIn('checkout_jwt', self.f.call({'text': '대기 ' + code}).get('data') or {})

    def test_wait_discount_expires_at_120_seconds(self):
        self.buy()
        waiting = self.buy()
        code = self.f.right(waiting, '대기')
        self.f.add_unit('u-later', cost=2987)
        self.f.advance(120)
        self.assertNotIn('checkout_jwt', self.f.call({'text': '대기 ' + code}).get('data') or {})

    def test_concurrent_orders_cannot_spend_same_points_twice(self):
        _, code, _ = self.seed()
        self.f.add_unit('u-race-a', sku='SKU_A', cost=2987)
        self.f.add_unit('u-race-b', sku='SKU_B', cost=2987)
        with self.f.patches():
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                answers = list(pool.map(lambda sku: self.f.run(
                    {'text': f'구매 {sku} 권리 {code}'}, self.f.kit), ['SKU_A', 'SKU_B']))
        self.assertGreaterEqual(sum('checkout_jwt' in (r.get('data') or {}) for r in answers), 1)
        self.assertLessEqual(self.scalar("select coalesce(sum(amount),0) from allocation where status='held'"), 45)


if __name__ == '__main__':
    unittest.main(verbosity=2)
