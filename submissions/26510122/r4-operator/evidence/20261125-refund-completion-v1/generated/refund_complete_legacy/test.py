import hashlib
import os
import sqlite3
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch

SCHEMA = '''
CREATE TABLE identity(singleton INTEGER PRIMARY KEY,shop TEXT,wallet TEXT);
CREATE TABLE sale(id TEXT PRIMARY KEY,owner TEXT,unit TEXT,sku TEXT,base INTEGER,cost INTEGER,price INTEGER,discount INTEGER,spent INTEGER,ticket TEXT,shop_url TEXT,wallet TEXT,created REAL,digest TEXT,jwt TEXT,expected_wei TEXT,fee_wei TEXT,gas_cap_wei TEXT,fee_wallet TEXT,grade TEXT,status TEXT,market_order TEXT,payment TEXT,fee_payment TEXT,payer TEXT,settled REAL,broken REAL);
CREATE TABLE refund(sale_id TEXT PRIMARY KEY,incoming TEXT,payer TEXT,wei TEXT,marker TEXT,transfer_wei TEXT,fee_wei TEXT,gas_wei TEXT,fee_payment TEXT,reason TEXT,status TEXT,outgoing TEXT,requested REAL);
CREATE TABLE lot(sale_id TEXT PRIMARY KEY,owner TEXT,amount INTEGER,expires REAL,revoked REAL);
CREATE TABLE allocation(id INTEGER PRIMARY KEY,sale_id TEXT,lot_id TEXT,amount INTEGER,status TEXT);
CREATE TABLE promotion_loss(sale_id TEXT PRIMARY KEY,policy_id TEXT,reserved INTEGER,amount INTEGER,state TEXT,at REAL);
CREATE TABLE stock_intent(id TEXT PRIMARY KEY,plan_id TEXT,sku TEXT,qty INTEGER,quote TEXT,total INTEGER,marker TEXT,recipient TEXT,wei TEXT,units TEXT,tx TEXT,chain_anchor INTEGER,ledger_anchor INTEGER,state TEXT,created REAL,retry_at REAL,delivered TEXT);
'''

def test(run, kit):
    seller, buyer = '0x' + '1'*40, '0x' + '2'*40
    incoming, fee, outgoing = ('0x' + char*64 for char in 'abc')
    case = 'd'*64
    args = {'case_id': case}
    fake_kit = SimpleNamespace(address=lambda role: {'shop': seller}[role], canon=kit.canon)
    previous = Path.cwd()
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp).resolve()
        ledger = root / 'agent/state/r4-benefits/benefits.sqlite3'
        host = root / 'host.sqlite3'
        ledger.parent.mkdir(parents=True)
        with closing(sqlite3.connect(ledger)) as db, closing(sqlite3.connect(host)) as proof_db:
            db.row_factory = sqlite3.Row
            db.executescript(SCHEMA)
            db.execute('INSERT INTO identity VALUES (1,?,?)', ('outseop-r4', seller))
            db.execute('''INSERT INTO sale(id,owner,spent,ticket,wallet,expected_wei,fee_wei,gas_cap_wei,status,payment,fee_payment,payer)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''', ('sale','owner',7,'ticket',seller,'100','5','4','settled',incoming,fee,buyer))
            db.execute("INSERT INTO sale(id,owner,status) VALUES ('later','owner','settled')")
            db.execute('INSERT INTO refund VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', ('sale',incoming,buyer,'108','marker','100','5','3',fee,'early_market_breakage','pending_unknown',outgoing,1))
            db.executescript('''INSERT INTO lot VALUES ('sale','owner',20,333,NULL),('prior','owner',10,111,NULL);
                INSERT INTO allocation VALUES (1,'sale','prior',7,'spent'),(2,'later','sale',16,'spent');
                INSERT INTO promotion_loss VALUES ('sale','promo',4,4,'consumed',1);
                INSERT INTO stock_intent(id,state) VALUES ('existing','pending_unknown');''')
            sale = dict(db.execute("SELECT * FROM sale WHERE id='sale'").fetchone())
            refund = dict(db.execute('SELECT * FROM refund').fetchone())
            digest = hashlib.sha256(kit.canon({'purpose':'refund_completion_v1','case_id':case,'tx':outgoing,'sale':sale,'refund':refund})).hexdigest()
            proof_db.execute('CREATE TABLE refund_receipt_confirmation(case_id TEXT PRIMARY KEY,sale_id TEXT,tx TEXT,snapshot TEXT)')
            proof_db.execute('INSERT INTO refund_receipt_confirmation VALUES (?,?,?,?)', (case,'sale',outgoing,digest))
            db.commit()
            proof_db.commit()
            def rows(sql):
                return [tuple(row) for row in db.execute(sql)]
            unchanged_queries = ['SELECT * FROM promotion_loss','SELECT * FROM stock_intent',
                                 "SELECT * FROM sale WHERE id='later'", "SELECT * FROM lot WHERE sale_id='prior'",
                                 'SELECT * FROM allocation WHERE id=2']
            unchanged = [rows(query) for query in unchanged_queries]
            try:
                os.chdir(ledger.parents[2])
                with patch.dict(os.environ, {'R4_REFUND_CONFIRMATION_DB':str(host)}):
                    assert run({'case_id':case,'success':True}, fake_kit)['status'] == 'invalid_request'
                    assert run({'case_id':'e'*64}, fake_kit)['status'] == 'confirmation_required'
                    db.execute("UPDATE refund SET outgoing=NULL WHERE sale_id='sale'")
                    db.commit()
                    assert run(args, fake_kit)['status'] == 'known_transfer_required'
                    db.execute("UPDATE refund SET outgoing=?, gas_wei='4' WHERE sale_id='sale'", (outgoing,))
                    db.commit()
                    assert run(args, fake_kit)['status'] == 'evidence_mismatch'
                    db.execute("UPDATE refund SET gas_wei='3' WHERE sale_id='sale'")
                    db.execute('INSERT INTO refund(sale_id,outgoing) VALUES (?,?)', ('duplicate',outgoing.upper()))
                    db.commit()
                    assert run(args, fake_kit)['status'] == 'duplicate_transfer'
                    db.execute("DELETE FROM refund WHERE sale_id='duplicate'")
                    db.executescript("CREATE TRIGGER fail_sale BEFORE UPDATE OF status ON sale BEGIN SELECT RAISE(ABORT,'fixture'); END;")
                    assert run(args, fake_kit)['status'] == 'completion_blocked'
                    assert rows('SELECT status FROM refund') == [('pending_unknown',)]
                    assert rows('SELECT revoked FROM lot') == [(None,), (None,)]
                    assert rows('SELECT status FROM allocation ORDER BY id') == [('spent',), ('spent',)]
                    assert rows("SELECT name FROM sqlite_master WHERE name='refund_completion'") == []
                    db.execute('DROP TRIGGER fail_sale')
                    db.commit()
                    gate = Barrier(2, timeout=4)
                    def complete():
                        gate.wait()
                        return run(args, fake_kit)
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        calls = [pool.submit(complete) for _ in range(2)]
                        assert [call.result() for call in calls] == [{'status':'completed'}]*2
                    assert rows('SELECT sale_id,tx FROM refund_completion') == [('sale',outgoing)]
                    assert rows("SELECT status,ticket FROM sale WHERE id='sale'") == [('refunded','ticket')]
                    assert rows('SELECT status,outgoing FROM refund') == [('refunded',outgoing)]
                    revoked = rows("SELECT revoked FROM lot WHERE sale_id='sale'")
                    assert revoked[0][0] > 0
                    assert rows('SELECT status FROM allocation WHERE id=1') == [('released',)]
                    assert [rows(query) for query in unchanged_queries] == unchanged
                    assert run(args, fake_kit) == {'status':'completed'}
                    assert rows("SELECT revoked FROM lot WHERE sale_id='sale'") == revoked
            finally:
                os.chdir(previous)
