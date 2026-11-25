import hashlib
import os
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path

LEDGER = Path('state/r4-benefits/benefits.sqlite3')
HASH = re.compile(r'0x[0-9a-fA-F]{64}\Z')
ADDRESS = re.compile(r'0x[0-9a-fA-F]{40}\Z')
PENDING = ('sending', 'pending_unknown')

def ident(value, pattern):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError('invalid chain identifier')
    return value.lower()

def wei(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,78}', value):
        raise ValueError('invalid wei')
    return int(value)

def connect(path, mode):
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=' + mode, uri=True, timeout=3)
    db.row_factory = sqlite3.Row
    return db

def confirmation(case_id):
    configured = os.environ.get('R4_REFUND_CONFIRMATION_DB')
    if not configured or not Path(configured).is_absolute():
        return None
    path = Path(configured).resolve(strict=True)
    if path.is_relative_to(Path.cwd().resolve()):
        return None
    with closing(connect(path, 'ro')) as db:
        return db.execute('SELECT sale_id, tx, snapshot FROM refund_receipt_confirmation WHERE case_id=?', (case_id,)).fetchone()

def valid_terms(sale, refund, wallet):
    allowed = {'early_market_breakage': ('settled',), 'paid_no_delivery': ('paid', 'missing')}
    if sale['status'] not in allowed.get(refund['reason'], ()) or refund['status'] not in PENDING:
        return False
    transfer, fee, gas = (wei(refund[key]) for key in ('transfer_wei', 'fee_wei', 'gas_wei'))
    return (
        ident(sale['wallet'], ADDRESS) == wallet
        and ident(sale['payer'], ADDRESS) == ident(refund['payer'], ADDRESS)
        and ident(sale['payment'], HASH) == ident(refund['incoming'], HASH)
        and isinstance(refund['marker'], str) and bool(refund['marker'].strip())
        and transfer == wei(sale['expected_wei']) and fee == wei(sale['fee_wei'])
        and gas <= wei(sale['gas_cap_wei'])
        and 0 < transfer + fee + gas == wei(refund['wei'])
        and (not fee or ident(sale['fee_payment'], HASH) == ident(refund['fee_payment'], HASH))
    )

def reverse_benefits(db, sale):
    sale_id, owner = sale['id'], sale['owner']
    lot = db.execute('SELECT owner, revoked FROM lot WHERE sale_id=?', (sale_id,)).fetchone()
    if lot is not None and lot['owner'] != owner:
        raise ValueError('lot owner mismatch')
    allocations = db.execute('''SELECT a.lot_id, a.amount, a.status, l.owner
        FROM allocation a LEFT JOIN lot l ON l.sale_id=a.lot_id WHERE a.sale_id=?''', (sale_id,)).fetchall()
    for row in allocations:
        if (row['owner'] != owner or row['lot_id'] == sale_id
                or type(row['amount']) is not int or row['amount'] <= 0
                or row['status'] not in ('reserved', 'spent', 'released')):
            raise ValueError('unsupported allocation')
    if sum(row['amount'] for row in allocations) != sale['spent']:
        raise ValueError('allocation total mismatch')
    if lot is not None and lot['revoked'] is None:
        if db.execute('UPDATE lot SET revoked=? WHERE sale_id=?', (time.time(), sale_id)).rowcount != 1:
            raise ValueError('lot update failed')
    changed = db.execute("UPDATE allocation SET status='released' WHERE sale_id=? AND status IN ('reserved','spent')", (sale_id,)).rowcount
    if changed != sum(row['status'] != 'released' for row in allocations):
        raise ValueError('allocation update failed')

def run(args, kit):
    case_id = args.get('case_id') if isinstance(args, dict) else None
    if not isinstance(case_id, str) or set(args) != {'case_id'} or not re.fullmatch(r'[A-Za-z0-9_:-]{16,128}', case_id):
        return {'status': 'invalid_request'}
    try:
        wallet = ident(kit.address('shop'), ADDRESS)
        with closing(connect(LEDGER, 'rw')) as db, db:
            db.execute('BEGIN IMMEDIATE')
            identity = db.execute('SELECT wallet FROM identity WHERE singleton=1').fetchone()
            if identity is None or ident(identity['wallet'], ADDRESS) != wallet:
                return {'status': 'identity_mismatch'}
            proof = confirmation(case_id)
            if proof is None:
                return {'status': 'confirmation_required'}
            sale_id = proof['sale_id']
            tx = ident(proof['tx'], HASH)
            sale = db.execute('SELECT * FROM sale WHERE id=?', (sale_id,)).fetchone()
            refund = db.execute('SELECT * FROM refund WHERE sale_id=?', (sale_id,)).fetchone()
            if sale is None or refund is None or not refund['outgoing']:
                return {'status': 'known_transfer_required'}
            if ident(refund['outgoing'], HASH) != tx or ident(sale['wallet'], ADDRESS) != wallet:
                return {'status': 'evidence_mismatch'}
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='refund_completion'").fetchone():
                completed = db.execute('SELECT * FROM refund_completion WHERE case_id=?', (case_id,)).fetchone()
                if completed is not None:
                    if (completed['sale_id'] == sale_id and completed['tx'] == tx
                            and completed['snapshot'] == proof['snapshot']
                            and sale['status'] == refund['status'] == 'refunded'):
                        return {'status': 'completed'}
                    return {'status': 'evidence_mismatch'}
            snapshot = {'purpose': 'refund_completion_v1', 'case_id': case_id, 'tx': tx,
                        'sale': dict(sale), 'refund': dict(refund)}
            digest = hashlib.sha256(kit.canon(snapshot)).hexdigest()
            if digest != proof['snapshot'] or not valid_terms(sale, refund, wallet):
                return {'status': 'evidence_mismatch'}
            if db.execute('SELECT 1 FROM refund WHERE sale_id<>? AND lower(outgoing)=?', (sale_id, tx)).fetchone():
                return {'status': 'duplicate_transfer'}
            db.execute('''CREATE TABLE IF NOT EXISTS refund_completion(
                case_id TEXT PRIMARY KEY, sale_id TEXT NOT NULL UNIQUE,
                tx TEXT NOT NULL UNIQUE, snapshot TEXT NOT NULL)''')
            reverse_benefits(db, sale)
            if db.execute("UPDATE refund SET status='refunded' WHERE sale_id=?", (sale_id,)).rowcount != 1:
                raise ValueError('refund update failed')
            if db.execute("UPDATE sale SET status='refunded' WHERE id=?", (sale_id,)).rowcount != 1:
                raise ValueError('sale update failed')
            db.execute('INSERT INTO refund_completion VALUES (?,?,?,?)', (case_id, sale_id, tx, digest))
        return {'status': 'completed'}
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return {'status': 'completion_blocked'}
