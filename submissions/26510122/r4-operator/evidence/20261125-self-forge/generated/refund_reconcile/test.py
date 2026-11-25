def test(run, kit):
    import hashlib
    import json
    import sqlite3
    from contextlib import closing
    from pathlib import Path
    from unittest.mock import patch

    path = Path('refund_dev_fixture.sqlite3')
    seller = '0x' + '11' * 20
    buyer = '0x' + '22' * 20
    outsider = '0x' + '33' * 20
    rpc_calls = []

    def txid(n):
        return '0x' + format(n, '064x')

    def marker(original):
        return '0x' + hashlib.sha256(('round4-refund:' + original).encode('ascii')).hexdigest()

    class FixtureKit:
        testing = True
        name = 'fixture-shop'

        def address(self, role):
            assert role == 'shop'
            return seller

        def pay(self, *args, **kwargs):
            raise AssertionError('reconciliation must never pay')

    class Response:
        def __init__(self, body):
            self.body = body

        def raise_for_status(self):
            pass

        def json(self):
            return self.body

    transactions = {}
    receipts = {}

    def add_transfer(refund, original, *, sender=seller, recipient=buyer, amount=8010, status='0x1', data=None):
        block = {'blockHash': txid(900), 'blockNumber': '0x20'}
        parties = {'from': sender, 'to': recipient}
        refund_hash = txid(refund)
        transactions[refund_hash] = dict(block, **parties, hash=refund_hash, value=hex(amount), input=data or marker(txid(original)))
        if status is not None:
            receipts[refund_hash] = dict(block, **parties, transactionHash=refund_hash, status=status)

    def fake_get(url, *, timeout):
        assert url == 'https://market.ourolabs.ai/api/chain'
        return Response({'rpc': 'https://rpc-testnet.maroo.io', 'chain_id': 42})

    def fake_post(url, *, json, timeout):
        assert url == 'https://rpc-testnet.maroo.io'
        method = json['method']
        rpc_calls.append(method)
        if method == 'eth_chainId':
            assert json['params'] == []
            result = '0x2a'
        else:
            table = {'eth_getTransactionByHash': transactions, 'eth_getTransactionReceipt': receipts}[method]
            result = table.get(json['params'][0])
        return Response({'id': 1, 'result': result})

    def request(original, refund=None):
        args = {'original_tx': txid(original)}
        if refund is not None:
            args['refund_tx'] = txid(refund)
        return run(args, FixtureKit())

    def state(original):
        with closing(sqlite3.connect(path)) as db:
            return db.execute('SELECT status, refund_tx FROM refunds WHERE original_tx=?', (txid(original),)).fetchone()

    assert not path.exists()
    try:
        assert request(1, 101)['reason'] == 'refund_state_unavailable'
        assert not path.exists()
        with closing(sqlite3.connect(path)) as db:
            db.executescript('''PRAGMA user_version=1;
                CREATE TABLE orders (original_tx TEXT PRIMARY KEY, evidence TEXT NOT NULL);
                CREATE TABLE refunds (original_tx TEXT PRIMARY KEY, status TEXT NOT NULL CHECK(status IN ('attempted', 'uncertain', 'completed')), recipient TEXT NOT NULL, amount_wei TEXT NOT NULL, marker TEXT NOT NULL, refund_tx TEXT UNIQUE, CHECK(status <> 'completed' OR refund_tx IS NOT NULL));''')
            for original, status, stored in ((1, 'uncertain', None), (2, 'attempted', None), (3, 'uncertain', txid(103))):
                evidence = {'shop': 'fixture-shop', 'seller': seller, 'buyer': buyer, 'decision': 'approved', 'approval_ref': 'approval', 'review_ref': 'review', 'approved_wei': 8010}
                db.execute('INSERT INTO orders VALUES (?, ?)', (txid(original), json.dumps(evidence)))
                db.execute('INSERT INTO refunds VALUES (?, ?, ?, ?, ?, ?)', (txid(original), status, buyer, '8010', marker(txid(original)), stored))
            db.commit()

        add_transfer(101, 1)
        add_transfer(102, 2)
        add_transfer(103, 3)
        add_transfer(110, 1, sender=outsider)
        add_transfer(111, 1, recipient=outsider)
        add_transfer(112, 1, amount=8011)
        add_transfer(113, 1, data=marker(txid(2)))
        add_transfer(114, 1, status=None)
        add_transfer(115, 1, status='0x0')
        with patch('httpx.get', fake_get), patch('httpx.post', fake_post):
            disabled = FixtureKit()
            disabled.testing = False
            assert run({'original_tx': txid(1)}, disabled)['reason'] == 'development_only'
            assert request(1)['reason'] == 'refund_transaction_hash_required'
            assert request(4, 101)['reason'] == 'refund_attempt_unavailable'
            assert request(3, 101)['reason'] == 'recorded_refund_hash_mismatch'
            assert not rpc_calls
            for refund in (110, 111, 112, 113):
                assert request(1, refund)['reason'] == 'refund_transfer_mismatch'
                assert state(1) == ('uncertain', None)
            assert request(1, 114)['reason'] == 'refund_receipt_unavailable'
            assert request(1, 115)['reason'] == 'refund_receipt_unsuccessful'
            assert state(1) == ('uncertain', None)
            result = request(1, 101)
            assert result == {'status': 'completed', 'simulated': True, 'original_tx': txid(1), 'refund_tx': txid(101), 'refund_wei': 8010}
            assert request(1) == result
            assert state(1) == ('completed', txid(101))
            assert request(2, 101)['reason'] == 'refund_transfer_mismatch'
            assert state(2) == ('attempted', None)
            assert request(2, 102)['status'] == 'completed'
            assert state(2) == ('completed', txid(102))
            assert request(3)['status'] == 'completed'
            assert state(3) == ('completed', txid(103))
            path.write_bytes(b'corrupted fixture ledger')
            assert request(1, 101)['reason'] == 'refund_state_unavailable'
            assert path.read_bytes() == b'corrupted fixture ledger'
    finally:
        path.unlink(missing_ok=True)
