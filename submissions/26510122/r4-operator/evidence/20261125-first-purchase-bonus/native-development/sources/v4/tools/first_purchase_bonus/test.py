import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Event
from unittest.mock import patch

START = 1_795_604_500
NOW = START + 20.875
LOT_SECONDS = 604800
ROOT = Path('state/r4-benefits')
POLICY = ROOT / 'first-purchase-bonus-policy.json'
DATABASE = ROOT / 'benefits.sqlite3'
SCHEMA = '''
CREATE TABLE sale (id TEXT PRIMARY KEY, owner TEXT, base INTEGER, status TEXT,
                   payer TEXT, payment TEXT, market_order TEXT, settled REAL);
CREATE TABLE event (id TEXT PRIMARY KEY, at REAL, kind TEXT, reference TEXT, details TEXT);
CREATE TABLE lot (sale_id TEXT PRIMARY KEY, owner TEXT, amount INTEGER, expires REAL, revoked REAL);
CREATE TABLE allocations (id TEXT PRIMARY KEY, sale_id TEXT, amount INTEGER, state TEXT);
INSERT INTO allocations VALUES ('usage', 'existing', 1, 'spent'),
                               ('hold', 'existing', 2, 'reserved'),
                               ('debt', 'existing', 3, 'debt'),
                               ('cancel', 'existing', 4, 'cancelled');
'''


def _policy(**changes):
    settings = dict(enabled=True, id='fixture', start=START, end=START + 3600, lifetime_budget=50000)
    settings.update(changes)
    POLICY.write_text(json.dumps(settings), encoding='utf-8')
    POLICY.chmod(0o600)


def _exec(sql, args=()):
    with closing(sqlite3.connect(DATABASE)) as db, db:
        return db.execute(sql, args).fetchall()


def _wallet(number):
    return '0x' + format(number, '040x')


def _sale(sid, wallet, base, *, settled=START + 1.25, status='settled', event=True,
          payment='0x' + 'a' * 64, expiry_adjustment=0, revoked=None, make_lot=None):
    order = 'order-' + sid
    owner = 'right-' + sid
    with closing(sqlite3.connect(DATABASE)) as db, db:
        db.execute('INSERT INTO sale VALUES (?,?,?,?,?,?,?,?)',
                   (sid, owner, base, status, wallet, payment, order, settled))
        if event:
            db.execute('INSERT INTO event VALUES (?,?,?,?,?)',
                       ('event-' + sid, settled, 'settled_and_earned', sid,
                        json.dumps({'order': order, 'earned': base // 100})))
        if settled is not None and (base >= 100 if make_lot is None else make_lot):
            db.execute('INSERT INTO lot VALUES (?,?,?,?,?)',
                       (sid, owner, base // 100, settled + LOT_SECONDS + expiry_adjustment, revoked))


def _snapshot():
    with closing(sqlite3.connect(DATABASE)) as db:
        return '\n'.join(db.iterdump())


def _history_checks(check):
    problems = (
        ('missing', None, ()),
        ('wrong_ref', "UPDATE event SET reference = 'unrelated-sale' WHERE reference = ?", ()),
        ('wrong_amount', 'UPDATE event SET details = ? WHERE reference = ?',
         (json.dumps({'order': 'order-history-wrong_amount', 'earned': 2}),)),
        ('duplicate', "INSERT INTO event SELECT 'fixture-extra-event', at, kind, reference, details FROM event WHERE reference = ?", ()),
        ('bad_payment', "UPDATE sale SET payment = 'receipt' WHERE id = ?", ()),
    )
    for number, (problem, sql, params) in enumerate(problems, start=0xBA):
        previous = 'history-' + problem
        candidate = 'candidate-' + problem
        _sale(previous, _wallet(number), 100, settled=START + 0.125,
              status='refunded', revoked=NOW, event=sql is not None)
        if sql is not None:
            _exec(sql, (*params, previous))
        _sale(candidate, '0x' + _wallet(number)[2:].upper(), 100)
        before = _snapshot()
        check(candidate, 'unverified_history')
        assert _snapshot() == before, problem
    assert not _exec("SELECT 1 FROM sqlite_master WHERE name = 'welcome_award'")


def _policy_lock_checks(check):
    connect = sqlite3.connect
    for replacement in (None, {'enabled': False}, {'id': 'changed-while-waiting'}):
        entered = Event()

        class ObservedConnection(sqlite3.Connection):
            def execute(self, sql, parameters=()):
                if sql == 'BEGIN IMMEDIATE':
                    entered.set()
                return super().execute(sql, parameters)

        def observed_connect(*args, **kwargs):
            return connect(*args, factory=ObservedConnection, **kwargs)

        _policy(id='renamed', start=START + 0.5)
        before = _snapshot()
        with closing(connect(DATABASE)) as holder, ThreadPoolExecutor(max_workers=1) as pool:
            holder.execute('BEGIN IMMEDIATE')
            try:
                with patch.object(sqlite3, 'connect', observed_connect):
                    result = pool.submit(check, 'atomic', 'inactive')
                    try:
                        assert entered.wait(timeout=3)
                        if replacement is None:
                            POLICY.unlink()
                        else:
                            _policy(**replacement)
                    finally:
                        holder.rollback()
                    result.result(timeout=6)
            finally:
                holder.rollback()
        assert _snapshot() == before
    _policy(id='renamed', start=START + 0.5)


def _test(run, kit):
    def call(sid):
        return run({'sale_id': sid}, kit)

    def check(sid, status, credits=None):
        expected = {'status': status}
        if credits is not None:
            expected['credits'] = credits
        actual = call(sid)
        assert actual == expected, (sid, expected, actual)

    check('absent', 'inactive')
    _policy()
    check('absent', 'unavailable')
    assert not DATABASE.exists()
    with closing(sqlite3.connect(DATABASE)) as db, db:
        db.executescript(SCHEMA)
    DATABASE.chmod(0o600)
    _policy(end=START + 72 * 3600 + 0.125)
    check('absent', 'inactive')
    _policy(end=START + 72 * 3600)
    check('absent', 'ineligible')
    for changes in ({'extra': True}, {'start': float('nan')}, {'start': False},
                    {'end': float('inf')}, {'lifetime_budget': 50001}):
        _policy(**changes)
        check('absent', 'inactive')
    _policy()
    POLICY.chmod(0o620)
    check('absent', 'inactive')
    POLICY.chmod(0o600)
    ROOT.chmod(0o720)
    try:
        check('absent', 'inactive')
    finally:
        ROOT.chmod(0o700)
    copy = ROOT / 'policy-fixture.json'
    os.link(POLICY, copy)
    check('absent', 'inactive')
    POLICY.unlink()
    POLICY.symlink_to(copy.name)
    check('absent', 'inactive')
    POLICY.unlink()
    copy.unlink()
    _policy(start=START + 0.5)
    assert run({'sale_id': 'absent', 'proof': 'fixture'}, kit) == {'status': 'invalid_args'}
    _sale('pre', _wallet(1), 100, settled=START + 0.25, status='refunded', revoked=NOW)
    _sale('returner', _wallet(1), 100)
    check('returner', 'ineligible')
    _history_checks(check)
    _sale('never_delivered', _wallet(2), 100, settled=None, status='refunded', event=False)
    _sale('forged', _wallet(40), 100, event=False)
    check('forged', 'ineligible')
    _sale('bad_hash', _wallet(41), 100, payment='receipt')
    check('bad_hash', 'ineligible')
    _sale('bad_event', _wallet(42), 100)
    _exec('UPDATE event SET details = ? WHERE reference = ?', ('{"order":"wrong","earned":1}', 'bad_event'))
    check('bad_event', 'ineligible')
    for number, (sid, settled) in enumerate(
            [('future', START + 20.9375), ('negative', -1), ('infinite', float('inf'))], start=43):
        _sale(sid, _wallet(number), 100, settled=settled)
        check(sid, 'ineligible')
    _sale('fractional', _wallet(2), 99, settled=START + 20.75)
    assert _exec('SELECT settled, typeof(settled) FROM sale WHERE id = ?', ('fractional',)) == [(START + 20.75, 'real')]
    _sale('later', _wallet(3), 109, settled=START + 3)
    assert _exec('SELECT settled, typeof(settled) FROM sale WHERE id = ?', ('later',)) == [(float(START + 3), 'real')]
    _sale('valid_later_same_payer', _wallet(2), 200, settled=START + 20.8)
    _policy(start=START + 0.5, end=START + 20.75)
    check('fractional', 'ineligible')
    _policy(start=START + 0.5, end=START + 20.8125)
    check('later', 'defer')
    assert not _exec("SELECT 1 FROM sqlite_master WHERE name = 'welcome_award'")
    assert _exec('SELECT amount FROM lot WHERE sale_id = ?', ('later',)) == [(1,)]
    sales = _exec('SELECT * FROM sale ORDER BY id')
    events = _exec('SELECT * FROM event ORDER BY rowid')
    allocations = _exec('SELECT * FROM allocations ORDER BY id')
    other_lots = _exec("SELECT * FROM lot WHERE sale_id != 'later' ORDER BY sale_id")
    check('fractional', 'granted', 4)
    check('later', 'granted', 5)
    check('valid_later_same_payer', 'already_awarded')
    assert _exec('SELECT amount, expires, typeof(expires) FROM lot WHERE sale_id = ?', ('fractional',)) == [(4, START + 20.75 + LOT_SECONDS, 'real')]
    assert _exec('SELECT amount, expires, typeof(expires) FROM lot WHERE sale_id = ?', ('later',)) == [(6, START + 3.0 + LOT_SECONDS, 'real')]
    assert _exec('SELECT * FROM sale ORDER BY id') == sales
    assert _exec('SELECT * FROM event ORDER BY rowid') == events
    assert _exec('SELECT * FROM allocations ORDER BY id') == allocations
    assert _exec("SELECT * FROM lot WHERE sale_id NOT IN ('later', 'fractional') ORDER BY sale_id") == other_lots
    _sale('repeat', _wallet(2), 200)
    check('fractional', 'already_awarded')
    _exec("UPDATE sale SET status = 'refunded' WHERE id = 'fractional'")
    _exec("UPDATE lot SET revoked = ? WHERE sale_id = 'fractional'", (NOW,))
    _policy(id='renamed', start=START + 0.5)
    check('repeat', 'already_awarded')
    assert _exec("SELECT amount FROM welcome_award WHERE sale_id = 'fractional'") == [(4,)]
    _sale('refunded_first', _wallet(4), 100, status='refunded', revoked=NOW)
    _sale('refunded_returner', _wallet(4), 100)
    check('refunded_first', 'ineligible')
    check('refunded_returner', 'ineligible')
    _sale('expiry_mismatch', _wallet(5), 100, expiry_adjustment=0.0005)
    check('expiry_mismatch', 'ineligible')
    _sale('revoked', _wallet(6), 100, revoked=NOW)
    check('revoked', 'ineligible')
    _sale('tiny', _wallet(7), 19)
    check('tiny', 'ineligible')
    _sale('zero_lot', _wallet(8), 20, make_lot=True)
    check('zero_lot', 'granted', 1)
    _sale('missing_basic', _wallet(9), 200, make_lot=False)
    check('missing_basic', 'ineligible')
    _sale('cap', _wallet(10), 100001)
    check('cap', 'granted', 5000)
    _sale('expired', _wallet(11), 100)
    _sale('pending_at_expiry', _wallet(46), 100, settled=START + 20.8125)
    expiry = START + 1.25 + LOT_SECONDS
    before = _snapshot()
    with patch.dict(run.__globals__, {'_now': lambda: expiry}):
        check('expired', 'ineligible')
        check('pending_at_expiry', 'defer')
    assert _snapshot() == before
    _exec("UPDATE lot SET revoked = ? WHERE sale_id = 'expired'", (expiry,))
    _exec("UPDATE lot SET revoked = ? WHERE sale_id = 'pending_at_expiry'", (NOW,))
    _sale('race', _wallet(0xAB), 200)
    _sale('race_right', '0x' + _wallet(0xAB)[2:].upper(), 200)
    gate = Barrier(3)

    def race(sid):
        gate.wait(timeout=5)
        return call(sid)['status']

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(race, sid) for sid in ('race', 'race', 'race_right')]
        statuses = [future.result(timeout=8) for future in futures]
    assert sorted(statuses[:2]) == ['already_awarded', 'granted']
    assert statuses[2] in ('defer', 'already_awarded')
    assert _exec('SELECT payer, sale_id, amount FROM welcome_award WHERE payer = ?', (_wallet(0xAB),)) == [(_wallet(0xAB), 'race', 10)]
    _sale('atomic', _wallet(12), 200)
    _policy_lock_checks(check)
    _exec("""CREATE TRIGGER award_fixture_fail BEFORE INSERT ON welcome_award
             WHEN NEW.sale_id = 'atomic' BEGIN SELECT RAISE(ABORT, 'fixture'); END""")
    check('atomic', 'unavailable')
    assert _exec("SELECT amount FROM lot WHERE sale_id = 'atomic'") == [(2,)]
    assert not _exec("SELECT 1 FROM welcome_award WHERE sale_id = 'atomic'")
    _exec('DROP TRIGGER award_fixture_fail')
    check('atomic', 'granted', 10)
    for number in range(20, 28):
        sid = 'budget-' + str(number)
        _sale(sid, _wallet(number), 100000)
        check(sid, 'granted', 5000)
    assert _exec('SELECT SUM(amount) FROM welcome_award') == [(45030,)]
    _sale('too_large', _wallet(30), 100000)
    check('too_large', 'budget_exhausted')
    assert _exec("SELECT amount FROM lot WHERE sale_id = 'too_large'") == [(1000,)]
    _sale('exact_rest', _wallet(31), 99400)
    check('exact_rest', 'granted', 4970)
    _policy(id='renamed-again')
    _sale('over', _wallet(32), 20)
    check('over', 'budget_exhausted')
    assert _exec('SELECT SUM(amount) FROM welcome_award') == [(50000,)]
    assert not _exec("SELECT 1 FROM lot WHERE sale_id = 'over'")
    _exec('ALTER TABLE welcome_award RENAME TO fixture_awards')
    _exec('CREATE TABLE welcome_award (payer TEXT, campaign TEXT, PRIMARY KEY (payer, campaign))')
    check('over', 'incompatible')
    assert _exec('SELECT SUM(amount) FROM fixture_awards') == [(50000,)]
    assert [row[1] for row in _exec('PRAGMA table_info(welcome_award)')] == ['payer', 'campaign']


def test(run, kit):
    assert kit.testing
    original = Path.cwd()
    fixture_parent = original / ROOT
    fixture_parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='welcome-v4-fixture-', dir=fixture_parent) as temporary:
        try:
            os.chdir(temporary)
            Path('state').mkdir(mode=0o700)
            ROOT.mkdir(mode=0o700)
            with patch.dict(run.__globals__, {'_now': lambda: NOW}):
                _test(run, kit)
        finally:
            os.chdir(original)
