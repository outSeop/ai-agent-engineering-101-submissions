from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
from threading import Barrier


def test(run, kit):
    assert kit.testing
    epoch = 2_000_000_000
    now = epoch + 10_000
    ttl = 604800
    globals_ = run.__globals__
    original_epoch = globals_['ROLLOUT_EPOCH']
    original_clock = globals_['_now']
    path = Path('state/r4-benefits/benefits.sqlite3')
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation protects any pre-existing database from the fixture.
    with path.open('xb'):
        pass
    db = None
    try:
        assert run({'sale_id': 'example'}, kit) == {'status': 'rollout_disabled'}
        globals_['ROLLOUT_EPOCH'] = epoch
        globals_['_now'] = lambda: now
        db = sqlite3.connect(path)
        db.executescript('''
            CREATE TABLE sale (id TEXT PRIMARY KEY, owner TEXT, base INTEGER, status TEXT,
                payer TEXT, payment TEXT, market_order TEXT, settled INTEGER);
            CREATE TABLE event (id TEXT PRIMARY KEY, at INTEGER, kind TEXT, reference TEXT, details TEXT);
            CREATE TABLE lot (sale_id TEXT PRIMARY KEY, owner TEXT, amount INTEGER, expires INTEGER, revoked INTEGER);
            CREATE TABLE usage (sale_id TEXT, amount INTEGER);
            CREATE TABLE reservation (sale_id TEXT, amount INTEGER);
            CREATE TABLE debt (sale_id TEXT, amount INTEGER);
            CREATE TABLE cancellation (sale_id TEXT, amount INTEGER);
            INSERT INTO usage VALUES ('first', 1);
            INSERT INTO reservation VALUES ('first', 1);
            INSERT INTO debt VALUES ('older-right', 8);
            INSERT INTO cancellation VALUES ('older-right', 4);
        ''')

        def wallet(seed):
            return '0x' + seed.rjust(40, '0')

        def sale(sale_id, payer, base=201, offset=1, status='settled', evidence='valid', owner=None, lot=True):
            owner = owner or 'right-' + sale_id
            settled = None if offset is None else epoch + offset
            order = 'order-' + sale_id
            payment = 'receipt-' + sale_id if settled is not None else None
            db.execute('INSERT INTO sale VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                       (sale_id, owner, base, status, payer, payment, order, settled))
            if evidence != 'missing' and settled is not None:
                detail = {'order': order, 'earned': base // 100}
                if evidence == 'wrong_order':
                    detail['order'] = 'other-order'
                if evidence == 'wrong_earned':
                    detail['earned'] = base // 100 + 1
                db.execute('INSERT INTO event VALUES (?, ?, ?, ?, ?)',
                           ('event-' + sale_id, settled, 'settled_and_earned', sale_id, json.dumps(detail)))
            if lot and settled is not None:
                db.execute('INSERT INTO lot VALUES (?, ?, ?, ?, ?)',
                           (sale_id, owner, base // 100, settled + ttl, settled + 1 if status == 'refunded' else None))

        sale('first', wallet('aB'), offset=5)
        sale('different-right', wallet('Ab'), offset=5)
        sale('parallel', wallet('bc'), base=219)
        sale('parallel-second', wallet('BC'), base=400, offset=2)
        sale('older-right', wallet('cd'), offset=-20, base=900)
        sale('returner', wallet('CD'))
        sale('settled-refund', wallet('de'), offset=-10, status='refunded')
        sale('after-settled-refund', wallet('DE'))
        sale('undelivered-refund', wallet('ef'), offset=None, status='refunded')
        sale('after-undelivered-refund', wallet('EF'), base=39)
        sale('receipt-only', wallet('11'), evidence='missing')
        sale('wrong-order', wallet('12'), evidence='wrong_order')
        sale('wrong-earned', wallet('13'), evidence='wrong_earned')
        sale('expired', wallet('14'), offset=10_000 - ttl)
        sale('fresh-after-expired', wallet('14'))
        sale('revoked', wallet('15'))
        sale('wrong-lot-owner', wallet('16'))
        sale('depleted-lot', wallet('17'))
        sale('wrong-expiry', wallet('18'))
        sale('zero-bonus', wallet('19'), base=19)
        sale('missing-zero-lot', wallet('20'), base=39, lot=False)
        sale('rollback', wallet('21'))
        db.execute("UPDATE lot SET revoked = ? WHERE sale_id = 'revoked'", (now,))
        db.execute("UPDATE lot SET owner = 'unrelated-right' WHERE sale_id = 'wrong-lot-owner'")
        db.execute("UPDATE lot SET amount = 1 WHERE sale_id = 'depleted-lot'")
        db.execute("UPDATE lot SET expires = expires + 1 WHERE sale_id = 'wrong-expiry'")
        db.commit()

        def snapshot(table):
            return db.execute('SELECT * FROM ' + table + ' ORDER BY rowid').fetchall()

        def call(sale_id):
            return run({'sale_id': sale_id}, kit)

        assert run({}, kit) == {'status': 'no_sale_id'}
        for extra in ('payer', 'proof', 'metadata', 'buyer', 'bearer'):
            assert run({'sale_id': 'first', extra: 'synthetic'}, kit) == {'status': 'invalid_args'}
        for invalid in (None, '', '  ', 4, ['first']):
            assert call(invalid) == {'status': 'invalid_args'}

        stable_tables = ('sale', 'event', 'usage', 'reservation', 'debt', 'cancellation')
        stable = {table: snapshot(table) for table in stable_tables}
        lots_before = {row[0]: row for row in snapshot('lot')}
        total_before = sum(row[2] for row in lots_before.values())
        assert call('different-right') == {'status': 'returning_payer'}
        assert call('first') == {'status': 'granted', 'bonus': 10}
        assert call('first') == {'status': 'already_granted'}
        assert call('older-right') == {'status': 'before_rollout'}
        assert call('returner') == {'status': 'returning_payer'}
        assert call('settled-refund') == {'status': 'ineligible_sale'}
        assert call('after-settled-refund') == {'status': 'returning_payer'}
        assert call('after-undelivered-refund') == {'status': 'granted', 'bonus': 1}
        for forged in ('receipt-only', 'wrong-order', 'wrong-earned'):
            assert call(forged) == {'status': 'unverified_settlement'}
        assert call('expired') == {'status': 'before_rollout'}
        assert call('fresh-after-expired') == {'status': 'returning_payer'}
        globals_['_now'] = lambda: epoch + ttl + 5
        assert call('first') == {'status': 'expired'}
        globals_['_now'] = lambda: now
        for invalid_lot in ('revoked', 'wrong-lot-owner', 'depleted-lot', 'wrong-expiry', 'missing-zero-lot'):
            assert call(invalid_lot) == {'status': 'ineligible_lot'}
        assert call('zero-bonus') == {'status': 'granted', 'bonus': 0}
        assert call('zero-bonus') == {'status': 'already_granted'}

        barrier = Barrier(6, timeout=5)

        def concurrent_call(sale_id):
            barrier.wait()
            return call(sale_id)

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(concurrent_call, ['parallel', 'parallel-second'] * 3))
        assert results.count({'status': 'granted', 'bonus': 10}) == 1
        assert results.count({'status': 'already_granted'}) == 2
        assert results.count({'status': 'returning_payer'}) == 3

        db.executescript('''CREATE TRIGGER fail_lot_update BEFORE UPDATE ON lot
            WHEN NEW.sale_id = 'rollback' BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END;''')
        assert call('rollback') == {'status': 'storage_error'}
        assert db.execute("SELECT 1 FROM first_purchase_bonus_grant WHERE sale_id = 'rollback'").fetchone() is None
        assert db.execute("SELECT amount FROM lot WHERE sale_id = 'rollback'").fetchone() == (2,)
        db.execute('DROP TRIGGER fail_lot_update')
        db.commit()
        assert call('rollback') == {'status': 'granted', 'bonus': 10}

        assert {table: snapshot(table) for table in stable_tables} == stable
        lots_after = {row[0]: row for row in snapshot('lot')}
        assert lots_after.keys() == lots_before.keys()
        bonuses = {'first': 10, 'parallel': 10, 'after-undelivered-refund': 1, 'rollback': 10}
        for sale_id, before in lots_before.items():
            assert lots_after[sale_id] == (*before[:2], before[2] + bonuses.get(sale_id, 0), *before[3:])
        assert sum(row[2] for row in lots_after.values()) == total_before + sum(bonuses.values())
        assert db.execute("SELECT payer, amount, granted_at, earned_event_id FROM first_purchase_bonus_grant WHERE sale_id = 'first'").fetchone() == (wallet('ab'), 10, now, 'event-first')
        assert db.execute('SELECT COUNT(*) FROM first_purchase_bonus_grant').fetchone() == (5,)

        # Simulate the existing refund writer revoking the full linked lot.
        db.execute("UPDATE sale SET status = 'refunded' WHERE id = 'first'")
        db.execute("UPDATE lot SET revoked = ? WHERE sale_id = 'first'", (now,))
        db.commit()
        assert db.execute("SELECT amount FROM lot WHERE sale_id = 'first' AND revoked = ?", (now,)).fetchone() == (12,)
        assert db.execute("SELECT amount FROM lot WHERE sale_id = 'first' AND revoked IS NULL").fetchone() is None
        assert call('first') == {'status': 'ineligible_sale'}
        assert call('different-right') == {'status': 'returning_payer'}
        assert db.execute("SELECT COUNT(*) FROM first_purchase_bonus_grant WHERE payer = ?", (wallet('ab'),)).fetchone() == (1,)
    finally:
        globals_['ROLLOUT_EPOCH'] = original_epoch
        globals_['_now'] = original_clock
        if db is not None:
            db.close()
        path.unlink()
