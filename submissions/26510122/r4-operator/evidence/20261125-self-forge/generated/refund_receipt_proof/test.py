import json
import sqlite3
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import patch

import httpx


def test(run, kit):
    logic = run.__globals__
    path = 'refund_receipt_fixture.sqlite3'
    seller, buyer, other = ('0x' + char * 40 for char in '123')
    incoming, fee_payment, outgoing, marker, block_hash, other_hash = ('0x' + char * 64 for char in '123456')
    shop = SimpleNamespace(name='fixture-shop', address=lambda role: {'shop': seller}[role])
    request = {'sale_id': 'sale-1'}
    shared = {'blockHash': block_hash, 'blockNumber': '0x20', 'from': seller, 'to': buyer}
    tx = dict(shared, hash=outgoing, value=hex(8040), input=marker)
    receipt = dict(shared, transactionHash=outgoing, status='0x1')
    block = {'hash': block_hash, 'number': '0x20', 'transactions': [outgoing]}
    queries = {
        'eth_chainId': ([], '0x2a'),
        'eth_getTransactionByHash': ([outgoing], tx),
        'eth_getTransactionReceipt': ([outgoing], receipt),
        'eth_getBlockByNumber': (['0x20', False], block),
    }
    calls = []

    def respond(req):
        calls.append(req.method)
        if req.method == 'GET':
            assert str(req.url) == logic['CHAIN_FACTS']
            return httpx.Response(200, json={'rpc': logic['RPC'], 'chain_id': 42})
        assert req.method == 'POST' and str(req.url) == logic['RPC']
        query = json.loads(req.content)
        params, result = queries[query['method']]
        assert query['params'] == params
        return httpx.Response(200, json={'jsonrpc': '2.0', 'id': query['id'], 'result': result})

    with closing(sqlite3.connect(path)) as db, httpx.Client(transport=httpx.MockTransport(respond)) as client:
        db.execute('CREATE TABLE identity(singleton INTEGER PRIMARY KEY, shop TEXT, wallet TEXT)')
        db.execute('CREATE TABLE sale(id TEXT PRIMARY KEY, owner TEXT, unit TEXT, sku TEXT, base INTEGER, cost INTEGER, price INTEGER, discount INTEGER, spent INTEGER, ticket TEXT, shop_url TEXT, wallet TEXT, created REAL, digest TEXT, jwt TEXT, expected_wei TEXT, fee_wei TEXT, gas_cap_wei TEXT, fee_wallet TEXT, grade TEXT, status TEXT, market_order TEXT, payment TEXT, fee_payment TEXT, payer TEXT, settled REAL, broken REAL)')
        db.execute('CREATE TABLE refund(sale_id TEXT PRIMARY KEY, incoming TEXT, payer TEXT, wei TEXT, marker TEXT, transfer_wei TEXT, fee_wei TEXT, gas_wei TEXT, fee_payment TEXT, reason TEXT, status TEXT, outgoing TEXT, requested REAL)')
        db.execute('INSERT INTO identity VALUES(1, ?, ?)', (shop.name, seller))
        db.execute('INSERT INTO sale(id, wallet, payer, payment, fee_payment, expected_wei, fee_wei, gas_cap_wei, status) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)', ('sale-1', seller, buyer, incoming, fee_payment, '7800', '200', '40', 'missing'))
        db.execute('INSERT INTO refund VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', ('sale-1', incoming, buyer, '8040', marker, '7800', '200', '40', fee_payment, 'fixture', 'pending_unknown', outgoing, 100.0))
        db.commit()
        original = db.execute('SELECT * FROM refund').fetchall()

        def check(reason):
            assert run(request, shop) == {'status': 'unverified', 'reason': reason}

        with patch.dict(logic, {'DB': path}), patch.object(httpx, 'get', client.get), patch.object(httpx, 'post', client.post):
            assert run(request, shop) == {'status': 'refund_receipt_verified'}
            assert run(request, shop) == {'status': 'refund_receipt_verified'}
            assert db.execute('SELECT * FROM refund').fetchall() == original
            assert db.execute('SELECT status FROM sale').fetchone() == ('missing',)
            assert run(dict(request, refund_tx=other_hash), shop)['reason'] == 'invalid_request'
            with patch.dict(tx, {'to': other}), patch.dict(receipt, {'to': other}):
                check('refund_transfer_mismatch')
            with patch.dict(tx, {'from': other}), patch.dict(receipt, {'from': other}):
                check('refund_transfer_mismatch')
            with patch.dict(tx, {'input': other_hash}):
                check('refund_transfer_mismatch')
            with patch.dict(tx, {'value': hex(8041)}):
                check('refund_transfer_mismatch')
            with patch.dict(receipt, {'status': '0x0'}):
                check('refund_receipt_unsuccessful')
            with patch.dict(queries, {'eth_getTransactionReceipt': ([outgoing], None)}):
                check('refund_receipt_unavailable')
            with patch.dict(block, {'hash': other_hash}):
                check('refund_block_unverified')
            with patch.dict(block, {'transactions': []}):
                check('refund_block_unverified')
            with patch.dict(queries, {'eth_chainId': ([], '0x2b')}):
                check('chain_mismatch')
            db.execute('UPDATE refund SET outgoing=NULL')
            db.commit()
            before = len(calls)
            check('recorded_refund_hash_unavailable')
            assert len(calls) == before
            db.execute('UPDATE refund SET outgoing=?, status=?', (outgoing, 'requested'))
            db.commit()
            check('refund_attempt_unavailable')
            db.execute('UPDATE refund SET status=?, gas_wei=?, wei=?', ('sending', '41', '8041'))
            db.commit()
            check('refund_attempt_amount_mismatch')
            db.execute('UPDATE refund SET gas_wei=?, wei=?', ('40', '8040'))
            db.execute('INSERT INTO refund(sale_id, marker) VALUES(?, ?)', ('other-sale', marker.upper().replace('0X', '0x')))
            db.commit()
            check('refund_attempt_link_ambiguous')
            db.execute('DELETE FROM refund WHERE sale_id=?', ('other-sale',))
            db.execute('INSERT INTO sale(id, payment) VALUES(?, ?)', ('other-sale', incoming))
            db.commit()
            check('refund_attempt_link_ambiguous')
            assert len(calls) == before
            with patch.dict(logic, {'DB': path + '.absent'}):
                check('ledger_unavailable')
