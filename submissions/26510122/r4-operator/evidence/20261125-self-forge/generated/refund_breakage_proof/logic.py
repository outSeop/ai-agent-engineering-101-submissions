import hashlib
import json
import math
import re
import sqlite3
from contextlib import closing
from urllib.parse import urlsplit

import httpx

FIXTURE = 'refund_breakage_fixture_v2.sqlite3'
LEDGER = 'https://market.ourolabs.ai/api/ledger'
WINDOW = 48 * 3600
PAGE_BUDGET = 12
MAX_SEQ = 2**63 - 1


class Hold(Exception):
    pass


def require(condition, status):
    if not condition:
        raise Hold(status)


def address(value):
    require(isinstance(value, str) and re.fullmatch(r'0x[0-9a-fA-F]{40}', value) and int(value, 16), 'shop_identity_unverified')
    return value.lower()


def finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def timestamp(value):
    return finite_number(value) and value > 0


def digest(domain, fields):
    payload = json.dumps(fields, ensure_ascii=True, separators=(',', ':')).encode('ascii')
    return hashlib.sha256(domain + b'\x00' + payload).hexdigest()


def load_case(case_id, kit):
    seller = address(kit.address('shop'))
    with closing(sqlite3.connect('file:' + FIXTURE + '?mode=ro', uri=True, timeout=2)) as db:
        db.row_factory = sqlite3.Row
        db.execute('BEGIN')
        require([tuple(row) for row in db.execute('PRAGMA quick_check(1)')] == [('ok',)], 'ledger_unverified')
        identities = db.execute('SELECT singleton, shop, wallet FROM identity LIMIT 2').fetchall()
        require(len(identities) == 1, 'shop_identity_unverified')
        identity = identities[0]
        require(identity['singleton'] == 1 and identity['shop'] == kit.name and address(identity['wallet']) == seller, 'shop_identity_unverified')
        matches = []
        rows = db.execute('''
            SELECT s.id, s.wallet, s.jwt, s.unit, s.market_order, s.shop_url,
                   s.status, s.settled, s.broken, r.reason, r.requested
            FROM refund r JOIN sale s ON s.id=r.sale_id
            WHERE r.status='requested'
        ''')
        for row in rows:
            if not timestamp(row['requested']) or not isinstance(row['jwt'], str) or not 0 < len(row['jwt']) <= 65536:
                continue
            candidate = digest(b'r4/refund-review/v1', [kit.name, row['id'], row['requested'], row['jwt']])
            if candidate == case_id:
                matches.append(row)
        require(len(matches) == 1, 'requested_case_unavailable')
        sale = matches[0]
        require(address(sale['wallet']) == seller, 'shop_identity_unverified')
        require(sale['reason'] == 'early_market_breakage', 'different_reason_path_required')
        require(sale['status'] == 'settled' and timestamp(sale['settled']) and timestamp(sale['broken']), 'local_breakage_unverified')
        require(0 <= sale['broken'] - sale['settled'] <= WINDOW, 'local_breakage_unverified')
        order, unit, shop_url = sale['market_order'], sale['unit'], sale['shop_url']
        require(all(isinstance(value, str) and value for value in (order, unit, shop_url)), 'market_order_unverified')
        try:
            parsed = urlsplit(shop_url)
            valid_url = parsed.scheme in ('http', 'https') and parsed.hostname and parsed.username is None and parsed.password is None
        except ValueError:
            valid_url = False
        require(valid_url, 'market_order_unverified')
        linked = db.execute('SELECT id FROM sale WHERE market_order=? LIMIT 2', (order,)).fetchall()
        require([row['id'] for row in linked] == [sale['id']], 'market_order_unverified')
        binding = digest(b'r4/breakage-scan/v2', [seller, order, unit, shop_url, sale['settled'], sale['broken']])
        progress = db.execute('SELECT after_seq FROM scan_progress WHERE case_id=? AND binding=?', (case_id, binding)).fetchone()
        return shop_url, order, unit, binding, progress['after_seq'] if progress else 0


def checkpoint(case_id, binding, after):
    with closing(sqlite3.connect('file:' + FIXTURE + '?mode=rw', uri=True, timeout=2)) as db, db:
        db.execute('''
            INSERT INTO scan_progress (case_id, binding, after_seq) VALUES (?, ?, ?)
            ON CONFLICT(case_id, binding) DO UPDATE SET after_seq=excluded.after_seq
            WHERE excluded.after_seq > scan_progress.after_seq
        ''', (case_id, binding, after))


def inspect_page(rows, after, shop_url, order, unit):
    require(isinstance(rows, list), 'market_evidence_unavailable')
    confirmed = False
    for entry in rows:
        require(isinstance(entry, dict) and type(entry.get('seq')) is int and after < entry['seq'] <= MAX_SEQ and isinstance(entry.get('data'), dict), 'market_evidence_unavailable')
        after = entry['seq']
        data = entry['data']
        if entry.get('kind') != 'broken' or data.get('shop') != shop_url or data.get('order') != order:
            continue
        hours = data.get('hours_after_sale')
        require(finite_number(hours) and 0 <= hours <= 48, 'market_breakage_unverified')
        require('unit' not in data or data['unit'] == unit, 'market_breakage_unverified')
        confirmed = True
    return after, confirmed


def run(args, kit):
    if not isinstance(args, dict) or set(args) != {'case_id'} or not isinstance(args['case_id'], str) or re.fullmatch(r'[0-9a-f]{64}', args['case_id']) is None:
        return {'status': 'invalid_arguments'}
    if not kit.testing:
        return {'status': 'development_only'}
    case_id = args['case_id']
    try:
        shop_url, order, unit, binding, after = load_case(case_id, kit)
        require(type(after) is int and 0 <= after <= MAX_SEQ, 'ledger_unverified')
        for _ in range(PAGE_BUDGET):
            response = httpx.get(LEDGER, params={'after': after}, timeout=2)
            response.raise_for_status()
            rows = response.json()
            next_after, confirmed = inspect_page(rows, after, shop_url, order, unit)
            if confirmed:
                return {'status': 'market_breakage_confirmed', 'case_id': case_id, 'reason': 'early_market_breakage', 'period': 'within_48_hours'}
            if not rows:
                return {'status': 'market_breakage_unverified'}
            checkpoint(case_id, binding, next_after)
            after = next_after
        return {'status': 'pagination_incomplete'}
    except Hold as error:
        return {'status': error.args[0]}
    except sqlite3.Error:
        return {'status': 'ledger_unverified'}
    except (httpx.HTTPError, ValueError, OverflowError):
        return {'status': 'market_evidence_unavailable'}
