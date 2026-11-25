import hashlib
import os
import sqlite3
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path


ROOT = Path('state/r4-benefits')
LEDGER = ROOT / 'benefits.sqlite3'
CASE = 'e' * 64
OUT = '0x' + 'a' * 64
IN = '0x' + 'b' * 64
PAYER = '0x' + 'c' * 40


def fixture(kit, held=True, used=False):
    ROOT.mkdir(parents=True)
    wallet = kit.address('shop')
    with closing(sqlite3.connect(LEDGER)) as db, db:
        db.executescript('''
            CREATE TABLE identity(singleton INTEGER PRIMARY KEY,shop TEXT,wallet TEXT);
            CREATE TABLE sale(id TEXT PRIMARY KEY,owner TEXT,wallet TEXT,payer TEXT,payment TEXT,
                fee_payment TEXT,expected_wei TEXT,fee_wei TEXT,gas_cap_wei TEXT,status TEXT,
                spent INTEGER,ticket TEXT,settled REAL,broken REAL);
            CREATE TABLE refund(sale_id TEXT PRIMARY KEY,incoming TEXT,payer TEXT,wei TEXT,
                marker TEXT,transfer_wei TEXT,fee_wei TEXT,gas_wei TEXT,fee_payment TEXT,
                reason TEXT,status TEXT,outgoing TEXT,requested REAL);
            CREATE TABLE lot(sale_id TEXT PRIMARY KEY,owner TEXT,amount INTEGER,expires REAL,revoked REAL);
            CREATE TABLE allocation(id INTEGER PRIMARY KEY,sale_id TEXT,lot_id TEXT,amount INTEGER,
                status TEXT CHECK(status IN ('held','spent','offset','released')));
            CREATE TABLE debt(owner TEXT PRIMARY KEY,amount INTEGER CHECK(amount>=0));
            CREATE TABLE ticket(id TEXT PRIMARY KEY,owner TEXT,held TEXT,used REAL,expires REAL);
            CREATE TABLE promotion_loss(sale_id TEXT PRIMARY KEY,policy_id TEXT,reserved INTEGER,
                amount INTEGER,state TEXT CHECK(state IN ('spent','refunded')),at REAL);
            CREATE TABLE stock_intent(id TEXT PRIMARY KEY,state TEXT);
            INSERT INTO stock_intent VALUES('stock','pending_unknown');
            INSERT INTO lot VALUES('sale','alice',10,4000000000,NULL),
                ('restored','alice',5,3999999990,NULL),('other','alice',6,4000000000,NULL),
                ('expired','alice',20,1,NULL),('foreign','bob',50,4000000000,NULL);
            INSERT INTO allocation VALUES(1,'sale','restored',5,'held'),
                (2,'other-order','sale',8,'spent'),(3,'another-order','other',4,'held'),
                (4,'unrelated','foreign',3,'spent');
            INSERT INTO debt VALUES('alice',2),('bob',1);
            INSERT INTO promotion_loss VALUES('sale','policy',20,15,'spent',100),
                ('other','policy',20,13,'spent',100);
        ''')
        db.execute('INSERT INTO identity VALUES(1,?,?)', (kit.name, wallet))
        db.execute('INSERT INTO sale VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   ('sale','alice',wallet,PAYER,IN,None,'12','0','3','missing',5,'ticket',None,None))
        db.execute('INSERT INTO refund VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   ('sale',IN,PAYER,'14','marker','12','0','2',None,'paid_no_delivery','pending_unknown',OUT,100))
        db.execute('INSERT INTO ticket VALUES(?,?,?,?,?)', ('ticket','alice','sale' if held else None,123 if used else None,4000000000))
        db.row_factory = sqlite3.Row
        sale = dict(db.execute('SELECT * FROM sale').fetchone())
        refund = dict(db.execute('SELECT * FROM refund').fetchone())
    snapshot = hashlib.sha256(kit.canon({'sale': sale, 'refund': refund})).hexdigest()
    with closing(sqlite3.connect(ROOT / 'refund-confirmations.sqlite3')) as db, db:
        db.execute('CREATE TABLE refund_receipt_confirmation(case_id TEXT PRIMARY KEY,sale_id TEXT,tx TEXT,snapshot TEXT)')
        db.execute('INSERT INTO refund_receipt_confirmation VALUES(?,?,?,?)', (CASE,'sale',OUT,snapshot))


def dump():
    with closing(sqlite3.connect(LEDGER)) as db:
        return tuple(db.iterdump())


def test(run, kit):
    original = Path.cwd()
    with tempfile.TemporaryDirectory() as directory:
        try:
            for index, scenario in enumerate(('normal','used','terms','missing','duplicate','wrong_tx','lot','allocation','debt','ticket','promotion_loss','sale','refund','refund_completion')):
                folder = Path(directory) / str(index)
                folder.mkdir()
                os.chdir(folder)
                fixture(kit, used=scenario == 'used')
                args = {'case_id': CASE}
                if scenario in ('normal','used'):
                    assert run({'case_id': CASE, 'success': True}, kit)['status'] == 'invalid_request'
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        statuses = list(pool.map(lambda _: run(args, kit)['status'], range(2)))
                    assert sorted(statuses) == ['already_completed','completed'], statuses
                    before = dump()
                    assert run(args, kit)['status'] == 'already_completed' and dump() == before
                    with closing(sqlite3.connect(LEDGER)) as db:
                        assert db.execute('SELECT status FROM sale').fetchone() == ('refunded',)
                        assert db.execute('SELECT status FROM refund').fetchone() == ('refunded',)
                        assert db.execute("SELECT revoked FROM lot WHERE sale_id='sale'").fetchone()[0] is not None
                        assert db.execute('SELECT status FROM allocation WHERE id<=4 ORDER BY id').fetchall() == [('released',),('spent',),('held',),('spent',)]
                        assert db.execute("SELECT lot_id,amount FROM allocation WHERE status='offset' ORDER BY id").fetchall() == [('restored',5),('other',2)]
                        assert db.execute('SELECT * FROM debt ORDER BY owner').fetchall() == [('alice',3),('bob',1)]
                        expected = ('sale',123,4000000000) if scenario == 'used' else (None,None,4000000000)
                        assert db.execute('SELECT held,used,expires FROM ticket').fetchone() == expected
                        assert db.execute('SELECT state,amount,reserved FROM promotion_loss ORDER BY sale_id').fetchall() == [('spent',13,20),('refunded',15,20)]
                        assert db.execute('SELECT * FROM stock_intent').fetchall() == [('stock','pending_unknown')]
                    continue
                if scenario == 'missing':
                    (ROOT / 'refund-confirmations.sqlite3').unlink()
                with closing(sqlite3.connect(LEDGER)) as db, db:
                    if scenario == 'terms':
                        db.execute("UPDATE refund SET wei='15'")
                    elif scenario == 'duplicate':
                        db.execute('INSERT INTO refund SELECT ?,incoming,payer,wei,marker,transfer_wei,fee_wei,gas_wei,fee_payment,reason,status,outgoing,requested FROM refund', ('second',))
                    elif scenario == 'wrong_tx':
                        db.execute('UPDATE refund SET outgoing=?', ('0x' + 'd'*64,))
                    elif scenario != 'missing':
                        if scenario == 'refund_completion':
                            db.execute('CREATE TABLE refund_completion(case_id TEXT PRIMARY KEY,sale_id TEXT UNIQUE,tx TEXT UNIQUE,snapshot TEXT,completed REAL)')
                        op = 'INSERT' if scenario in ('debt','refund_completion') else 'UPDATE'
                        db.execute(f"CREATE TRIGGER fault BEFORE {op} ON {scenario} BEGIN SELECT RAISE(ABORT,'fixture fault'); END")
                before = dump()
                expected = {'terms':'evidence_mismatch','missing':'confirmation_required','duplicate':'ambiguous_transfer','wrong_tx':'evidence_mismatch'}.get(scenario,'completion_blocked')
                assert run(args, kit)['status'] == expected, scenario
                assert dump() == before, scenario
        finally:
            os.chdir(original)
