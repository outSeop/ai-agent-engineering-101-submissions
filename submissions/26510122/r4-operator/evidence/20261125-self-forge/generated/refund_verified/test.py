def test(run, kit):
    import base64
    import hashlib
    import json
    import sqlite3
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import closing
    from pathlib import Path
    from threading import Event
    from unittest.mock import patch

    path = Path('refund_dev_fixture.sqlite3')
    seller, buyer, market, outsider = ['0x' + byte * 20 for byte in ('11', '22', '33', '44')]
    txs, receipts = {}, {}
    payments = []
    entered_pay, release_pay = Event(), Event()

    def txid(n):
        return '0x' + format(n, '064x')

    def add_transfer(tx_hash, sender, recipient, value, data, *, status='0x1', visible=True):
        fields = {'from': sender, 'to': recipient, 'blockHash': txid(999), 'blockNumber': '0x20'}
        txs[tx_hash] = dict(fields, hash=tx_hash, value=hex(value), input=data)
        receipt = dict(fields, transactionHash=tx_hash, status=status, gasUsed='0x5', effectiveGasPrice='0x2')
        if visible:
            receipts[tx_hash] = receipt
        return receipt

    class Response:
        def __init__(self, body):
            self.body = body

        def raise_for_status(self):
            pass

        def json(self):
            return self.body

    def fake_get(url, *, timeout):
        assert url == 'https://market.ourolabs.ai/api/chain'
        return Response({'rpc': 'https://rpc-testnet.maroo.io', 'chain_id': 42, 'credit_wei': 10, 'market_fee_bps': 100, 'network_fee_credits': 420, 'market_address': market})

    def fake_post(url, *, json, timeout):
        assert url == 'https://rpc-testnet.maroo.io'
        if json['method'] == 'eth_chainId':
            assert json['params'] == []
            return Response({'id': 1, 'result': '0x2a'})
        table = {'eth_getTransactionByHash': txs, 'eth_getTransactionReceipt': receipts}[json['method']]
        return Response({'id': 1, 'result': table.get(json['params'][0])})

    class FixtureKit:
        testing = True
        name = 'fixture-shop'

        def __init__(self, mode='confirmed'):
            self.mode = mode

        def address(self, role):
            assert role == 'shop'
            return seller

        def pay(self, recipient, amount, data, *, role):
            assert self.mode != 'recovery', 'recovery must never send'
            assert (role, recipient, amount) == ('shop', buyer, 8010)
            refund_tx = txid(100 + len(payments) + 1)
            payments.append(refund_tx)
            self.refund_tx = refund_tx
            self.receipt = add_transfer(refund_tx, seller, recipient, amount, data, visible=self.mode != 'lost_receipt')
            if self.mode == 'waiting':
                entered_pay.set()
                assert release_pay.wait(5)
                raise TimeoutError('broadcast succeeded, response lost')
            return refund_tx

    def add_order(db, n, *, wrong_destination=False, wrong_fee=False, gas_cap=1, early_hours=None):
        original = txid(n)
        checkout_id = 'checkout-' + str(n)
        claims = {'id': checkout_id, 'shop': 'fixture-shop', 'item': 'sku', 'price': 1000, 'currency': 'credits'}
        payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')
        checkout = 'fixture.' + payload + '.fixture'
        data = '0x' + hashlib.sha256(checkout.encode()).hexdigest()
        fee_tx = txid(50 + n)
        add_transfer(original, buyer, outsider if wrong_destination else seller, 7800, data)
        add_transfer(fee_tx, buyer, market, 190 if wrong_fee else 200, data)
        order = {'order_id': 'order-' + str(n), 'shop': 'fixture-shop', 'seller': seller, 'buyer': buyer, 'sku': 'sku', 'checkout_id': checkout_id, 'checkout_jwt': checkout, 'price': 1000, 'fee_tx': fee_tx, 'promised_gas_credits': gas_cap, 'approved_wei': 8010, 'approval_ref': 'decision', 'review_ref': 'evidence', 'decision': 'approved', 'cause': 'seller_non_delivery', 'delivery': 'undelivered', 'seller_fault': True}
        if early_hours is not None:
            order.update(cause='early_issue', delivery='delivered', delivered_at=1000, confirmed_at=1000 + early_hours * 3600)
        db.execute('INSERT INTO orders VALUES (?, ?)', (original, json.dumps(order)))

    def submit(n, fixture_kit=None):
        return run({'original_tx': txid(n)}, fixture_kit or FixtureKit())

    def recover(n, candidate=None):
        args = {'operation': 'reconcile', 'original_tx': txid(n)}
        if candidate is not None:
            args['refund_tx'] = candidate
        return run(args, FixtureKit('recovery'))

    def state(n):
        with closing(sqlite3.connect(path)) as db:
            return db.execute('SELECT status, refund_tx FROM refunds WHERE original_tx=?', (txid(n),)).fetchone()

    assert not path.exists()
    try:
        assert submit(1)['reason'] == 'refund_state_unavailable'
        assert not path.exists()
        with closing(sqlite3.connect(path)) as db:
            db.executescript('''PRAGMA user_version=1;
                CREATE TABLE orders (original_tx TEXT PRIMARY KEY, evidence TEXT NOT NULL);
                CREATE TABLE refunds (original_tx TEXT PRIMARY KEY, status TEXT NOT NULL CHECK(status IN ('attempted', 'uncertain', 'completed')), recipient TEXT NOT NULL, amount_wei TEXT NOT NULL, marker TEXT NOT NULL, refund_tx TEXT UNIQUE, CHECK(status <> 'completed' OR refund_tx IS NOT NULL));''')
            add_order(db, 1)
            add_order(db, 2)
            add_order(db, 3, wrong_destination=True)
            add_order(db, 4, wrong_fee=True)
            add_order(db, 5, gas_cap=-1)
            add_order(db, 6, early_hours=48)
            add_order(db, 7, early_hours=49)
            add_order(db, 8)
            db.commit()

        with patch('httpx.get', fake_get), patch('httpx.post', fake_post):
            disabled = FixtureKit()
            disabled.testing = False
            assert submit(1, disabled)['reason'] == 'development_only'
            spoofed = {'original_tx': txid(1), 'recipient': outsider, 'approval': True, 'ledger': {'payer': outsider}}
            assert run(spoofed, FixtureKit())['reason'] == 'original_tx_only'
            for n, reason in ((3, 'chain_transfer_mismatch'), (4, 'chain_transfer_mismatch'), (5, 'invalid_numeric_evidence'), (7, 'early_issue_outside_window')):
                assert submit(n)['reason'] == reason
            assert not payments

            waiting = FixtureKit('waiting')
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(submit, 1, waiting)
                try:
                    assert entered_pay.wait(5)
                    assert state(1) == ('attempted', None)
                    assert pool.submit(submit, 1).result(timeout=5)['reason'] == 'refund_already_recorded'
                    assert submit(2)['reason'] == 'unresolved_refund_exists'
                    assert payments == [waiting.refund_tx]
                finally:
                    release_pay.set()
                assert first.result(timeout=5)['reason'] == 'refund_uncertain'

            assert state(1) == ('uncertain', None)
            assert submit(1)['reason'] == 'refund_already_recorded'
            assert submit(2)['reason'] == 'unresolved_refund_exists'
            assert recover(1)['reason'] == 'refund_transaction_hash_required'
            assert recover(1, txid(950))['reason'] == 'chain_evidence_unavailable'
            data = txs[waiting.refund_tx]['input']
            add_transfer(txid(951), seller, buyer, 8010, data, status='0x0')
            add_transfer(txid(952), seller, outsider, 8010, data)
            add_transfer(txid(953), outsider, buyer, 8010, data)
            add_transfer(txid(954), seller, buyer, 8011, data)
            add_transfer(txid(955), seller, buyer, 8010, txid(955))
            assert recover(1, txid(951))['reason'] == 'chain_transfer_unsuccessful'
            for n in range(952, 956):
                assert recover(1, txid(n))['reason'] == 'chain_transfer_mismatch'
            assert state(1) == ('uncertain', None)
            assert submit(2)['reason'] == 'unresolved_refund_exists'
            assert payments == [waiting.refund_tx]

            recovered = recover(1, waiting.refund_tx)
            assert recovered == {'status': 'completed', 'simulated': True, 'original_tx': txid(1), 'refund_tx': waiting.refund_tx, 'refund_wei': 8010}
            assert recover(1) == recovered
            assert recover(1, txid(952))['reason'] == 'recorded_refund_hash_mismatch'
            assert state(1) == ('completed', waiting.refund_tx)
            assert submit(1)['reason'] == 'refund_already_recorded'
            assert payments == [waiting.refund_tx]

            invisible = FixtureKit('lost_receipt')
            assert submit(2, invisible)['reason'] == 'refund_uncertain'
            assert state(2) == ('uncertain', invisible.refund_tx)
            assert recover(2)['reason'] == 'chain_evidence_unavailable'
            assert recover(2, waiting.refund_tx)['reason'] == 'recorded_refund_hash_mismatch'
            assert submit(6)['reason'] == 'unresolved_refund_exists'
            receipts[invisible.refund_tx] = invisible.receipt
            assert recover(2)['status'] == 'completed'
            assert submit(6)['approved'] is True
            assert len(payments) == 3

            path.write_bytes(b'corrupted fixture ledger')
            assert submit(1)['reason'] == 'refund_state_unavailable'
            assert submit(8)['reason'] == 'refund_state_unavailable'
            assert recover(2)['reason'] == 'refund_state_unavailable'
            assert path.read_bytes() == b'corrupted fixture ledger'
            assert len(payments) == 3
    finally:
        path.unlink(missing_ok=True)
