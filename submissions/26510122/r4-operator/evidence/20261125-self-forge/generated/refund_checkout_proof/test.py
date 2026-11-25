import hashlib
import json
import sqlite3
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import patch


def test(run, kit):
    logic = run.__globals__
    assert logic['keccak256'](b'').hex() == 'c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470'
    assert logic['keccak256'](b'abc').hex() == '4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45'
    assert logic['keccak256'](b'The quick brown fox jumps over the lazy dog').hex() == '4d741b6f1eb29cb2a9b9911c82f56fa8d73b04959d3d9d222895df6c0b28aa15'
    # The public address of the disposable test key 1 is fixed independently of this implementation.
    seller = '0x7e5f4552091a69125d5dfcb7b8c2659029395bdf'
    fixture_kit = SimpleNamespace(name='fixture-shop', address=lambda role: {'shop': seller}[role])
    b64url = logic['b64url']
    path = 'refund_checkout_fixture.sqlite3'
    claims = {'id': 'sale-1', 'shop': 'fixture-shop', 'shop_url': 'https://fixture.invalid/card', 'item': 'fixture-sku', 'unit': 'fixture-unit', 'price': 1000, 'currency': 'credits', 'task': 'fixture-task', 'iat': 100}

    def segment(obj):
        return b64url(json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8'))

    def sign(payload, test_key=1, algorithm='EIP191'):
        message = segment({'alg': algorithm, 'typ': 'JWT'}) + '.' + segment(payload)
        # Fixed nonce 1 and public fixture keys are used exclusively in this sandbox test.
        r = 0x79be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798
        digest = int.from_bytes(logic['personal_hash'](message.encode('ascii')), 'big')
        s = (digest + r * test_key) % logic['ORDER']
        return message + '.' + b64url(r.to_bytes(32, 'big') + s.to_bytes(32, 'big') + bytes([27]))

    with closing(sqlite3.connect(path)) as db, patch.dict(logic, {'DB': path}):
        db.execute('CREATE TABLE identity(singleton INTEGER PRIMARY KEY, shop TEXT, wallet TEXT)')
        db.execute('CREATE TABLE sale(id TEXT PRIMARY KEY, owner TEXT, unit TEXT, sku TEXT, base INTEGER, cost INTEGER, price INTEGER, discount INTEGER, spent INTEGER, ticket TEXT, shop_url TEXT, wallet TEXT, created REAL, digest TEXT, jwt TEXT, expected_wei TEXT, fee_wei TEXT, gas_cap_wei TEXT, fee_wallet TEXT, grade TEXT, status TEXT, market_order TEXT, payment TEXT, fee_payment TEXT, payer TEXT, settled REAL, broken REAL)')
        db.execute('INSERT INTO identity VALUES(1, ?, ?)', (fixture_kit.name, seller))
        db.execute('INSERT INTO sale(id, unit, sku, price, shop_url, wallet, status) VALUES(?, ?, ?, ?, ?, ?, ?)', ('sale-1', claims['unit'], claims['item'], claims['price'], claims['shop_url'], seller, 'missing'))

        def store(checkout, digest=None):
            if digest is None:
                digest = hashlib.sha256(checkout.encode('ascii')).hexdigest()
            db.execute('UPDATE sale SET jwt=?, digest=? WHERE id=?', (checkout, digest, 'sale-1'))
            db.commit()

        request = {'sale_id': 'sale-1'}
        checkout = sign(claims)
        store(checkout)
        assert run(request, fixture_kit) == {'status': 'verified'}
        assert run(dict(request, approval='approved'), fixture_kit)['reason'] == 'invalid_request'
        assert run({'sale_id': 'absent'}, fixture_kit)['reason'] == 'sale_unavailable'
        store(sign(claims, test_key=2))
        assert run(request, fixture_kit)['reason'] == 'checkout_signature_invalid'
        header, _, signature = checkout.split('.')
        store('.'.join((header, segment(dict(claims, price=1001)), signature)))
        assert run(request, fixture_kit)['reason'] == 'checkout_signature_invalid'
        store(sign(dict(claims, item='other-sku')))
        assert run(request, fixture_kit)['reason'] == 'checkout_sale_mismatch'
        store(sign(claims, algorithm='none'))
        assert run(request, fixture_kit)['reason'] == 'checkout_encoding_invalid'
        store(checkout, 'unrelated-digest')
        assert run(request, fixture_kit)['reason'] == 'checkout_digest_mismatch'
        store(checkout)
        db.execute('UPDATE identity SET wallet=?', ('0x' + '3' * 40,))
        db.commit()
        assert run(request, fixture_kit)['reason'] == 'shop_wallet_mismatch'
    with patch.dict(logic, {'DB': path + '.absent'}):
        assert run(request, fixture_kit)['reason'] == 'ledger_unavailable'
