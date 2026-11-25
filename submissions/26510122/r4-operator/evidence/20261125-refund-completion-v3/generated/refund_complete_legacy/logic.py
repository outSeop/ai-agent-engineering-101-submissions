import hashlib
import json
import math
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path

ROOT = Path('state/r4-benefits')
LEDGER = ROOT / 'benefits.sqlite3'
PROOFS = ROOT / 'refund-confirmations.sqlite3'
HASH = re.compile(r'0x[0-9a-fA-F]{64}')
ADDRESS = re.compile(r'0x[0-9a-fA-F]{40}')
CASE = re.compile(r'[0-9a-f]{64}')


def ident(value, pattern):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError('invalid identifier')
    return value.lower()


def wei(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,78}', value):
        raise ValueError('invalid wei')
    number = int(value)
    if number >= 2**256:
        raise ValueError('wei overflow')
    return number


def connect(path, options):
    db = sqlite3.connect(path.resolve().as_uri() + '?' + options, uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    return db


def confirmation(case_id):
    if PROOFS.resolve() != Path.cwd().resolve() / PROOFS or not PROOFS.is_file():
        raise ValueError('confirmation unavailable')
    if any(Path(str(PROOFS) + suffix).exists() for suffix in ('-journal', '-wal', '-shm')):
        raise ValueError('confirmation is not a closed snapshot')
    with closing(connect(PROOFS, 'mode=ro&immutable=1')) as db:
        row = db.execute('SELECT sale_id, tx, snapshot FROM refund_receipt_confirmation WHERE case_id=?', (case_id,)).fetchone()
        if row is None:
            raise ValueError('confirmation missing')
        return row


def review_case(shop, sale, refund):
    requested, jwt = refund['requested'], sale['jwt']
    if type(requested) not in (int, float) or not math.isfinite(requested) or requested <= 0:
        raise ValueError('invalid request time')
    if not isinstance(jwt, str) or not 0 < len(jwt) <= 65536:
        raise ValueError('invalid checkout reference')
    binding = json.dumps([shop, sale['id'], requested, jwt], ensure_ascii=True, separators=(',', ':'))
    return hashlib.sha256(b'r4/refund-review/v1\x00' + binding.encode('ascii')).hexdigest()


def valid_terms(sale, refund):
    allowed = {'early_market_breakage': ('settled',), 'paid_no_delivery': ('paid', 'missing')}
    if sale['status'] not in allowed.get(refund['reason'], ()) or refund['status'] not in ('sending', 'pending_unknown'):
        return False
    if refund['reason'] == 'early_market_breakage':
        settled, broken = sale['settled'], sale['broken']
        if not all(type(value) in (int, float) and math.isfinite(value) for value in (settled, broken)):
            return False
        if not 0 < settled <= broken <= settled + 172800:
            return False
    transfer, fee, gas = (wei(refund[key]) for key in ('transfer_wei', 'fee_wei', 'gas_wei'))
    return (
        ident(sale['payer'], ADDRESS) == ident(refund['payer'], ADDRESS)
        and ident(sale['payment'], HASH) == ident(refund['incoming'], HASH)
        and isinstance(refund['marker'], str) and bool(refund['marker'].strip())
        and 0 < transfer == wei(sale['expected_wei']) and fee == wei(sale['fee_wei'])
        and gas <= wei(sale['gas_cap_wei']) and transfer + fee + gas == wei(refund['wei'])
        and (not fee or ident(sale['fee_payment'], HASH) == ident(refund['fee_payment'], HASH))
    )


def release_ticket(db, sale):
    key = sale['ticket']
    if key is None:
        return
    row = db.execute('SELECT owner FROM ticket WHERE key=?', (key,)).fetchone()
    if row is None or row['owner'] != sale['owner']:
        raise ValueError('ticket owner mismatch')
    db.execute("UPDATE ticket SET status='released' WHERE key=? AND owner=? AND status='held'", (key, sale['owner']))


def reconcile_offsets(db, owner, now):
    debt = sum(row[0] for row in db.execute('''SELECT a.amount FROM allocation a
        JOIN lot l ON l.sale_id=a.lot_id
        WHERE l.owner=? AND l.revoked IS NOT NULL AND a.status IN ('held','spent')''', (owner,)))
    offsets = db.execute('''SELECT a.id, a.sale_id, a.lot_id, a.amount FROM allocation a
        JOIN lot l ON l.sale_id=a.lot_id
        WHERE l.owner=? AND l.revoked IS NULL AND a.status='offset'
        ORDER BY l.expires, l.sale_id, a.id''', (owner,)).fetchall()
    for row in offsets:
        retained = min(debt, row['amount'])
        debt -= retained
        excess = row['amount'] - retained
        if not excess:
            continue
        if retained == 0:
            db.execute("UPDATE allocation SET status='released' WHERE id=?", (row['id'],))
        else:
            db.execute('UPDATE allocation SET amount=? WHERE id=?', (retained, row['id']))
            db.execute("INSERT INTO allocation(sale_id,lot_id,amount,status) VALUES(?,?,?,'released')",
                       (row['sale_id'], row['lot_id'], excess))
    if not debt:
        return
    lots = db.execute('''SELECT l.sale_id, l.amount-COALESCE(SUM(a.amount),0) AS available
        FROM lot l LEFT JOIN allocation a ON a.lot_id=l.sale_id AND a.status!='released'
        WHERE l.owner=? AND l.revoked IS NULL AND l.expires>?
        GROUP BY l.sale_id HAVING available>0 ORDER BY l.expires, l.sale_id''', (owner, now)).fetchall()
    for row in lots:
        amount = min(debt, row['available'])
        db.execute("INSERT INTO allocation(sale_id,lot_id,amount,status) VALUES(NULL,?,?,'offset')", (row['sale_id'], amount))
        debt -= amount
        if not debt:
            break


def reverse_benefits(db, sale, now):
    sale_id, owner = sale['id'], sale['owner']
    lot = db.execute('SELECT owner FROM lot WHERE sale_id=?', (sale_id,)).fetchone()
    if lot is not None and lot['owner'] != owner:
        raise ValueError('earned lot owner mismatch')
    mismatch = db.execute('''SELECT 1 FROM allocation a LEFT JOIN lot l ON l.sale_id=a.lot_id
        WHERE a.sale_id=? AND a.status IN ('held','spent') AND l.owner IS NOT ? LIMIT 1''', (sale_id, owner)).fetchone()
    if mismatch is not None:
        raise ValueError('purchase allocation owner mismatch')
    db.execute("UPDATE allocation SET status='released' WHERE sale_id=? AND status IN ('held','spent')", (sale_id,))
    db.execute('UPDATE lot SET revoked=? WHERE sale_id=? AND revoked IS NULL', (now, sale_id))
    reconcile_offsets(db, owner, now)
    release_ticket(db, sale)
    db.execute("UPDATE promotion_loss SET state='refunded' WHERE sale_id=? AND state!='refunded'", (sale_id,))


def load_bound_case(db, case_id, sale_id, kit):
    sale = db.execute('SELECT * FROM sale WHERE id=?', (sale_id,)).fetchone()
    refund = db.execute('SELECT * FROM refund WHERE sale_id=?', (sale_id,)).fetchone()
    identity = db.execute('SELECT shop, wallet FROM identity WHERE singleton=1').fetchone()
    wallet = ident(kit.address('shop'), ADDRESS)
    if sale is None or refund is None or identity is None:
        raise ValueError('case missing')
    if identity['shop'] != kit.name or ident(identity['wallet'], ADDRESS) != wallet or ident(sale['wallet'], ADDRESS) != wallet:
        raise ValueError('shop mismatch')
    if review_case(kit.name, sale, refund) != case_id:
        raise ValueError('case mismatch')
    return sale, refund


def complete(db, case_id, kit):
    db.execute('''CREATE TABLE IF NOT EXISTS refund_completion (
        case_id TEXT PRIMARY KEY, sale_id TEXT NOT NULL UNIQUE REFERENCES sale(id),
        tx TEXT NOT NULL UNIQUE, snapshot TEXT NOT NULL, completed REAL NOT NULL)''')
    saved = db.execute('SELECT sale_id, tx FROM refund_completion WHERE case_id=?', (case_id,)).fetchone()
    if saved is not None:
        sale, refund = load_bound_case(db, case_id, saved['sale_id'], kit)
        if sale['status'] != 'refunded' or refund['status'] != 'refunded' or ident(refund['outgoing'], HASH) != saved['tx']:
            raise ValueError('completed case mismatch')
        return 'already_completed'
    proof = confirmation(case_id)
    sale, refund = load_bound_case(db, case_id, proof['sale_id'], kit)
    tx = ident(refund['outgoing'], HASH)
    snapshot = hashlib.sha256(kit.canon({'sale': dict(sale), 'refund': dict(refund)})).hexdigest()
    if ident(proof['tx'], HASH) != tx or proof['snapshot'] != snapshot or not valid_terms(sale, refund):
        raise ValueError('confirmation mismatch')
    duplicate = db.execute('''SELECT 1 FROM refund
        WHERE (sale_id!=? AND lower(outgoing)=?) OR lower(incoming)=? OR lower(fee_payment)=?
        UNION ALL SELECT 1 FROM sale WHERE lower(payment)=? OR lower(fee_payment)=? LIMIT 1''',
        (sale['id'], tx, tx, tx, tx, tx)).fetchone()
    if duplicate is not None:
        raise ValueError('duplicate outgoing hash')
    now = time.time()
    reverse_benefits(db, sale, now)
    db.execute("UPDATE sale SET status='refunded' WHERE id=?", (sale['id'],))
    db.execute("UPDATE refund SET status='refunded' WHERE sale_id=?", (sale['id'],))
    db.execute('INSERT INTO refund_completion VALUES(?,?,?,?,?)', (case_id, sale['id'], tx, snapshot, now))
    return 'completed'


def run(args, kit):
    if not isinstance(args, dict) or set(args) != {'case_id'} or not isinstance(args['case_id'], str) or not CASE.fullmatch(args['case_id']):
        return {'status': 'invalid_arguments'}
    try:
        with closing(connect(LEDGER, 'mode=rw')) as db, db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('BEGIN IMMEDIATE')
            status = complete(db, args['case_id'], kit)
        return {'status': status, 'case_id': args['case_id']}
    except (sqlite3.Error, OSError, ValueError, OverflowError):
        return {'status': 'completion_blocked'}
