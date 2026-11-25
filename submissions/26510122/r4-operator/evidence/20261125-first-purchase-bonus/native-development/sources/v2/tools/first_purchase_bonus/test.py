import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier

START = 1800000000
DAY = 86400
WEEK = DAY * 7


def _wallet(index):
    return '0x' + format(index, '040x')


def _fixture(path):
    with sqlite3.connect(path) as db:
        db.executescript('''
          CREATE TABLE sale (id TEXT PRIMARY KEY, owner TEXT, base INTEGER, status TEXT,
                             payer TEXT, payment TEXT, market_order TEXT, settled INTEGER);
          CREATE TABLE event (id INTEGER PRIMARY KEY, at INTEGER, kind TEXT, reference TEXT, details TEXT);
          CREATE TABLE lot (sale_id TEXT PRIMARY KEY, owner TEXT, amount INTEGER, expires INTEGER, revoked INTEGER);
          CREATE TABLE allocations (sale_id TEXT, amount INTEGER);
          CREATE TABLE reservations (sale_id TEXT, amount INTEGER);
          CREATE TABLE debt (sale_id TEXT, amount INTEGER);
          CREATE TABLE cancellations (sale_id TEXT, amount INTEGER);
        ''')


def _sale(db, name, index, base=200, settled=START, status='settled',
          event=True, earned=None, order=None, payer=None, lot=True, revoked=None):
    owner = 'right-' + name
    market_order = 'order-' + name
    db.execute('INSERT INTO sale VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
               (name, owner, base, status, payer or _wallet(index), 'payment-' + name,
                market_order, settled))
    if event:
        details = {'order': order if order is not None else market_order,
                   'earned': base // 100 if earned is None else earned}
        db.execute("INSERT INTO event VALUES (NULL, ?, 'settled_and_earned', ?, ?)",
                   (settled, name, json.dumps(details)))
    if lot and settled is not None:
        db.execute('INSERT INTO lot VALUES (?, ?, ?, ?, ?)',
                   (name, owner, base // 100, settled + WEEK, revoked))


def test(run, kit):
    assert kit.testing
    scope = run.__globals__
    original = {key: scope[key] for key in ('POLICY_PATH', 'DB_URI', '_now')}
    parent = Path('state/r4-benefits')
    parent.mkdir(parents=True, exist_ok=True)
    try:
        with TemporaryDirectory(prefix='bonus-fixture-', dir=parent) as temporary:
            root = Path(temporary).resolve()
            policy_path = root / 'first-purchase-bonus-policy.json'
            scope['POLICY_PATH'] = policy_path
            scope['_now'] = lambda: START + 3 * DAY

            def fresh(name):
                path = root / (name + '.sqlite3')
                _fixture(path)
                scope['DB_URI'] = path.as_uri() + '?mode=rw'
                return path

            def policy(**changes):
                value = dict(enabled=True, id='welcome', start=START, end=START + 72 * 3600,
                             lifetime_budget=50000)
                value.update(changes)
                policy_path.write_text(json.dumps(value), encoding='utf-8')

            def call(name):
                return run({'sale_id': name}, kit)

            def snapshot(db, table):
                return db.execute('SELECT * FROM ' + table + ' ORDER BY rowid').fetchall()

            path = fresh('eligibility')
            with sqlite3.connect(path) as db:
                _sale(db, 'first', 171, 255, payer='0X' + '0' * 38 + 'AB')
                _sale(db, 'same-payer', 171)
                _sale(db, 'void-first', 172, settled=None, status='refunded', event=False)
                _sale(db, 'no-basic', 172, 39, lot=False)
                _sale(db, 'zero-basic-lot', 173, 59)
                _sale(db, 'zero-bonus', 174, 19, lot=False)
                _sale(db, 'legacy', 175, settled=START - 1)
                _sale(db, 'returner', 175)
                _sale(db, 'refunded-first', 176, settled=START - 1, status='refunded', revoked=START)
                _sale(db, 'after-refund', 176)
                _sale(db, 'no-event', 177, event=False)
                _sale(db, 'bad-earned', 178, earned=3)
                _sale(db, 'bad-order', 179, order='forged')
                _sale(db, 'duplicate-event', 180)
                db.execute("INSERT INTO event SELECT NULL, at, kind, reference, details FROM event WHERE reference='duplicate-event'")
                _sale(db, 'revoked', 181, revoked=START + 1)
                _sale(db, 'refunded', 182, status='refunded', revoked=START + 1)
                _sale(db, 'boundary', 183, settled=START + 3 * DAY)
                _sale(db, 'wrong-expiry', 184)
                db.execute("UPDATE lot SET expires=expires+1 WHERE sale_id='wrong-expiry'")
                _sale(db, 'wrong-owner', 185)
                db.execute("UPDATE lot SET owner='other' WHERE sale_id='wrong-owner'")
                _sale(db, 'wrong-amount', 186)
                db.execute("UPDATE lot SET amount=amount+1 WHERE sale_id='wrong-amount'")
                _sale(db, 'bad-payer', 187, payer='customer-nickname')
                _sale(db, 'missing-payment', 188)
                db.execute("UPDATE sale SET payment=NULL WHERE id='missing-payment'")
                _sale(db, 'missing-positive-lot', 189, lot=False)
                preserved_tables = ('sale', 'event', 'allocations', 'reservations', 'debt', 'cancellations')
                for table in preserved_tables[2:]:
                    db.execute('INSERT INTO ' + table + ' VALUES (?, ?)', ('first', 1))
                before = {table: snapshot(db, table) for table in preserved_tables}
                before_lots = dict((row[0], row[1:]) for row in snapshot(db, 'lot'))
            assert run({}, kit) == {'status': 'no_sale_id'}
            assert run({'sale_id': 'first', 'proof': 'forged'}, kit) == {'status': 'invalid_args'}
            assert call('first') == {'status': 'inactive'}
            policy(end=START + 72 * 3600 + 1)
            assert call('first')['status'] == 'inactive'
            policy(lifetime_budget=50001)
            assert call('first')['status'] == 'inactive'
            policy(extra='unexpected')
            assert call('first')['status'] == 'inactive'
            policy(start=float('inf'))
            assert call('first')['status'] == 'inactive'
            policy(enabled=False)
            assert call('first')['status'] == 'inactive'
            policy_path.write_text('{"enabled":true,"enabled":false}', encoding='utf-8')
            assert call('first')['status'] == 'inactive'
            policy_path.write_text('broken JSON', encoding='utf-8')
            assert call('first')['status'] == 'inactive'
            with sqlite3.connect(path) as db:
                assert db.execute("SELECT count(*) FROM sqlite_master WHERE name='welcome_award'").fetchone()[0] == 0
                assert dict((row[0], row[1:]) for row in snapshot(db, 'lot')) == before_lots
            policy()
            assert call('no-basic')['status'] == 'deferred'
            assert call('first') == {'status': 'awarded', 'credits': 12}
            assert call('first')['status'] == 'already_awarded'
            policy(id='renamed')
            assert call('same-payer')['status'] == 'already_awarded'
            assert call('no-basic') == {'status': 'awarded', 'credits': 1}
            assert call('zero-basic-lot') == {'status': 'awarded', 'credits': 2}
            expected = {
                'zero-bonus': 'zero_bonus', 'legacy': 'outside_rollout',
                'returner': 'returning_payer', 'after-refund': 'returning_payer',
                'no-event': 'unverified_settlement', 'bad-earned': 'unverified_settlement',
                'bad-order': 'unverified_settlement', 'duplicate-event': 'unverified_settlement',
                'revoked': 'ineligible_lot', 'refunded': 'ineligible_sale',
                'boundary': 'outside_rollout', 'wrong-expiry': 'ineligible_lot',
                'wrong-owner': 'ineligible_lot', 'wrong-amount': 'ineligible_lot',
                'bad-payer': 'unverified_settlement', 'missing-payment': 'unverified_settlement',
                'missing-positive-lot': 'ineligible_lot',
            }
            for name, status in expected.items():
                assert call(name) == {'status': status}, name
            with sqlite3.connect(path) as db:
                assert {table: snapshot(db, table) for table in preserved_tables} == before
                after_lots = dict((row[0], row[1:]) for row in snapshot(db, 'lot'))
                assert after_lots.pop('no-basic') == ('right-no-basic', 1, START + WEEK, None)
                before_lots['first'] = ('right-first', 14, START + WEEK, None)
                before_lots['zero-basic-lot'] = ('right-zero-basic-lot', 2, START + WEEK, None)
                assert after_lots == before_lots
                assert db.execute("SELECT payer, amount FROM welcome_award WHERE sale_id='first'").fetchone() == (_wallet(171), 12)
                db.execute("UPDATE sale SET status='refunded' WHERE id='first'")
                db.execute("UPDATE lot SET revoked=? WHERE sale_id='first'", (START + DAY,))
                assert db.execute("SELECT amount FROM lot WHERE sale_id='first'").fetchone() == (14,)
            assert call('same-payer')['status'] == 'already_awarded'
            assert call('first')['status'] == 'ineligible_sale'

            path = fresh('expiry')
            with sqlite3.connect(path) as db:
                _sale(db, 'expires', 201, 100, settled=START)
                _sale(db, 'still-valid', 202, 100, settled=START + 1)
            scope['_now'] = lambda: START + WEEK
            assert call('expires')['status'] == 'expired'
            assert call('still-valid') == {'status': 'awarded', 'credits': 5}
            scope['_now'] = lambda: START + 3 * DAY

            path = fresh('budget')
            with sqlite3.connect(path) as db:
                for index in range(9):
                    _sale(db, 'cap-' + str(index), 300 + index, 500000)
                _sale(db, 'partial-capacity', 310, 99980)
                _sale(db, 'needs-two', 311, 40, lot=False)
                _sale(db, 'last-credit', 312, 20, lot=False)
                _sale(db, 'over-budget', 313, 20, lot=False)
            assert call('cap-1')['status'] == 'deferred'
            for index in range(9):
                assert call('cap-' + str(index)) == {'status': 'awarded', 'credits': 5000}
            assert call('last-credit')['status'] == 'deferred'
            assert call('partial-capacity') == {'status': 'awarded', 'credits': 4999}
            assert call('needs-two')['status'] == 'insufficient_budget'
            assert call('last-credit') == {'status': 'awarded', 'credits': 1}
            policy(id='new-promotion')
            assert call('over-budget')['status'] == 'insufficient_budget'
            with sqlite3.connect(path) as db:
                assert db.execute('SELECT SUM(amount) FROM welcome_award').fetchone() == (50000,)
                assert db.execute("SELECT count(*) FROM lot WHERE sale_id='needs-two'").fetchone() == (0,)
                db.execute("UPDATE sale SET status='refunded' WHERE id='last-credit'")
                db.execute("UPDATE lot SET revoked=? WHERE sale_id='last-credit'", (START + DAY,))
            assert call('over-budget')['status'] == 'insufficient_budget'

            path = fresh('concurrent')
            with sqlite3.connect(path) as db:
                _sale(db, 'append-first', 400, settled=START + 2)
                _sale(db, 'append-second', 401, settled=START + 1)
                _sale(db, 'same-right-holder', 400, settled=START)
            assert call('append-second')['status'] == 'deferred'
            assert call('same-right-holder')['status'] == 'returning_payer'
            barrier = Barrier(4, timeout=5)

            def replay():
                barrier.wait()
                return call('append-first')['status']

            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(lambda _: replay(), range(4)))
            assert sorted(results) == ['already_awarded'] * 3 + ['awarded']
            with sqlite3.connect(path) as db:
                assert db.execute('SELECT count(*), SUM(amount) FROM welcome_award').fetchone() == (1, 10)
                assert db.execute("SELECT amount FROM lot WHERE sale_id='append-first'").fetchone() == (12,)

            path = fresh('rollback')
            with sqlite3.connect(path) as db:
                _sale(db, 'rollback', 500)
                db.execute("CREATE TRIGGER reject_lot BEFORE UPDATE ON lot BEGIN SELECT RAISE(ABORT, 'fixture'); END")
            assert call('rollback')['status'] == 'state_error'
            with sqlite3.connect(path) as db:
                assert db.execute("SELECT count(*) FROM sqlite_master WHERE name='welcome_award'").fetchone() == (0,)
                assert db.execute("SELECT amount FROM lot WHERE sale_id='rollback'").fetchone() == (2,)
                db.execute('DROP TRIGGER reject_lot')
            assert call('rollback') == {'status': 'awarded', 'credits': 10}
            with sqlite3.connect(path) as db:
                _sale(db, 'append-error', 501, 20, lot=False)
                db.execute("CREATE TRIGGER reject_award BEFORE INSERT ON welcome_award BEGIN SELECT RAISE(ABORT, 'fixture'); END")
            assert call('append-error')['status'] == 'state_error'
            with sqlite3.connect(path) as db:
                assert db.execute("SELECT count(*) FROM lot WHERE sale_id='append-error'").fetchone() == (0,)
                assert db.execute('SELECT count(*) FROM welcome_award').fetchone() == (1,)

            for name in ('welcome_award', 'first_purchase_bonus_grant'):
                path = fresh('old-' + name)
                with sqlite3.connect(path) as db:
                    _sale(db, 'old-schema', 600)
                    db.execute('CREATE TABLE ' + name + ' (payer TEXT, campaign TEXT, PRIMARY KEY(payer,campaign))')
                    db.execute('INSERT INTO ' + name + ' VALUES (?, ?)', (_wallet(600), 'old'))
                    before = tuple(db.iterdump())
                assert call('old-schema')['status'] == 'incompatible_ledger'
                with sqlite3.connect(path) as db:
                    assert tuple(db.iterdump()) == before
    finally:
        scope.update(original)
