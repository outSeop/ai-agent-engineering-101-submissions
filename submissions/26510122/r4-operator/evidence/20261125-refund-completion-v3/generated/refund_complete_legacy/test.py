import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

ROOT = Path('state/r4-benefits')
LEDGER = ROOT / 'benefits.sqlite3'
PROOFS = ROOT / 'refund-confirmations.sqlite3'
PAYER = '0x' + 'a' * 40
EXPIRES = 4000000000
DDL = '''
CREATE TABLE account(key TEXT PRIMARY KEY, created REAL NOT NULL);
CREATE TABLE identity(singleton INTEGER PRIMARY KEY CHECK(singleton=1), shop TEXT NOT NULL, wallet TEXT NOT NULL);
CREATE TABLE ticket(key TEXT PRIMARY KEY, sku TEXT NOT NULL, owner TEXT REFERENCES account(key),
    created REAL NOT NULL, expires REAL NOT NULL, discount INTEGER NOT NULL, ready REAL,
    status TEXT NOT NULL CHECK(status IN ('waiting','held','used','released')));
CREATE TABLE sale(id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES account(key),
    unit TEXT NOT NULL, sku TEXT NOT NULL, base INTEGER NOT NULL CHECK(base>0), cost INTEGER NOT NULL CHECK(cost>=0),
    price INTEGER NOT NULL CHECK(price>0), discount INTEGER NOT NULL CHECK(discount>=0), spent INTEGER NOT NULL CHECK(spent>=0),
    ticket TEXT REFERENCES ticket(key), shop_url TEXT NOT NULL, wallet TEXT NOT NULL, created REAL NOT NULL,
    digest TEXT UNIQUE NOT NULL, jwt TEXT NOT NULL, expected_wei TEXT NOT NULL, fee_wei TEXT NOT NULL,
    gas_cap_wei TEXT NOT NULL, fee_wallet TEXT NOT NULL, grade TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('issued','cancel_requested','paid','missing','settled','refunded')),
    market_order TEXT UNIQUE, payment TEXT UNIQUE, fee_payment TEXT UNIQUE, payer TEXT, settled REAL, broken REAL,
    CHECK(price=base-discount-spent));
CREATE TABLE refund(sale_id TEXT PRIMARY KEY REFERENCES sale(id), incoming TEXT NOT NULL UNIQUE,
    payer TEXT NOT NULL, wei TEXT NOT NULL, marker TEXT NOT NULL UNIQUE, transfer_wei TEXT NOT NULL,
    fee_wei TEXT NOT NULL, gas_wei TEXT NOT NULL, fee_payment TEXT, reason TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('requested','sending','pending_unknown','refunded')),
    outgoing TEXT UNIQUE, requested REAL NOT NULL);
CREATE TABLE lot(sale_id TEXT PRIMARY KEY REFERENCES sale(id), owner TEXT NOT NULL REFERENCES account(key),
    amount INTEGER NOT NULL CHECK(amount>0), expires REAL NOT NULL, revoked REAL);
CREATE TABLE allocation(id INTEGER PRIMARY KEY, sale_id TEXT REFERENCES sale(id), lot_id TEXT NOT NULL REFERENCES lot(sale_id),
    amount INTEGER NOT NULL CHECK(amount>0), status TEXT NOT NULL CHECK(status IN ('held','spent','offset','released')),
    CHECK(sale_id IS NOT lot_id));
CREATE TABLE promotion_loss(sale_id TEXT PRIMARY KEY REFERENCES sale(id), policy_id TEXT NOT NULL,
    reserved INTEGER NOT NULL CHECK(reserved>0), amount INTEGER NOT NULL CHECK(amount>=0),
    state TEXT NOT NULL CHECK(state IN ('reserved','settled','refunded')), at REAL NOT NULL);
'''


def chain_hash(value):
    return '0x' + format(value, '064x')


def sale(db, wallet, name, number, owner='owner', spent=0, ticket=None, status='settled'):
    db.execute('''INSERT INTO sale VALUES(?,?,?,'sku',100,10,?,0,?,?,'https://fixture.invalid',?,100,
        ?,?,'900','0','2',?,'grade',?,?,?,NULL,?,100,110)''',
        (name, owner, name, 100-spent, spent, ticket, wallet, 'digest-'+name, 'jwt-'+name,
         wallet, status, 'order-'+name, chain_hash(number), PAYER))


def refund(db, name, number, reason):
    db.execute('INSERT INTO refund VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
               (name, chain_hash(number), PAYER, '901', 'marker-'+name, '900', '0', '1', None,
                reason, 'pending_unknown', chain_hash(number+100), 120))


def proof(db, kit, name):
    sale_row = dict(db.execute('SELECT * FROM sale WHERE id=?', (name,)).fetchone())
    refund_row = dict(db.execute('SELECT * FROM refund WHERE sale_id=?', (name,)).fetchone())
    binding = json.dumps([kit.name, name, refund_row['requested'], sale_row['jwt']], ensure_ascii=True, separators=(',', ':'))
    case_id = hashlib.sha256(b'r4/refund-review/v1\x00' + binding.encode('ascii')).hexdigest()
    snapshot = hashlib.sha256(kit.canon({'sale': sale_row, 'refund': refund_row})).hexdigest()
    return case_id, name, refund_row['outgoing'], snapshot


def test(run, kit):
    assert kit.testing
    ROOT.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(LEDGER)) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.executescript(DDL)
        wallet = kit.address('shop')
        db.execute('INSERT INTO identity VALUES(1,?,?)', (kit.name, wallet))
        db.executemany('INSERT INTO account VALUES(?,100)', [('owner',), ('other',)])
        db.executemany("INSERT INTO ticket VALUES(?,'sku',?,100,?,1,101,?)",
                       [('used','owner',EXPIRES,'used'), ('held','owner',EXPIRES,'held'), ('other','other',EXPIRES,'held')])
        sale(db, wallet, 'prior', 1)
        sale(db, wallet, 'target', 2, spent=45, ticket='used')
        sale(db, wallet, 'later-held', 3, spent=20, status='issued')
        sale(db, wallet, 'later-spent', 4, spent=25)
        sale(db, wallet, 'untouched', 5, owner='other', ticket='other')
        sale(db, wallet, 'missing', 6, ticket='held', status='missing')
        db.executemany('INSERT INTO lot VALUES(?,?,?,?,NULL)',
                       [('prior','owner',45,EXPIRES), ('target','owner',45,EXPIRES), ('untouched','other',13,EXPIRES)])
        db.executemany('INSERT INTO allocation VALUES(?,?,?,?,?)',
                       [(1,'target','prior',45,'spent'), (2,'later-held','target',20,'held'), (3,'later-spent','target',25,'spent')])
        db.execute("INSERT INTO promotion_loss VALUES('target','policy',9,7,'settled',115)")
        refund(db, 'target', 2, 'early_market_breakage')
        refund(db, 'missing', 6, 'paid_no_delivery')
        db.commit()
        first, second = proof(db, kit, 'target'), proof(db, kit, 'missing')
        args = {'case_id': first[0]}
        assert run(args, kit)['status'] == 'completion_blocked'
        with closing(sqlite3.connect(PROOFS)) as proofs, proofs:
            proofs.execute('CREATE TABLE refund_receipt_confirmation(case_id TEXT PRIMARY KEY,sale_id TEXT,tx TEXT,snapshot TEXT)')
            proofs.executemany('INSERT INTO refund_receipt_confirmation VALUES(?,?,?,?)', [first, second])
        assert run(dict(args, success=True), kit)['status'] == 'invalid_arguments'
        db.execute("UPDATE sale SET grade='changed' WHERE id='target'")
        db.commit()
        assert run(args, kit)['status'] == 'completion_blocked'
        db.execute("UPDATE sale SET grade='grade' WHERE id='target'")
        db.execute("CREATE TRIGGER synthetic_failure BEFORE UPDATE OF status ON refund BEGIN SELECT RAISE(ABORT,'fixture rollback'); END")
        db.commit()
        assert run(args, kit)['status'] == 'completion_blocked'
        assert tuple(db.execute("SELECT state, amount FROM promotion_loss WHERE sale_id='target'").fetchone()) == ('settled', 7)
        assert db.execute("SELECT revoked FROM lot WHERE sale_id='target'").fetchone()[0] is None
        assert db.execute('SELECT status FROM allocation WHERE id=1').fetchone()[0] == 'spent'
        db.execute('DROP TRIGGER synthetic_failure')
        db.commit()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: run(args, kit)['status'], range(2)))
        assert sorted(results) == ['already_completed', 'completed'], results
        assert run(args, kit)['status'] == 'already_completed'
        assert run({'case_id': second[0]}, kit)['status'] == 'completed'
        assert db.execute('SELECT COUNT(*) FROM refund_completion').fetchone()[0] == 2
        assert dict(db.execute("SELECT sale_id,status FROM refund")) == {'target':'refunded','missing':'refunded'}
        assert dict(db.execute("SELECT id,status FROM sale WHERE id IN ('target','missing')")) == {'target':'refunded','missing':'refunded'}
        assert dict(db.execute('SELECT key,status FROM ticket')) == {'used':'used','held':'released','other':'held'}
        assert tuple(db.execute("SELECT state,reserved,amount FROM promotion_loss").fetchone()) == ('refunded', 9, 7)
        assert tuple(db.execute("SELECT amount,expires FROM lot WHERE sale_id='target' AND revoked IS NOT NULL").fetchone()) == (45, EXPIRES)
        assert [(row['sale_id'], row['lot_id'], row['amount'], row['status']) for row in db.execute(
            'SELECT * FROM allocation ORDER BY id')] == [('target','prior',45,'released'), ('later-held','target',20,'held'),
            ('later-spent','target',25,'spent'), (None,'prior',45,'offset')]
        available = dict(db.execute("""SELECT l.owner, SUM(l.amount-COALESCE((SELECT SUM(a.amount) FROM allocation a
            WHERE a.lot_id=l.sale_id AND a.status!='released'),0)) FROM lot l WHERE l.revoked IS NULL GROUP BY l.owner"""))
        assert available == {'owner':0, 'other':13}
