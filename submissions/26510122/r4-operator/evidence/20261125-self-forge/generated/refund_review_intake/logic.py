import hashlib
import json
import math
import re
import sqlite3
from contextlib import closing

DB = 'state/r4-benefits/benefits.sqlite3'
FIXTURE = 'refund_review_fixture.sqlite3'
WINDOW = 48 * 3600


def valid_time(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def address(value):
    if not isinstance(value, str) or re.fullmatch(r'0x[0-9a-fA-F]{40}', value) is None:
        raise ValueError('invalid shop wallet')
    return value.lower()


def case_summary(row, shop):
    if not isinstance(row['id'], str) or not row['id'] or not valid_time(row['requested']):
        raise ValueError('invalid request identity')
    jwt = row['jwt']
    if not isinstance(jwt, str) or not 0 < len(jwt) <= 65536:
        raise ValueError('missing checkout reference')
    # This reference lets the review loop refer to a case. It grants no authority.
    binding = json.dumps([shop, row['id'], row['requested'], jwt], ensure_ascii=True, separators=(',', ':'))
    case_id = hashlib.sha256(b'r4/refund-review/v1\x00' + binding.encode('ascii')).hexdigest()
    reason = row['reason']
    period = 'unverified'
    reason_evidence = 'unsupported_reason'
    if reason == 'early_market_breakage':
        reason_evidence = 'local_state_unverified'
        if row['sale_status'] == 'settled' and valid_time(row['settled']) and valid_time(row['broken']):
            elapsed = row['broken'] - row['settled']
            if 0 <= elapsed <= WINDOW:
                period = 'within_48_hours'
                reason_evidence = 'awaiting_market_breakage_confirmation'
            else:
                period = 'outside_48_hours' if elapsed > WINDOW else 'invalid_event_order'
                reason_evidence = 'local_timing_mismatch'
    elif reason == 'paid_no_delivery':
        period = 'not_applicable'
        reason_evidence = 'awaiting_removal_inventory_and_ledger' if row['sale_status'] == 'paid' else 'local_state_unverified'
    else:
        reason = 'unsupported'
    return {
        'case_id': case_id,
        'reason': reason,
        'period': period,
        'evidence': {'reason': reason_evidence, 'checkout': 'unverified', 'original_transfers': 'unverified'},
        'approval_ready': False,
    }


def read_cases(path, shop, wallet):
    with closing(sqlite3.connect('file:' + path + '?mode=ro', uri=True, timeout=2)) as db:
        db.row_factory = sqlite3.Row
        db.execute('BEGIN')
        if [tuple(row) for row in db.execute('PRAGMA quick_check(1)')] != [('ok',)]:
            raise ValueError('ledger integrity check failed')
        identities = db.execute('SELECT singleton, shop, wallet FROM identity LIMIT 2').fetchall()
        if len(identities) != 1:
            raise ValueError('shop identity unavailable')
        identity = identities[0]
        if identity['singleton'] != 1 or identity['shop'] != shop or address(identity['wallet']) != wallet:
            raise ValueError('shop identity mismatch')
        rows = db.execute('''
            SELECT s.id, s.wallet, s.jwt, s.status AS sale_status, s.settled, s.broken,
                   r.reason, r.requested
            FROM refund AS r LEFT JOIN sale AS s ON s.id = r.sale_id
            WHERE r.status = 'requested'
            ORDER BY r.requested, r.sale_id
        ''')
        cases = []
        for row in rows:
            if address(row['wallet']) != wallet:
                raise ValueError('sale wallet mismatch')
            cases.append(case_summary(row, shop))
        return cases


def run(args, kit):
    if args != {}:
        return {'status': 'invalid_arguments'}
    if not kit.testing:
        return {'status': 'development_only'}
    try:
        return {'status': 'review_intake', 'cases': read_cases(FIXTURE, kit.name, address(kit.address('shop')))}
    except (sqlite3.Error, ValueError, OverflowError):
        return {'status': 'ledger_unverified'}
