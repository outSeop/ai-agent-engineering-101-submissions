import hashlib
import json
import sqlite3
from contextlib import closing


def digest(domain, value):
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'))
    return hashlib.sha256(domain + b'\x00' + encoded.encode('ascii')).hexdigest()


def test(run, kit):
    assert kit.testing
    wallet = kit.address('shop')
    payer = '0x' + ('2' if wallet.lower() == '0x' + '1' * 40 else '1') * 40
    payment = '0x' + 'a' * 64
    fee_payment = '0x' + 'b' * 64
    sale_id, checkout, requested = 'private-sale-id', 'private-checkout-jwt', 200000.0
    case_id = digest(b'r4/refund-review/v1', [kit.name, sale_id, requested, checkout])
    prepare = {'operation': 'prepare', 'case_id': case_id}
    record = {'operation': 'record_decision', 'case_id': case_id}
    with closing(sqlite3.connect('refund_binding_fixture.sqlite3')) as db:
        db.row_factory = sqlite3.Row
        db.executescript('''
            CREATE TABLE identity(singleton INTEGER PRIMARY KEY, shop TEXT, wallet TEXT);
            CREATE TABLE sale(id TEXT PRIMARY KEY, owner TEXT, unit TEXT, sku TEXT, base INTEGER, cost INTEGER, price INTEGER, discount INTEGER, spent INTEGER, ticket TEXT, shop_url TEXT, wallet TEXT, created REAL, digest TEXT, jwt TEXT, expected_wei TEXT, fee_wei TEXT, gas_cap_wei TEXT, fee_wallet TEXT, grade TEXT, status TEXT, market_order TEXT, payment TEXT, fee_payment TEXT, payer TEXT, settled REAL, broken REAL);
            CREATE TABLE refund(sale_id TEXT PRIMARY KEY, incoming TEXT, payer TEXT, wei TEXT, marker TEXT, transfer_wei TEXT, fee_wei TEXT, gas_wei TEXT, fee_payment TEXT, reason TEXT, status TEXT, outgoing TEXT, requested REAL);
            CREATE TABLE mock_host_proof(case_id TEXT PRIMARY KEY, snapshot TEXT, reference TEXT, checkout TEXT, transfers TEXT, reason_evidence TEXT, principal_wei TEXT, fee_wei TEXT, gas_wei TEXT);
            CREATE TABLE mock_review_preparation(case_id TEXT PRIMARY KEY, binding TEXT NOT NULL);
            CREATE TABLE mock_host_model_decision(case_id TEXT PRIMARY KEY, event_id TEXT UNIQUE NOT NULL, binding TEXT NOT NULL, decision TEXT NOT NULL);
            CREATE TABLE mock_recorded_decision(case_id TEXT PRIMARY KEY, event_id TEXT UNIQUE NOT NULL, binding TEXT NOT NULL, decision TEXT NOT NULL);
        ''')
        db.execute('INSERT INTO identity VALUES (1, ?, ?)', (kit.name, wallet))
        db.execute('INSERT INTO sale(id, ticket, wallet, jwt, expected_wei, fee_wei, gas_cap_wei, status, payment, fee_payment, payer) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', (sale_id, 'private-rights-code', wallet, checkout, '987654321', '22', '12', 'paid', payment, fee_payment, payer))
        db.execute('INSERT INTO refund(sale_id, incoming, payer, wei, transfer_wei, fee_wei, gas_wei, fee_payment, reason, status, requested) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', (sale_id, payment, payer, '987654355', '987654321', '22', '12', fee_payment, 'paid_no_delivery', 'requested', requested))
        db.commit()
        original = {table: dict(db.execute('SELECT * FROM ' + table).fetchone()) for table in ('sale', 'refund')}
        snapshot = digest(b'r4/refund-ledger-snapshot/v1', original)
        assert run(prepare, kit)['status'] == 'evidence_unverified'
        assert run({**record, 'approved': True}, kit)['status'] == 'invalid_arguments'
        assert run({**record, 'ledger': original}, kit)['status'] == 'invalid_arguments'
        db.execute('INSERT INTO mock_host_proof VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', (case_id, snapshot, 'c' * 64, 'verified', 'verified', 'irreversible_seller_non_delivery_confirmed', '987654321', '22', '12'))
        db.commit()
        assert run(record, kit)['status'] == 'review_preparation_required'
        summary = run(prepare, kit)
        assert summary['status'] == 'ready_for_model_review' and summary['reason'] == 'paid_no_delivery'
        assert summary == run(prepare, kit)
        rendered = json.dumps(summary)
        assert all(secret not in rendered for secret in (wallet, payer, payment, sale_id, checkout, 'private-rights-code', '987654321'))
        assert run(record, kit)['status'] == 'model_decision_required'
        binding = db.execute('SELECT binding FROM mock_review_preparation WHERE case_id=?', (case_id,)).fetchone()[0]
        db.execute('INSERT INTO mock_host_model_decision VALUES (?, ?, ?, ?)', (case_id, 'd' * 64, 'e' * 64, 'approved'))
        db.commit()
        assert run(record, kit)['status'] == 'model_decision_unverified'
        db.execute('UPDATE mock_host_model_decision SET binding=?', (binding,))
        db.execute("UPDATE refund SET wei='987654356'")
        db.commit()
        assert run(record, kit)['status'] == 'evidence_unverified'
        assert db.execute('SELECT count(*) FROM mock_recorded_decision').fetchone()[0] == 0
        db.execute("UPDATE refund SET wei='987654355'")
        db.commit()
        expected = {'status': 'decision_recorded', 'case_id': case_id, 'decision': 'approved'}
        assert run(record, kit) == expected
        assert run(record, kit) == expected
        assert db.execute('SELECT count(*) FROM mock_recorded_decision').fetchone()[0] == 1
        assert original == {table: dict(db.execute('SELECT * FROM ' + table).fetchone()) for table in ('sale', 'refund')}
        db.execute("UPDATE mock_host_model_decision SET decision='declined'")
        db.commit()
        assert run(record, kit)['status'] == 'model_decision_conflict'
