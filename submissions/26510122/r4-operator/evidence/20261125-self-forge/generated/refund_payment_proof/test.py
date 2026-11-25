import hashlib
import json
import sqlite3
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import patch

import httpx


def test(run, kit):
    namespace = run.__globals__
    path = 'refund_payment_fixture.sqlite3'
    shop = '0x' + '1' * 40
    buyer = '0x' + '2' * 40
    market = '0x' + '3' * 40
    outsider = '0x' + '4' * 40
    payment = '0x' + '1' * 64
    fee_payment = '0x' + '2' * 64
    block = '0x' + '3' * 64
    checkout = 'fixture.checkout.bytes'
    data = '0x' + hashlib.sha256(checkout.encode('ascii')).hexdigest()
    facts = {'rpc': namespace['RPC'], 'chain_id': 42, 'credit_wei': 10, 'market_fee_bps': 100, 'network_fee_credits': 420, 'market_address': market}
    fixture_shop = SimpleNamespace(name='fixture-shop', address=lambda role: {'shop': shop}[role])
    request = {'sale_id': 'sale-1'}
    calls = []

    def transfer(tx_hash, recipient, amount, gas):
        fields = {'blockHash': block, 'blockNumber': '0x20', 'from': buyer, 'to': recipient}
        tx = dict(fields, hash=tx_hash, value=hex(amount), input=data)
        receipt = dict(fields, transactionHash=tx_hash, gasUsed=hex(gas), effectiveGasPrice='0x2', status='0x1')
        return tx, receipt

    tx, receipt = transfer(payment, shop, 7800, 10)
    fee_tx, fee_receipt = transfer(fee_payment, market, 200, 15)
    transactions = {payment: tx, fee_payment: fee_tx}
    receipts = {payment: receipt, fee_payment: fee_receipt}

    def handle(http_request):
        if http_request.method == 'GET':
            assert str(http_request.url) == namespace['CHAIN_FACTS']
            return httpx.Response(200, json=facts)
        assert http_request.method == 'POST' and str(http_request.url) == namespace['RPC']
        query = json.loads(http_request.content)
        method, params = query['method'], query['params']
        calls.append((method, params))
        if method == 'eth_chainId':
            assert params == []
            result = '0x2a'
        else:
            assert len(params) == 1
            result = {'eth_getTransactionByHash': transactions, 'eth_getTransactionReceipt': receipts}[method].get(params[0])
        return httpx.Response(200, json={'jsonrpc': '2.0', 'id': query['id'], 'result': result})

    with closing(sqlite3.connect(path)) as db, httpx.Client(transport=httpx.MockTransport(handle)) as client:
        db.execute('CREATE TABLE identity(singleton INTEGER PRIMARY KEY, shop TEXT, wallet TEXT)')
        db.execute('CREATE TABLE sale(id TEXT PRIMARY KEY, owner TEXT, unit TEXT, sku TEXT, base INTEGER, cost INTEGER, price INTEGER, discount INTEGER, spent INTEGER, ticket TEXT, shop_url TEXT, wallet TEXT, created REAL, digest TEXT, jwt TEXT, expected_wei TEXT, fee_wei TEXT, gas_cap_wei TEXT, fee_wallet TEXT, grade TEXT, status TEXT, market_order TEXT, payment TEXT, fee_payment TEXT, payer TEXT, settled REAL, broken REAL)')
        db.execute('INSERT INTO identity VALUES(1, ?, ?)', (fixture_shop.name, shop))
        db.execute('INSERT INTO sale(id, wallet, payer, payment, fee_payment, jwt, digest, status, price, expected_wei, fee_wei, gas_cap_wei, fee_wallet) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', ('sale-1', shop, buyer, payment, fee_payment, checkout, data, 'missing', 1000, '7800', '200', '40', market))
        db.commit()
        db.row_factory = sqlite3.Row

        def check(reason):
            assert run(request, fixture_shop) == {'status': 'unverified', 'reason': reason}

        with patch.dict(namespace, {'DB': path}), patch.object(httpx, 'get', client.get), patch.object(httpx, 'post', client.post):
            assert run(request, fixture_shop) == {'status': 'payment_evidence_verified'}
            assert calls == [('eth_chainId', []), ('eth_getTransactionByHash', [payment]), ('eth_getTransactionReceipt', [payment]), ('eth_getTransactionByHash', [fee_payment]), ('eth_getTransactionReceipt', [fee_payment])]
            sale = dict(db.execute('SELECT * FROM sale').fetchone())
            assert namespace['verify_payments'](sale, shop) == (7800, 200, 40)
            assert namespace['verify_payments'](dict(sale, gas_cap_wei='60'), shop) == (7800, 200, 50)
            assert run(dict(request, payer=outsider, recipient=outsider), fixture_shop)['reason'] == 'invalid_request'
            with patch.dict(tx, {'to': outsider}), patch.dict(receipt, {'to': outsider}):
                check('original_transfer_mismatch')
            with patch.dict(tx, {'from': outsider}), patch.dict(receipt, {'from': outsider}):
                check('original_transfer_mismatch')
            with patch.dict(fee_tx, {'from': outsider}), patch.dict(fee_receipt, {'from': outsider}):
                check('original_transfer_mismatch')
            with patch.dict(fee_tx, {'input': '0x' + 'f' * 64}):
                check('original_transfer_mismatch')
            with patch.dict(tx, {'value': hex(7799)}):
                check('original_transfer_mismatch')
            with patch.dict(fee_tx, {'value': hex(201)}):
                check('original_transfer_mismatch')
            with patch.dict(fee_receipt, {'status': '0x0'}):
                check('original_transfer_unsuccessful')
            with patch.dict(receipts, {fee_payment: None}):
                check('chain_evidence_unavailable')
            with patch.dict(facts, {'chain_id': 43}):
                check('chain_mismatch')
            db.execute('UPDATE sale SET gas_cap_wei=?', ('-1',))
            db.commit()
            check('invalid_ledger_amount')
            db.execute('UPDATE sale SET gas_cap_wei=?, fee_payment=?', ('40', payment))
            db.commit()
            check('original_transfer_mismatch')
            db.execute('UPDATE sale SET fee_payment=?', (fee_payment,))
            db.execute('INSERT INTO sale(id, payment) VALUES(?, ?)', ('duplicate', payment))
            db.commit()
            check('original_payment_link_ambiguous')
            with patch.dict(namespace, {'DB': path + '.absent'}):
                check('ledger_unavailable')
