"""Offline candidate for the existing trusted benefits database.

The approved operator installs state/r4-benefits/first-purchase-bonus-policy.json
before rollout. Its exact keys are enabled, id, start, end, lifetime_budget.
The runtime requires a trusted working directory and runtime-owned protected
state directories and policy file. Invalid policy and detectable file races
disable eligibility. The filesystem write boundary establishes policy origin.
The policy ID is descriptive. Awards and lifetime budget are global.

The database and SQLite sidecars belong inside the trusted local write boundary.
Only the existing finalize_sale writes settlement fields and appends the matching
settled_and_earned event after checking the RPC product and fee payer and ledger.
Transaction hash syntax is a consistency check. Receipt fields alone cannot
prove RPC authenticity. The internal worker submits committed sale IDs in event
rowid order. Historical verified settlements, including later refunds, count as
first purchases without backfill. The existing refund path revokes and accounts
for the full lot. Award records are immutable and refunds consume budget forever.
"""

import json
import math
import os
import re
import sqlite3
import stat
import time
from pathlib import Path

STATE = Path('state/r4-benefits')
POLICY = 'first-purchase-bonus-policy.json'
DATABASE = STATE / 'benefits.sqlite3'
DB_URI = 'file:state/r4-benefits/benefits.sqlite3?mode=rw'
LOT_SECONDS = 604800
MAX_EPOCH = 253402300799 - LOT_SECONDS
MAX_POLICY_BYTES = 4096
WALLET = re.compile(r'0x[0-9a-fA-F]{40}', re.ASCII)
TX_HASH = re.compile(r'0x[0-9a-fA-F]{64}', re.ASCII)
AWARD_SCHEMA = '''CREATE TABLE welcome_award (
    payer TEXT NOT NULL PRIMARY KEY CHECK (payer = lower(payer)),
    sale_id TEXT NOT NULL UNIQUE,
    amount INTEGER NOT NULL CHECK (typeof(amount) = 'integer' AND amount BETWEEN 1 AND 5000),
    granted_at INTEGER NOT NULL,
    earned_event_id NOT NULL
)'''


def _now():
    return time.time()


def _epoch(value):
    return type(value) in (int, float) and 0 <= value <= MAX_EPOCH and math.isfinite(value)


def _nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def _owned_protected(info, uid):
    return info.st_uid == uid and not (info.st_mode & 0o022)


def _file_stamp(info):
    return (info.st_dev, info.st_ino, info.st_uid, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _policy_bytes():
    uid = os.geteuid()
    dir_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory = os.open('.', dir_flags)
    try:
        if not _owned_protected(os.fstat(directory), uid):
            return None
        for part in STATE.parts:
            child = os.open(part, dir_flags, dir_fd=directory)
            os.close(directory)
            directory = child
            if not _owned_protected(os.fstat(directory), uid):
                return None
        fd = os.open(POLICY, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            before = os.fstat(fd)
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                    or not _owned_protected(before, uid) or before.st_size > MAX_POLICY_BYTES):
                return None
            with os.fdopen(fd, 'rb', closefd=False) as source:
                raw = source.read(MAX_POLICY_BYTES + 1)
            after = os.fstat(fd)
            current = os.stat(POLICY, dir_fd=directory, follow_symlinks=False)
            if (len(raw) != before.st_size or len(raw) > MAX_POLICY_BYTES
                    or _file_stamp(before) != _file_stamp(after)
                    or _file_stamp(after) != _file_stamp(current)):
                return None
            return raw
        finally:
            os.close(fd)
    finally:
        os.close(directory)


def _policy():
    try:
        raw = _policy_bytes()
        if raw is None:
            return None
        policy = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_keys)
    except (AttributeError, NotImplementedError, OSError, ValueError, RecursionError):
        return None
    if (type(policy) is not dict
            or policy.keys() != {'enabled', 'id', 'start', 'end', 'lifetime_budget'}
            or policy['enabled'] is not True or not _nonempty(policy['id'])):
        return None
    start, end, budget = (policy[key] for key in ('start', 'end', 'lifetime_budget'))
    if (not _epoch(start) or not _epoch(end) or not 0 < end - start <= 72 * 3600
            or type(budget) is not int or not 1 <= budget <= 50000):
        return None
    return policy


def _evidence(sale, now):
    payer = sale['payer']
    payment = sale['payment']
    settled = sale['settled']
    if (sale['event_id'] is None or sale['status'] not in ('settled', 'refunded')
            or not all(_nonempty(sale[key]) for key in ('sale_id', 'owner', 'market_order'))
            or not isinstance(payment, str) or TX_HASH.fullmatch(payment) is None
            or not isinstance(payer, str) or WALLET.fullmatch(payer) is None
            or payer.lower() == '0x' + '0' * 40
            or type(sale['base']) is not int or sale['base'] < 0
            or not _epoch(settled) or not 0 < settled <= now):
        return None
    try:
        details = json.loads(sale['details'], object_pairs_hook=_unique_keys)
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


def _lot_mode(db, sale, expires):
    lot = db.execute('SELECT owner, amount, expires, revoked FROM lot WHERE sale_id = ?',
                     (sale['sale_id'],)).fetchone()
    basic = sale['base'] // 100
    if lot is None:
        return 'insert' if basic == 0 else None
    recorded = lot['expires']
    if (lot['owner'] == sale['owner'] and type(lot['amount']) is int and lot['amount'] == basic
            and type(recorded) in (int, float) and recorded == expires and lot['revoked'] is None):
        return 'update'
    return None


def _apply(db, sale_id, policy, now):
    schema = _award_schema(db)
    if schema == 'incompatible':
        return {'status': 'incompatible'}
    awarded_payers, awarded_sales, spent = set(), set(), 0
    if schema == 'ready':
        for row in db.execute('SELECT payer, sale_id FROM welcome_award'):
            awarded_payers.add(row['payer'])
            awarded_sales.add(row['sale_id'])
        spent = db.execute('SELECT COALESCE(SUM(amount), 0) FROM welcome_award').fetchone()[0]
    if sale_id in awarded_sales:
        return {'status': 'already_awarded'}
    target = db.execute('SELECT rowid FROM event WHERE kind = ? AND reference = ? LIMIT 2',
                        ('settled_and_earned', sale_id)).fetchall()
    if len(target) != 1:
        return {'status': 'ineligible'}
    events = db.execute('''
        SELECT s.id AS sale_id, s.owner, s.base, s.status, s.payer, s.payment,
               s.market_order, s.settled, e.id AS event_id, e.details,
               (SELECT COUNT(*) FROM event AS other
                 WHERE other.kind = e.kind AND other.reference = e.reference) AS evidence_count
          FROM event AS e JOIN sale AS s ON s.id = e.reference
         WHERE e.kind = 'settled_and_earned' AND e.rowid <= ?
         ORDER BY e.rowid
    ''', (target[0][0],))
    seen = set()
    for sale in events:
        current = sale['sale_id'] == sale_id
        payer = _evidence(sale, now)
        if payer is None:
            if current:
                return {'status': 'ineligible'}
            continue
        if sale['evidence_count'] != 1:
            return {'status': 'ineligible'}
        first = payer not in seen
        seen.add(payer)
        if payer in awarded_payers:
            if current:
                return {'status': 'already_awarded'}
            continue
        settled = sale['settled']
        expires = settled + LOT_SECONDS
        amount = min(5000, sale['base'] * 500 // 10000)
        if (not first or sale['status'] != 'settled' or sale['sale_id'] in awarded_sales
                or not policy['start'] <= settled < policy['end'] or now >= expires or amount == 0):
            if current:
                return {'status': 'ineligible'}
            continue
        mode = _lot_mode(db, sale, expires)
        if mode is None:
            if current:
                return {'status': 'ineligible'}
            continue
        if amount > policy['lifetime_budget'] - spent:
            if current:
                return {'status': 'budget_exhausted'}
            continue
        if not current:
            return {'status': 'defer'}
        if schema == 'absent':
            db.execute(AWARD_SCHEMA)
        if mode == 'insert':
            db.execute('INSERT INTO lot (sale_id, owner, amount, expires, revoked) VALUES (?, ?, ?, ?, NULL)',
                       (sale_id, sale['owner'], amount, expires))
        else:
            db.execute('UPDATE lot SET amount = amount + ? WHERE sale_id = ?', (amount, sale_id))
        db.execute('INSERT INTO welcome_award (payer, sale_id, amount, granted_at, earned_event_id) VALUES (?, ?, ?, ?, ?)',
                   (payer, sale_id, amount, int(now), sale['event_id']))
        return {'status': 'granted', 'credits': amount}
    return {'status': 'ineligible'}


def run(args, kit):
    if type(args) is not dict or set(args) - {'sale_id'}:
        return {'status': 'invalid_args'}
    if 'sale_id' in args and not _nonempty(args['sale_id']):
        return {'status': 'invalid_args'}
    policy = _policy()
    if policy is None:
        return {'status': 'inactive'}
    if 'sale_id' not in args:
        return {'status': 'idle'}
    try:
        info = DATABASE.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not _owned_protected(info, os.geteuid()):
            return {'status': 'unavailable'}
        db = sqlite3.connect(DB_URI, uri=True, isolation_level=None, timeout=5)
        try:
            db.row_factory = sqlite3.Row
            db.execute('BEGIN IMMEDIATE')
            now = _now()
            if not _epoch(now) or not now:
                db.rollback()
                return {'status': 'unavailable'}
            result = _apply(db, args['sale_id'], policy, now)
            if result['status'] == 'granted':
                db.commit()
            else:
                db.rollback()
            return result
        finally:
            db.close()
    except (OSError, sqlite3.Error, OverflowError, UnicodeError):
        return {'status': 'unavailable'}
