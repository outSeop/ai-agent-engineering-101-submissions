import hashlib
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


def ident(value, pattern):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError('invalid chain identifier')
    return value.lower()


def wei(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,78}', value):
        raise ValueError('invalid wei')
    if int(value) >= 2**256:
        raise ValueError('wei overflow')
    return int(value)


def connect(path, options):
    db = sqlite3.connect(path.resolve().as_uri() + '?' + options, uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    return db


def confirmation(case_id):
    if PROOFS.resolve() != Path.cwd().resolve() / PROOFS or not PROOFS.is_file():
        return None
    with closing(connect(PROOFS, 'mode=ro&immutable=1')) as db:
        return db.execute('SELECT sale_id,tx,snapshot FROM refund_receipt_confirmation WHERE case_id=?', (case_id,)).fetchone()


def valid_terms(sale, refund):
    allowed = {'early_market_breakage': ('settled',), 'paid_no_delivery': ('paid', 'missing')}
    if sale['status'] not in allowed.get(refund['reason'], ()) or refund['status'] not in ('sending', 'pending_unknown'):
        return False
    if refund['reason'] == 'early_market_breakage':
        if not 0 < sale['settled'] <= sale['broken'] <= sale['settled'] + 172800:
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
    if not sale['ticket']:
        return
    row = db.execute('SELECT * FROM ticket WHERE id=?', (sale['ticket'],)).fetchone()
    if row is None or row['owner'] != sale['owner']:
        raise ValueError('ticket mismatch')
    keys = set(row.keys())
    if {'held', 'used'} <= keys and 'status' not in keys:
        db.execute("UPDATE ticket SET held=NULL WHERE id=? AND held=? AND (used IS NULL OR used=0 OR used='')", (sale['ticket'], sale['id']))
        return
    refs = keys & {'held_sale', 'held_by', 'held', 'sale_id'}
    if 'status' not in keys or len(refs) != 1:
        raise ValueError('unsupported ticket schema')
    ref = refs.pop()
    if row['status'] != 'held' or row[ref] != sale['id']:
        return
    ddl = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='ticket'").fetchone()[0]
    available = re.findall(r"['\"](available|active|open|ready|issued)['\"]", ddl.lower())
    if len(set(available)) != 1:
        raise ValueError('ambiguous ticket release state')
    db.execute(f'UPDATE ticket SET status=?, {ref}=NULL WHERE id=? AND status=\'held\' AND {ref}=?', (available[0], sale['ticket'], sale['id']))


def reverse_benefits(db, sale, refund, now):
    sale_id, owner = sale['id'], sale['owner']
    lot = db.execute('SELECT owner, revoked FROM lot WHERE sale_id=?', (sale_id,)).fetchone()
    if lot is not None and lot['owner'] != owner:
        raise ValueError('lot owner mismatch')
    rows = db.execute('''SELECT a.lot_id, a.amount, a.status, l.owner
        FROM allocation a LEFT JOIN lot l ON l.sale_id=a.lot_id
        WHERE a.sale_id=? AND a.status!='offset' ''', (sale_id,)).fetchall()
    for row in rows:
        if (row['owner'] != owner or row['lot_id'] == sale_id
                or type(row['amount']) is not int or row['amount'] <= 0
                or row['status'] not in ('held', 'spent', 'released')):
            raise ValueError('unsupported allocation')
    if sum(row['amount'] for row in rows) != sale['spent']:
        raise ValueError('allocation total mismatch')
    db.execute("UPDATE allocation SET status='released' WHERE sale_id=? AND status IN ('held','spent')", (sale_id,))
    new_debt = 0
    if lot is not None and lot['revoked'] is None:
        db.execute('UPDATE lot SET revoked=? WHERE sale_id=?', (now, sale_id))
        new_debt = db.execute("SELECT COALESCE(SUM(amount),0) FROM allocation WHERE lot_id=? AND status IN ('spent','offset')", (sale_id,)).fetchone()[0]
    if new_debt:
        db.execute('''INSERT INTO debt(owner,amount) VALUES(?,?)
            ON CONFLICT(owner) DO UPDATE SET amount=debt.amount+excluded.amount''', (owner, new_debt))
    if new_debt or rows:
        offset_debt(db, sale_id, owner, now)
    if refund['reason'] == 'paid_no_delivery':
        release_ticket(db, sale)
    db.execute("UPDATE promotion_loss SET state='refunded' WHERE sale_id=? AND state IS NOT 'refunded'", (sale_id,))


def offset_debt(db, sale_id, owner, now):
    row = db.execute('SELECT amount FROM debt WHERE owner=?', (owner,)).fetchone()
    if row is None:
        return
    remaining = row['amount']
    if type(remaining) is not int or remaining < 0:
        raise ValueError('invalid debt')
    if not remaining:
        return
    lots = db.execute('''SELECT l.sale_id,l.amount-COALESCE(SUM(a.amount),0) AS available
        FROM lot l LEFT JOIN allocation a ON a.lot_id=l.sale_id AND a.status IN ('held','spent','offset')
        WHERE l.owner=? AND l.revoked IS NULL AND l.expires>?
        GROUP BY l.sale_id ORDER BY l.expires,l.sale_id''', (owner, now)).fetchall()
    for lot in lots:
        offset = min(remaining, lot['available'])
        if offset < 0:
            raise ValueError('overallocated lot')
        if offset:
            db.execute("INSERT INTO allocation(sale_id,lot_id,amount,status) VALUES(?,?,?,'offset')", (sale_id, lot['sale_id'], offset))
            remaining -= offset
        if not remaining:
            break
    db.execute('UPDATE debt SET amount=? WHERE owner=?', (remaining, owner))


def run(args, kit):
    case_id = args.get('case_id') if isinstance(args, dict) else None
    if not isinstance(case_id, str) or set(args) != {'case_id'} or not re.fullmatch(r'[A-Za-z0-9_:-]{16,128}', case_id):
        return {'status': 'invalid_request'}
    try:
        wallet = ident(kit.address('shop'), ADDRESS)
        with closing(connect(LEDGER, 'mode=rw')) as db, db:
            db.execute('BEGIN IMMEDIATE')
            identity = db.execute('SELECT wallet FROM identity WHERE singleton=1').fetchone()
            if identity is None or ident(identity['wallet'], ADDRESS) != wallet:
                return {'status': 'identity_mismatch'}
            proof = confirmation(case_id)
            if proof is None:
                return {'status': 'confirmation_required'}
            sid, tx = proof['sale_id'], ident(proof['tx'], HASH)
            sale = db.execute('SELECT * FROM sale WHERE id=?', (sid,)).fetchone()
            refund = db.execute('SELECT * FROM refund WHERE sale_id=?', (sid,)).fetchone()
            if sale is None or refund is None or not refund['outgoing']:
                return {'status': 'known_transfer_required'}
            if ident(refund['outgoing'], HASH) != tx or ident(sale['wallet'], ADDRESS) != wallet:
                return {'status': 'evidence_mismatch'}
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='refund_completion'").fetchone():
                completed = db.execute('SELECT sale_id,tx,snapshot FROM refund_completion WHERE case_id=?', (case_id,)).fetchone()
                if completed is not None:
                    if tuple(completed) == (sid, tx, proof['snapshot']) and sale['status'] == refund['status'] == 'refunded':
                        return {'status': 'already_completed'}
                    return {'status': 'evidence_mismatch'}
            snapshot = hashlib.sha256(kit.canon({'sale': dict(sale), 'refund': dict(refund)})).hexdigest()
            if snapshot != proof['snapshot'] or not valid_terms(sale, refund):
                return {'status': 'evidence_mismatch'}
            if db.execute('SELECT count(*) FROM refund WHERE outgoing=? COLLATE NOCASE', (tx,)).fetchone()[0] != 1:
                return {'status': 'ambiguous_transfer'}
            now = time.time()
            reverse_benefits(db, sale, refund, now)
            db.execute("UPDATE sale SET status='refunded' WHERE id=?", (sid,))
            db.execute("UPDATE refund SET status='refunded' WHERE sale_id=?", (sid,))
            db.execute('''CREATE TABLE IF NOT EXISTS refund_completion(
                case_id TEXT PRIMARY KEY, sale_id TEXT UNIQUE NOT NULL, tx TEXT UNIQUE NOT NULL,
                snapshot TEXT NOT NULL, completed REAL NOT NULL)''')
            db.execute('INSERT INTO refund_completion(case_id,sale_id,tx,snapshot,completed) VALUES(?,?,?,?,?)', (case_id, sid, tx, snapshot, now))
        return {'status': 'completed'}
    except (OSError, sqlite3.Error, ValueError, TypeError, IndexError):
        return {'status': 'completion_blocked'}
