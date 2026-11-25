"""Offline candidate for the existing trusted benefits database.

The future operator provisionally enables it by installing the fixed policy
file in the protected state directory with enabled=true, a nonblank id, integer
UTC Unix seconds start/end, and integer lifetime_budget in 1..50000. Keep the
state directory and policy writable only by the approved operator and trusted
local writers as applicable. Malformed, duplicate-key, unexpected, disabled,
or missing policy is inactive. An unauthorized edit that still encodes a valid
policy is indistinguishable in-process from an authorized edit. Authenticity
of the policy therefore depends on the operator's filesystem write boundary.
The id is descriptive and changing it does not reset the ledger or budget.

Only the existing verified finalize_sale may write committed settlement fields
and append settled_and_earned events. It verifies the same product and fee
payer via RPC and checks the ledger before writing. Receipt strings alone
cannot prove RPC authenticity. The worker calls this candidate with only the
internal sale ID, after commit, in ascending append-only event rowid order.
Historical settled evidence counts, including later refunds, without backfill.
Refund processing revokes/accounts for the full lot and preserves award rows.
Never delete award rows or allow other writers to edit them.
"""

import json
import re
import sqlite3
import time
from pathlib import Path

POLICY_PATH = Path('state/r4-benefits/first-purchase-bonus-policy.json')
DB_URI = 'file:state/r4-benefits/benefits.sqlite3?mode=rw'
LOT_SECONDS = 604800
MAX_EPOCH = 2**63 - 1 - LOT_SECONDS
WALLET = re.compile(r'0x[0-9a-f]{40}', re.ASCII | re.IGNORECASE)
AWARD_SCHEMA = '''CREATE TABLE welcome_award (
    payer TEXT NOT NULL PRIMARY KEY CHECK (payer = lower(payer)),
    sale_id TEXT NOT NULL UNIQUE,
    amount INTEGER NOT NULL CHECK (typeof(amount) = 'integer' AND amount BETWEEN 1 AND 5000),
    granted_at INTEGER NOT NULL,
    earned_event_id NOT NULL
)'''


def _now():
    return int(time.time())


def _nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def _policy():
    try:
        if POLICY_PATH.is_symlink():
            return None
        with POLICY_PATH.open('rb') as source:
            raw = source.read(4097)
        if len(raw) > 4096:
            return None
        policy = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_keys)
    except (OSError, ValueError, RecursionError):
        return None
    if (type(policy) is not dict
            or policy.keys() != {'enabled', 'id', 'start', 'end', 'lifetime_budget'}
            or policy['enabled'] is not True or not _nonempty(policy['id'])):
        return None
    start, end, budget = (policy[key] for key in ('start', 'end', 'lifetime_budget'))
    if (any(type(value) is not int for value in (start, end, budget))
            or not 0 <= start < end <= MAX_EPOCH or end - start > 72 * 3600
            or not 1 <= budget <= 50000):
        return None
    return policy


def _evidence(sale, event, now):
    payer = sale['payer']
    if (event is None or event['event_id'] is None
            or sale['status'] not in ('settled', 'refunded')
            or not all(_nonempty(sale[key]) for key in ('owner', 'market_order', 'payment'))
            or not isinstance(payer, str) or WALLET.fullmatch(payer) is None
            or payer.lower() == '0x' + '0' * 40
            or type(sale['base']) is not int or sale['base'] < 0
            or type(sale['settled']) is not int or not 0 < sale['settled'] <= min(now, MAX_EPOCH)):
        return None
    try:
        details = json.loads(event['details'], object_pairs_hook=_unique_keys)
    except (ValueError, TypeError, RecursionError):
        return None
    if (type(details) is not dict or details.keys() != {'order', 'earned'}
            or details['order'] != sale['market_order']
            or type(details['earned']) is not int or details['earned'] != sale['base'] // 100):
        return None
    return payer.lower()


def _award_schema(db):
    rows = db.execute(
        'SELECT name, type, sql FROM sqlite_master WHERE lower(name) IN (?, ?)',
        ('welcome_award', 'first_purchase_bonus_grant'),
    ).fetchall()
    if not rows:
        return 'absent'
    if len(rows) == 1 and tuple(rows[0]) == ('welcome_award', 'table', AWARD_SCHEMA):
        return 'ready'
    return 'incompatible'


def _existing_awards(db):
    rows = db.execute('SELECT payer, sale_id FROM welcome_award').fetchall()
    spent = db.execute('SELECT COALESCE(SUM(amount), 0) FROM welcome_award').fetchone()[0]
    return {row['payer'] for row in rows}, {row['sale_id'] for row in rows}, spent


def _lot(db, sale, expires):
    lot = db.execute('SELECT owner, amount, expires, revoked FROM lot WHERE sale_id = ?',
                     (sale['id'],)).fetchone()
    basic = sale['base'] // 100
    if lot is None:
        return 'insert' if basic == 0 else None
    if (lot['owner'] == sale['owner'] and type(lot['amount']) is int
            and lot['amount'] == basic and type(lot['expires']) is int
            and lot['expires'] == expires and lot['revoked'] is None):
        return 'update'
    return None


def _candidate(db, sale, policy, now):
    if sale['status'] != 'settled':
        return 'ineligible_sale', 0, None
    settled = sale['settled']
    if not policy['start'] <= settled < policy['end']:
        return 'outside_rollout', 0, None
    expires = settled + LOT_SECONDS
    if expires <= now:
        return 'expired', 0, None
    amount = min(5000, sale['base'] * 500 // 10000)
    if amount == 0:
        return 'zero_bonus', 0, None
    mode = _lot(db, sale, expires)
    return ('eligible', amount, mode) if mode else ('ineligible_lot', 0, None)


def _settlements_through(db, sequence):
    return db.execute('''SELECT s.id, s.owner, s.base, s.status, s.payer, s.payment,
                                s.market_order, s.settled, e.id AS event_id,
                                e.details, e.rowid AS seq
                         FROM event AS e JOIN sale AS s ON s.id = e.reference
                         WHERE e.kind = 'settled_and_earned' AND e.rowid <= ?
                           AND (SELECT COUNT(*) FROM event AS other
                                WHERE other.kind = 'settled_and_earned'
                                  AND other.reference = e.reference) = 1
                         ORDER BY e.rowid''', (sequence,))


def _decide(db, sale_id, policy, now, schema):
    sale = db.execute('SELECT * FROM sale WHERE id = ?', (sale_id,)).fetchone()
    if sale is None or sale['status'] != 'settled':
        return {'status': 'ineligible_sale'}
    events = db.execute('''SELECT rowid AS seq, id AS event_id, details FROM event
                           WHERE kind = 'settled_and_earned' AND reference = ? LIMIT 2''',
                        (sale_id,)).fetchall()
    event = events[0] if len(events) == 1 else None
    payer = _evidence(sale, event, now)
    if payer is None:
        return {'status': 'unverified_settlement'}

    awarded, used_sales, spent = _existing_awards(db) if schema == 'ready' else (set(), set(), 0)
    if payer in awarded or sale_id in used_sales:
        return {'status': 'already_awarded'}
    same_payer_history = {row['id'] for row in db.execute(
        "SELECT id FROM sale WHERE lower(payer) = ? AND id <> ? "
        "AND status IN ('settled', 'refunded') AND settled IS NOT NULL",
        (payer, sale_id),
    )}
    available = policy['lifetime_budget'] - spent
    status, amount, mode = _candidate(db, sale, policy, now)
    if status != 'eligible':
        return {'status': status}
    seen = set()
    pending = False
    for earlier in _settlements_through(db, event['seq'] - 1):
        earlier_payer = _evidence(earlier, earlier, now)
        if earlier_payer is None or earlier_payer in seen:
            continue
        if earlier_payer == payer:
            return {'status': 'returning_payer'}
        seen.add(earlier_payer)
        if earlier_payer not in awarded and earlier['id'] not in used_sales:
            earlier_status, earlier_amount, _ = _candidate(db, earlier, policy, now)
            if earlier_status == 'eligible' and earlier_amount <= available:
                pending = True

    # Missing or ambiguous evidence for a same-payer settled record can hide
    # a prior purchase. A uniquely verified event after the target is harmless.
    for later_id in same_payer_history:
        later = db.execute('SELECT * FROM sale WHERE id = ?', (later_id,)).fetchone()
        matches = db.execute('''SELECT rowid AS seq, id AS event_id, details FROM event
                                WHERE kind = 'settled_and_earned' AND reference = ? LIMIT 2''',
                             (later_id,)).fetchall()
        if (len(matches) != 1 or matches[0]['seq'] <= event['seq']
                or _evidence(later, matches[0], now) != payer):
            return {'status': 'inconsistent_history'}
    if pending:
        return {'status': 'deferred'}
    if amount > available:
        return {'status': 'insufficient_budget'}
    if _policy() != policy:
        return {'status': 'inactive'}
    if schema == 'absent':
        db.execute(AWARD_SCHEMA)
    if mode == 'insert':
        db.execute('INSERT INTO lot (sale_id, owner, amount, expires, revoked) VALUES (?, ?, ?, ?, NULL)',
                   (sale_id, sale['owner'], amount, sale['settled'] + LOT_SECONDS))
    else:
        db.execute('UPDATE lot SET amount = amount + ? WHERE sale_id = ?', (amount, sale_id))
    db.execute('INSERT INTO welcome_award (payer, sale_id, amount, granted_at, earned_event_id) VALUES (?, ?, ?, ?, ?)',
               (payer, sale_id, amount, now, event['event_id']))
    db.commit()
    return {'status': 'awarded', 'credits': amount}


def run(args, kit):
    if type(args) is not dict:
        return {'status': 'invalid_args'}
    if not args:
        return {'status': 'no_sale_id'}
    if args.keys() != {'sale_id'} or not _nonempty(args['sale_id']):
        return {'status': 'invalid_args'}
    sale_id = args['sale_id']
    try:
        sale_id.encode('utf-8')
    except UnicodeError:
        return {'status': 'invalid_args'}
    policy = _policy()
    if policy is None:
        return {'status': 'inactive'}
    db = None
    try:
        db = sqlite3.connect(DB_URI, uri=True, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('BEGIN IMMEDIATE')
        schema = _award_schema(db)
        if schema == 'incompatible':
            return {'status': 'incompatible_ledger'}
        return _decide(db, sale_id, policy, _now(), schema)
    except (sqlite3.Error, OverflowError, IndexError, UnicodeError):
        return {'status': 'state_error'}
    finally:
        if db is not None:
            db.close()
