import json
import sqlite3
from contextlib import closing


FIXTURE = 'refund_review_fixture.sqlite3'


def test(run, kit):
    assert kit.testing
    wallet = kit.address('shop')
    with closing(sqlite3.connect(FIXTURE)) as db:
        db.executescript('''
            CREATE TABLE identity(singleton INTEGER PRIMARY KEY, shop TEXT, wallet TEXT);
            CREATE TABLE sale(id TEXT PRIMARY KEY, owner TEXT, unit TEXT, sku TEXT, base INTEGER, cost INTEGER, price INTEGER, discount INTEGER, spent INTEGER, ticket TEXT, shop_url TEXT, wallet TEXT, created REAL, digest TEXT, jwt TEXT, expected_wei TEXT, fee_wei TEXT, gas_cap_wei TEXT, fee_wallet TEXT, grade TEXT, status TEXT, market_order TEXT, payment TEXT, fee_payment TEXT, payer TEXT, settled REAL, broken REAL);
            CREATE TABLE refund(sale_id TEXT PRIMARY KEY, incoming TEXT, payer TEXT, wei TEXT, marker TEXT, transfer_wei TEXT, fee_wei TEXT, gas_wei TEXT, fee_payment TEXT, reason TEXT, status TEXT, outgoing TEXT, requested REAL);
        ''')
        db.execute('INSERT INTO identity VALUES (1, ?, ?)', (kit.name, wallet))
        examples = [
            ('sale-boundary', 'settled', 1000, 173800, 'early_market_breakage', 'requested'),
            ('sale-late', 'settled', 1000, 173801, 'early_market_breakage', 'requested'),
            ('sale-reversed', 'settled', 1000, 999, 'early_market_breakage', 'requested'),
            ('sale-undelivered', 'paid', None, None, 'paid_no_delivery', 'requested'),
            ('sale-unknown', 'paid', None, None, 'paid_no_delivery', 'pending_unknown'),
            ('sale-wrong-state', 'settled', 1000, None, 'paid_no_delivery', 'requested'),
        ]
        for index, (sale, status, settled, broken, reason, refund_status) in enumerate(examples):
            db.execute('INSERT INTO sale(id, owner, ticket, wallet, jwt, expected_wei, payer, status, settled, broken) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', (sale, 'private-owner', 'private-rights-code', wallet, 'private-checkout-' + sale, '987654321', 'private-payer', status, settled, broken))
            db.execute('INSERT INTO refund(sale_id, reason, status, requested) VALUES (?, ?, ?, ?)', (sale, reason, refund_status, 200000 + index))
        db.commit()
        before = list(db.iterdump())
        result = run({}, kit)
        assert result['status'] == 'review_intake'
        assert result == run({}, kit)
        cases = result['cases']
        assert len(cases) == 5 and len({case['case_id'] for case in cases}) == 5
        assert [case['period'] for case in cases] == ['within_48_hours', 'outside_48_hours', 'invalid_event_order', 'not_applicable', 'not_applicable']
        assert [case['evidence']['reason'] for case in cases] == ['awaiting_market_breakage_confirmation', 'local_timing_mismatch', 'local_timing_mismatch', 'awaiting_removal_inventory_and_ledger', 'local_state_unverified']
        for case in cases:
            assert len(case['case_id']) == 64
            assert case['approval_ready'] is False
            assert case['evidence']['checkout'] == case['evidence']['original_transfers'] == 'unverified'
        encoded = json.dumps(result)
        for secret in ('sale-boundary', 'private-owner', 'private-rights-code', 'private-payer', 'private-checkout', '987654321', wallet):
            assert secret not in encoded
        assert run({'approved': True, 'ledger': {}}, kit) == {'status': 'invalid_arguments'}
        assert before == list(db.iterdump())
        wrong_wallet = '0x' + ('2' if wallet.lower() == '0x' + '1' * 40 else '1') * 40
        db.execute('UPDATE sale SET wallet=? WHERE id=?', (wrong_wallet, 'sale-undelivered'))
        db.commit()
        assert run({}, kit) == {'status': 'ledger_unverified'}
        db.execute('UPDATE sale SET wallet=? WHERE id=?', (wallet, 'sale-undelivered'))
        db.execute('UPDATE identity SET wallet=?', (wrong_wallet,))
        db.commit()
        assert run({}, kit) == {'status': 'ledger_unverified'}
