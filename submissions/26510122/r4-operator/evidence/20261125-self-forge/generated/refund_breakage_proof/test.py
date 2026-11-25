import hashlib
import json
import sqlite3
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import patch

import httpx

FIXTURE = 'file:refund_breakage_fixture_v2.sqlite3?mode='
LEDGER = 'https://market.ourolabs.ai/api/ledger'


def test(run, kit):
    assert kit.testing
    with patch('sqlite3.connect') as database, patch('httpx.get') as network:
        assert run({'case_id': '0' * 64}, SimpleNamespace(testing=False)) == {'status': 'development_only'}
        database.assert_not_called()
        network.assert_not_called()
    connect = sqlite3.connect
    for _ in range(2):
        memory = 'file:refund_breakage_forge_test?mode=memory&cache=shared'
        with closing(connect(memory, uri=True)) as keeper:
            def connect_fixture(path, *, uri, timeout):
                assert path in (FIXTURE + 'ro', FIXTURE + 'rw') and uri and timeout == 2
                db = connect(memory, uri=True, timeout=timeout)
                if path.endswith('=ro'):
                    db.execute('PRAGMA query_only=ON')
                return db

            with patch('sqlite3.connect', side_effect=connect_fixture):
                exercise_fixture(run, kit, keeper)


def exercise_fixture(run, kit, db):
    wallet = kit.address('shop')
    sale_id, jwt, requested = 'fixture-sale', 'private-fixture-jwt', 180000.0
    historical_url = 'https://historical-shop.example/a2a'
    current_url = 'https://current-shop.example/a2a'
    order, unit = 'fixture-order', 'fixture-unit'
    fields = json.dumps([kit.name, sale_id, requested, jwt], ensure_ascii=True, separators=(',', ':'))
    case_id = hashlib.sha256(b'r4/refund-review/v1\x00' + fields.encode('ascii')).hexdigest()
    args = {'case_id': case_id}
    confirmed = {'status': 'market_breakage_confirmed', 'case_id': case_id, 'reason': 'early_market_breakage', 'period': 'within_48_hours'}
    fixture_kit = SimpleNamespace(testing=True, name=kit.name, address=kit.address, shop_url=current_url)
    with db:
        db.executescript('''
            CREATE TABLE identity(singleton INTEGER PRIMARY KEY, shop TEXT, wallet TEXT);
            CREATE TABLE sale(id TEXT PRIMARY KEY, wallet TEXT, jwt TEXT, unit TEXT, market_order TEXT, shop_url TEXT, status TEXT, settled REAL, broken REAL);
            CREATE TABLE refund(sale_id TEXT PRIMARY KEY, reason TEXT, status TEXT, requested REAL);
            CREATE TABLE scan_progress(case_id TEXT NOT NULL, binding TEXT NOT NULL, after_seq INTEGER NOT NULL, PRIMARY KEY(case_id, binding));
        ''')
        db.execute('INSERT INTO identity VALUES (1, ?, ?)', (kit.name, wallet))
        db.execute('INSERT INTO sale VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', (sale_id, wallet, jwt, unit, order, historical_url, 'settled', 1000, 173800))
        db.execute('INSERT INTO refund VALUES (?, ?, ?, ?)', (sale_id, 'early_market_breakage', 'requested', requested))

    def broken(seq, **changes):
        data = {'shop': historical_url, 'order': order, 'hours_after_sale': 48}
        data.update(changes)
        return {'seq': seq, 'kind': 'broken', 'data': data}

    decoys = [broken(3, shop=kit.name), broken(7, shop=current_url), broken(8, order='another-order')]
    earlier_pages = [decoys] + [[{'seq': i * 11, 'kind': 'supply', 'data': {}}] for i in range(1, 25)]
    pages = earlier_pages + [[broken(300, sealed='a' * 64)]]
    page_starts = [0] + [page[-1]['seq'] for page in earlier_pages]
    final_cursor = page_starts[-1]
    responses = dict(zip(page_starts, pages))
    seen = []

    def ledger(url, *, params, timeout):
        assert url == LEDGER and timeout == 2 and set(params) == {'after'}
        after = params['after']
        seen.append(after)
        return httpx.Response(200, request=httpx.Request('GET', url, params=params), json=responses[after])

    with patch('httpx.get', side_effect=ledger):
        assert run(args, fixture_kit) == {'status': 'pagination_incomplete'}
        assert seen == page_starts[:12]
        assert run(args, fixture_kit) == {'status': 'pagination_incomplete'}
        assert seen == page_starts[:24]
        assert run(args, fixture_kit) == confirmed
        assert seen == page_starts
        assert run(args, fixture_kit) == confirmed
        assert seen == page_starts + [final_cursor]

    for candidate, status in [
        (broken(300), 'market_breakage_confirmed'),
        (broken(300, unit=unit), 'market_breakage_confirmed'),
        (broken(300, unit='different-unit'), 'market_breakage_unverified'),
        (broken(300, hours_after_sale=48.01), 'market_breakage_unverified'),
        (broken(300, hours_after_sale=True), 'market_breakage_unverified'),
        (broken(final_cursor), 'market_evidence_unavailable'),
    ]:
        responses[final_cursor] = [candidate]
        with patch('httpx.get', side_effect=ledger):
            assert run(args, fixture_kit)['status'] == status

    responses[final_cursor] = [broken(300), broken(299)]
    with patch('httpx.get', side_effect=ledger):
        assert run(args, fixture_kit) == {'status': 'market_evidence_unavailable'}
    responses[final_cursor] = []
    with patch('httpx.get', side_effect=ledger):
        assert run(args, fixture_kit) == {'status': 'market_breakage_unverified'}
    with patch('httpx.get', side_effect=httpx.ReadTimeout('fixture timeout')) as network:
        assert run(args, fixture_kit) == {'status': 'market_evidence_unavailable'}
        network.assert_called_once_with(LEDGER, params={'after': final_cursor}, timeout=2)
    responses[final_cursor] = [broken(300)]
    with patch('httpx.get', side_effect=ledger):
        seen.clear()
        assert run(args, fixture_kit) == confirmed
        assert seen == [final_cursor]

    with db:
        assert db.execute('SELECT status FROM refund').fetchone() == ('requested',)
        assert db.execute('SELECT status, shop_url FROM sale').fetchone() == ('settled', historical_url)
        db.execute('UPDATE sale SET settled=1001')
    with patch('httpx.get', side_effect=ledger):
        seen.clear()
        assert run(args, fixture_kit) == {'status': 'pagination_incomplete'}
        assert seen == page_starts[:12]
    with db:
        db.execute('UPDATE sale SET settled=1000, broken=173801')
    with patch('httpx.get') as network:
        assert run(args, fixture_kit) == {'status': 'local_breakage_unverified'}
        network.assert_not_called()
