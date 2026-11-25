"""Background-only candidate for an existing benefits database.

Before installation, set ROLLOUT_EPOCH to the operator-approved Unix second.
Invoke with the internal sale ID after trusted finalize_sale commits. Leave
pre-epoch sales untouched while including their settled history in eligibility.

The fixed database and its parent directory must be controlled by the trusted
worker. Only verified finalize_sale may write settlement fields and append the
corresponding settled_and_earned event. The original finalizer verifies the
product and fee payer through RPC and checks the ledger before recording it.
This candidate checks the consistency of that committed evidence. Receipt field
strings alone cannot prove RPC authenticity. Customer and model inputs convey
no authority. Refunds retain the settlement evidence and grant row, and the
existing refund transaction revokes and accounts for the whole linked lot.

An existing lot with base entitlement zero is supported. A missing lot is
ineligible even when the base entitlement would be zero. A zero bonus consumes
the campaign with a zero-credit ledger row and leaves the lot unchanged.
"""

import json
import re
import sqlite3
import time

DB_URI = 'file:state/r4-benefits/benefits.sqlite3?mode=rw'
ROLLOUT_EPOCH = None
CAMPAIGN = 'first_purchase_bonus_v1'
LOT_SECONDS = 604800
SQLITE_MAX_INT = 2**63 - 1
WALLET = re.compile(r'0x[0-9a-f]{40}', re.ASCII | re.IGNORECASE)


def _now():
    return int(time.time())


def _nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def _settlement_event(db, sale):
    if not (_nonempty(sale['owner']) and _nonempty(sale['payment'])
            and _nonempty(sale['market_order']) and type(sale['base']) is int
            and sale['base'] >= 0 and type(sale['settled']) is int
            and sale['settled'] > 0):
        return None
    rows = db.execute(
        'SELECT rowid AS event_sequence, id, details FROM event '
        'WHERE kind = ? AND reference = ? LIMIT 2',
        ('settled_and_earned', sale['id']),
    ).fetchall()
    if len(rows) != 1 or rows[0]['id'] is None:
        return None
    try:
        details = json.loads(rows[0]['details'])
    except (ValueError, TypeError, RecursionError):
        return None
    if (not isinstance(details, dict) or details.get('order') != sale['market_order']
            or type(details.get('earned')) is not int
            or details['earned'] != sale['base'] // 100):
        return None
    return rows[0]


def run(args, kit):
    if not isinstance(args, dict):
        return {'status': 'invalid_args'}
    if not args:
        return {'status': 'no_sale_id'}
    if set(args) != {'sale_id'} or not _nonempty(args['sale_id']):
        return {'status': 'invalid_args'}
    sale_id = args['sale_id']
    try:
        sale_id.encode('utf-8')
    except UnicodeError:
        return {'status': 'invalid_args'}
    if type(ROLLOUT_EPOCH) is not int or ROLLOUT_EPOCH <= 0:
        return {'status': 'rollout_disabled'}

    db = None
    try:
        db = sqlite3.connect(DB_URI, uri=True, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('BEGIN IMMEDIATE')
        now = _now()
        sale = db.execute('SELECT * FROM sale WHERE id = ?', (sale_id,)).fetchone()
        if sale is None or sale['status'] != 'settled':
            return {'status': 'ineligible_sale'}
        payer = sale['payer']
        event = _settlement_event(db, sale)
        if event is None or not isinstance(payer, str) or WALLET.fullmatch(payer) is None:
            return {'status': 'unverified_settlement'}
        payer = payer.lower()
        settled = sale['settled']
        if settled < ROLLOUT_EPOCH:
            return {'status': 'before_rollout'}
        if settled > now:
            return {'status': 'unverified_settlement'}
        expires = settled + LOT_SECONDS
        if expires > SQLITE_MAX_INT:
            return {'status': 'unverified_settlement'}
        if expires <= now:
            return {'status': 'expired'}

        # The append-only event rowid orders commits with equal settled seconds.
        earlier_or_tied = db.execute(
            'SELECT * FROM sale WHERE lower(payer) = ? AND id <> ? '
            'AND status IN (?, ?) AND settled IS NOT NULL AND settled <= ?',
            (payer, sale_id, 'settled', 'refunded', settled),
        )
        for previous in earlier_or_tied:
            previous_event = _settlement_event(db, previous)
            if previous_event is None:
                return {'status': 'inconsistent_history'}
            if (previous['settled'], previous_event['event_sequence']) < (settled, event['event_sequence']):
                return {'status': 'returning_payer'}

        db.execute('''CREATE TABLE IF NOT EXISTS first_purchase_bonus_grant (
            payer TEXT NOT NULL CHECK (payer = lower(payer)),
            campaign TEXT NOT NULL,
            sale_id TEXT NOT NULL UNIQUE,
            amount INTEGER NOT NULL CHECK (amount >= 0),
            granted_at INTEGER NOT NULL,
            earned_event_id NOT NULL,
            PRIMARY KEY (payer, campaign)
        )''')
        existing = db.execute(
            'SELECT 1 FROM first_purchase_bonus_grant '
            'WHERE (payer = ? AND campaign = ?) OR sale_id = ?',
            (payer, CAMPAIGN, sale_id),
        ).fetchone()
        if existing is not None:
            return {'status': 'already_granted'}

        lot = db.execute('SELECT * FROM lot WHERE sale_id = ?', (sale_id,)).fetchone()
        base_earned = sale['base'] // 100
        if (lot is None or lot['owner'] != sale['owner'] or lot['revoked'] is not None
                or type(lot['amount']) is not int or lot['amount'] != base_earned
                or type(lot['expires']) is not int or lot['expires'] != expires):
            return {'status': 'ineligible_lot'}
        bonus = sale['base'] * 5 // 100
        db.execute(
            'INSERT INTO first_purchase_bonus_grant '
            '(payer, campaign, sale_id, amount, granted_at, earned_event_id) VALUES (?, ?, ?, ?, ?, ?)',
            (payer, CAMPAIGN, sale_id, bonus, now, event['id']),
        )
        if bonus:
            updated = db.execute('UPDATE lot SET amount = ? WHERE sale_id = ?', (base_earned + bonus, sale_id))
            if updated.rowcount != 1:
                raise sqlite3.IntegrityError('Expected one lot update')
        db.commit()
        return {'status': 'granted', 'bonus': bonus}
    except (sqlite3.Error, KeyError, IndexError):
        return {'status': 'storage_error'}
    finally:
        if db is not None:
            try:
                if db.in_transaction:
                    db.rollback()
            finally:
                db.close()
