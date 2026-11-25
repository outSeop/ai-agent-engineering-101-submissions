import hashlib
import json
import math
import re
import sqlite3
from contextlib import closing

DB = 'refund_binding_fixture.sqlite3'
WINDOW = 48 * 3600
HEX = re.compile(r'[0-9a-f]{64}')
ADDRESS = re.compile(r'0x[0-9a-fA-F]{40}')


class Hold(Exception):
    pass


def require(condition, status):
    if not condition:
        raise Hold(status)


def hash_data(domain, data):
    encoded = json.dumps(data, sort_keys=True, ensure_ascii=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(domain + b'\x00' + encoded.encode('ascii')).hexdigest()


def valid_time(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def wei(value):
    require(isinstance(value, str) and re.fullmatch(r'0|[1-9][0-9]{0,77}', value), 'refund_terms_unverified')
    number = int(value)
    require(number < 2**256, 'refund_terms_unverified')
    return number


def address(value):
    require(isinstance(value, str) and ADDRESS.fullmatch(value), 'shop_or_payer_unverified')
    return value.lower()


def load_case(db, case_id, kit):
    identities = db.execute('SELECT singleton, shop, wallet FROM identity LIMIT 2').fetchall()
    require(len(identities) == 1, 'shop_identity_unverified')
    identity = identities[0]
    seller = address(kit.address('shop'))
    require(identity['singleton'] == 1 and identity['shop'] == kit.name and address(identity['wallet']) == seller, 'shop_identity_unverified')
    matches = []
    rows = db.execute('SELECT s.id, s.jwt, r.requested FROM refund r JOIN sale s ON r.sale_id=s.id WHERE r.status=?', ('requested',))
    for row in rows:
        if isinstance(row['jwt'], str) and 0 < len(row['jwt']) <= 65536 and valid_time(row['requested']):
            candidate = hash_data(b'r4/refund-review/v1', [kit.name, row['id'], row['requested'], row['jwt']])
            if candidate == case_id:
                matches.append(row['id'])
    require(len(matches) == 1, 'requested_case_unavailable')
    sale_id = matches[0]
    sale = dict(db.execute('SELECT * FROM sale WHERE id=?', (sale_id,)).fetchone())
    refund = dict(db.execute('SELECT * FROM refund WHERE sale_id=?', (sale_id,)).fetchone())
    payer = address(sale['payer'])
    require(address(sale['wallet']) == seller and address(refund['payer']) == payer and payer != seller, 'shop_or_payer_unverified')
    incoming = sale['payment']
    require(isinstance(incoming, str) and re.fullmatch(r'0x[0-9a-fA-F]{64}', incoming) and incoming.lower() != '0x' + '0' * 64, 'original_payment_unverified')
    require(isinstance(refund['incoming'], str) and refund['incoming'].lower() == incoming.lower() and refund['outgoing'] in (None, ''), 'refund_state_unverified')
    for table, column in (('sale', 'payment'), ('refund', 'incoming')):
        count = db.execute(f'SELECT count(*) FROM {table} WHERE {column}=? COLLATE NOCASE', (incoming,)).fetchone()[0]
        require(count == 1, 'original_payment_ambiguous')
    return sale, refund


def verified_case(db, case_id, kit):
    sale, refund = load_case(db, case_id, kit)
    snapshot = hash_data(b'r4/refund-ledger-snapshot/v1', {'sale': sale, 'refund': refund})
    proof_row = db.execute('SELECT * FROM mock_host_proof WHERE case_id=?', (case_id,)).fetchone()
    require(proof_row is not None and proof_row['snapshot'] == snapshot, 'evidence_unverified')
    proof = dict(proof_row)
    require(HEX.fullmatch(proof['reference']) and proof['checkout'] == proof['transfers'] == 'verified', 'evidence_unverified')
    reason = refund['reason']
    if reason == 'early_market_breakage':
        settled, broken = sale['settled'], sale['broken']
        require(sale['status'] == 'settled' and valid_time(settled) and valid_time(broken) and 0 <= broken - settled <= WINDOW and proof['reason_evidence'] == 'market_breakage_confirmed', 'reason_unverified')
        period = 'within_48_hours'
    elif reason == 'paid_no_delivery':
        require(sale['status'] == 'paid' and proof['reason_evidence'] == 'irreversible_seller_non_delivery_confirmed', 'reason_unverified')
        period = 'not_applicable'
    else:
        raise Hold('reason_unverified')
    principal = wei(sale['expected_wei'])
    fee = wei(sale['fee_wei'])
    gas = wei(refund['gas_wei'])
    require(principal > 0 and principal == wei(refund['transfer_wei']) == wei(proof['principal_wei']) and fee == wei(refund['fee_wei']) == wei(proof['fee_wei']), 'refund_terms_unverified')
    require(gas == wei(proof['gas_wei']) <= wei(sale['gas_cap_wei']) and wei(refund['wei']) == principal + fee + gas, 'refund_terms_unverified')
    require(sale['fee_payment'] == refund['fee_payment'], 'refund_terms_unverified')
    binding = hash_data(b'r4/refund-review-binding/v1', {'case_id': case_id, 'snapshot': snapshot, 'proof': proof})
    return binding, {'case_id': case_id, 'reason': reason, 'period': period, 'evidence': {'checkout': 'verified', 'original_transfers': 'verified', 'refund_terms': 'verified', 'reason': proof['reason_evidence']}}


def run(args, kit):
    if not isinstance(args, dict) or set(args) != {'operation', 'case_id'} or args['operation'] not in ('prepare', 'record_decision') or not isinstance(args['case_id'], str) or not HEX.fullmatch(args['case_id']):
        return {'status': 'invalid_arguments'}
    if not kit.testing:
        return {'status': 'development_only'}
    case_id = args['case_id']
    try:
        with closing(sqlite3.connect('file:' + DB + '?mode=rw', uri=True, timeout=2)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute('BEGIN IMMEDIATE')
            require([tuple(row) for row in db.execute('PRAGMA quick_check(1)')] == [('ok',)], 'ledger_unverified')
            binding, summary = verified_case(db, case_id, kit)
            prepared = db.execute('SELECT binding FROM mock_review_preparation WHERE case_id=?', (case_id,)).fetchone()
            if args['operation'] == 'prepare':
                if prepared is None:
                    db.execute('INSERT INTO mock_review_preparation VALUES (?, ?)', (case_id, binding))
                else:
                    require(prepared['binding'] == binding, 'review_snapshot_changed')
                return {'status': 'ready_for_model_review', **summary}
            require(prepared is not None and prepared['binding'] == binding, 'review_preparation_required')
            event = db.execute('SELECT event_id, binding, decision FROM mock_host_model_decision WHERE case_id=?', (case_id,)).fetchone()
            require(event is not None, 'model_decision_required')
            require(event['binding'] == binding and isinstance(event['event_id'], str) and HEX.fullmatch(event['event_id']) and event['decision'] in ('approved', 'declined'), 'model_decision_unverified')
            decision = event['event_id'], binding, event['decision']
            recorded = db.execute('SELECT event_id, binding, decision FROM mock_recorded_decision WHERE case_id=?', (case_id,)).fetchone()
            if recorded is None:
                db.execute('INSERT INTO mock_recorded_decision VALUES (?, ?, ?, ?)', (case_id, *decision))
            else:
                require(tuple(recorded) == decision, 'model_decision_conflict')
            return {'status': 'decision_recorded', 'case_id': case_id, 'decision': event['decision']}
    except Hold as error:
        return {'status': error.args[0]}
    except (sqlite3.Error, TypeError, ValueError, KeyError, OverflowError):
        return {'status': 'ledger_unverified'}
