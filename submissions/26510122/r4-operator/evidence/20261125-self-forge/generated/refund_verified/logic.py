import base64
import hashlib
import json
import re
import sqlite3
from contextlib import closing

import httpx

DB = 'refund_dev_fixture.sqlite3'
RPC = 'https://rpc-testnet.maroo.io'
CHAIN_FACTS = 'https://market.ourolabs.ai/api/chain'
ZERO_HASH = '0x' + '0' * 64


class Refusal(Exception):
    pass


def require(condition, reason):
    if not condition:
        raise Refusal(reason)


def identifier(value, size):
    require(isinstance(value, str) and re.fullmatch(r'0[xX][0-9a-fA-F]{%d}' % (size * 2), value), 'invalid_chain_identifier')
    return value.lower()


def tx_id(value):
    value = identifier(value, 32)
    require(value != ZERO_HASH, 'invalid_chain_identifier')
    return value


def integer(value, minimum=0):
    require(type(value) is int and value >= minimum, 'invalid_numeric_evidence')
    return value


def quantity(value):
    require(isinstance(value, str) and re.fullmatch(r'0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)', value), 'invalid_rpc_quantity')
    return int(value, 16)


def rpc(method, params):
    response = httpx.post(RPC, json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}, timeout=4)
    response.raise_for_status()
    payload = response.json()
    require(payload.get('id') == 1 and 'error' not in payload and 'result' in payload, 'chain_evidence_unavailable')
    return payload['result']


def chain_facts():
    response = httpx.get(CHAIN_FACTS, timeout=4)
    response.raise_for_status()
    facts = response.json()
    require(facts['rpc'] == RPC and quantity(rpc('eth_chainId', [])) == integer(facts['chain_id'], 1), 'chain_mismatch')
    return facts


def transfer(tx_hash, sender, recipient, value, data):
    tx = rpc('eth_getTransactionByHash', [tx_hash])
    receipt = rpc('eth_getTransactionReceipt', [tx_hash])
    require(isinstance(tx, dict) and isinstance(receipt, dict), 'chain_evidence_unavailable')
    require(quantity(receipt['status']) == 1, 'chain_transfer_unsuccessful')
    require(
        tx_id(tx['hash']) == tx_id(receipt['transactionHash']) == tx_hash
        and tx_id(tx['blockHash']) == tx_id(receipt['blockHash'])
        and quantity(tx['blockNumber']) == quantity(receipt['blockNumber'])
        and identifier(tx['from'], 20) == identifier(receipt['from'], 20) == sender
        and identifier(tx['to'], 20) == identifier(receipt['to'], 20) == recipient
        and quantity(tx['value']) == value
        and identifier(tx['input'], 32) == data,
        'chain_transfer_mismatch',
    )
    return receipt


def gas_cost(receipt):
    return quantity(receipt['gasUsed']) * quantity(receipt['effectiveGasPrice'])


def open_state():
    db = sqlite3.connect('file:' + DB + '?mode=rw', uri=True, timeout=2, isolation_level=None)
    try:
        db.execute('PRAGMA synchronous=FULL')
        db.execute('BEGIN IMMEDIATE')
        require(db.execute('PRAGMA quick_check').fetchall() == [('ok',)], 'refund_state_unavailable')
        require(db.execute('PRAGMA user_version').fetchone() == (1,), 'refund_state_unavailable')
        return db
    except BaseException:
        db.close()
        raise


def seller_order(db, original, kit):
    row = db.execute('SELECT evidence FROM orders WHERE original_tx=?', (original,)).fetchone()
    require(row is not None, 'seller_order_unavailable')
    order = json.loads(row[0])
    seller = identifier(kit.address('shop'), 20)
    buyer = identifier(order['buyer'], 20)
    require(identifier(order['seller'], 20) == seller and buyer != seller and order['shop'] == kit.name, 'seller_wallet_mismatch')
    require(order['decision'] == 'approved' and order['approval_ref'] and order['review_ref'], 'seller_approval_required')
    return order, seller, buyer


def marker_for(original):
    return '0x' + hashlib.sha256(('round4-refund:' + original).encode('ascii')).hexdigest()


def authorize_amount(order, original, seller, buyer, kit):
    require(order['order_id'] and order['sku'], 'seller_evidence_incomplete')
    if order['cause'] == 'seller_non_delivery':
        require(order['delivery'] == 'undelivered' and order['seller_fault'] is True, 'non_delivery_unverified')
    elif order['cause'] == 'early_issue':
        require(order['delivery'] == 'delivered', 'delivery_unverified')
        delivered = integer(order['delivered_at'], 1)
        confirmed = integer(order['confirmed_at'], 1)
        require(0 <= confirmed - delivered <= 48 * 3600, 'early_issue_outside_window')
    else:
        raise Refusal('refund_cause_unverified')

    price = integer(order['price'], 1)
    gas_cap = integer(order['promised_gas_credits'])
    checkout = order['checkout_jwt']
    header, payload, signature = checkout.split('.')
    require(bool(header and signature), 'checkout_unverified')
    claims = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
    require(
        claims['id'] == order['checkout_id'] and claims['shop'] == kit.name
        and claims['item'] == order['sku'] and integer(claims['price'], 1) == price
        and claims['currency'] == 'credits',
        'checkout_mismatch',
    )
    checkout_data = '0x' + hashlib.sha256(checkout.encode('ascii')).hexdigest()
    facts = chain_facts()
    credit = integer(facts['credit_wei'], 1)
    fee_bps = integer(facts['market_fee_bps'])
    standard_gas = integer(facts['network_fee_credits'])
    require(fee_bps <= 10000 and standard_gas % 2 == 0, 'invalid_chain_fees')
    market = identifier(facts['market_address'], 20)
    require(market not in (seller, buyer), 'invalid_market_wallet')
    fee = price * fee_bps // 10000
    shop_value = (price - fee - standard_gas // 2) * credit
    fee_value = 2 * fee * credit
    require(shop_value > 0, 'invalid_shop_payment')
    gas_paid = gas_cost(transfer(original, buyer, seller, shop_value, checkout_data))
    if fee:
        fee_hash = tx_id(order['fee_tx'])
        require(fee_hash != original, 'invalid_fee_transfer')
        gas_paid += gas_cost(transfer(fee_hash, buyer, market, fee_value, checkout_data))
    else:
        require(order['fee_tx'] is None, 'unexpected_fee_transfer')
    amount = shop_value + fee_value + min(gas_paid, gas_cap * credit)
    require(integer(order['approved_wei'], 1) == amount, 'seller_approval_amount_mismatch')
    return amount


def reserve(original, kit):
    with closing(open_state()) as db:
        existing = db.execute('SELECT 1 FROM refunds WHERE original_tx=?', (original,)).fetchone()
        require(existing is None, 'refund_already_recorded')
        pending = db.execute("SELECT 1 FROM refunds WHERE status IS NULL OR status <> 'completed' OR refund_tx IS NULL LIMIT 1").fetchone()
        require(pending is None, 'unresolved_refund_exists')
        order, seller, buyer = seller_order(db, original, kit)
        amount = authorize_amount(order, original, seller, buyer, kit)
        marker = marker_for(original)
        db.execute("INSERT INTO refunds (original_tx, status, recipient, amount_wei, marker) VALUES (?, 'attempted', ?, ?, ?)", (original, buyer, str(amount), marker))
        db.commit()
    return buyer, amount, marker


def record_uncertain(original, refund_tx):
    with closing(open_state()) as db:
        db.execute("UPDATE refunds SET status='uncertain', refund_tx=COALESCE(refund_tx, ?) WHERE original_tx=? AND status='attempted'", (refund_tx, original))
        db.commit()


def reconcile(original, candidate, kit):
    with closing(open_state()) as db:
        row = db.execute('SELECT status, recipient, amount_wei, marker, refund_tx FROM refunds WHERE original_tx=?', (original,)).fetchone()
        require(row is not None, 'refund_attempt_unavailable')
        status, recipient, amount_text, marker, stored = row
        require(status in ('attempted', 'uncertain', 'completed') and (status != 'completed' or stored is not None), 'refund_state_unavailable')
        if stored is not None:
            stored = tx_id(stored)
            require(candidate is None or stored == candidate, 'recorded_refund_hash_mismatch')
        refund_tx = stored or candidate
        require(refund_tx is not None, 'refund_transaction_hash_required')
        require(refund_tx != original, 'invalid_refund_transaction')
        order, seller, buyer = seller_order(db, original, kit)
        require(isinstance(amount_text, str) and re.fullmatch(r'[1-9][0-9]*', amount_text), 'refund_state_unavailable')
        amount = int(amount_text)
        expected_marker = marker_for(original)
        require(
            identifier(recipient, 20) == buyer and integer(order['approved_wei'], 1) == amount
            and identifier(marker, 32) == expected_marker,
            'refund_attempt_evidence_mismatch',
        )
        chain_facts()
        transfer(refund_tx, seller, buyer, amount, expected_marker)
        if status != 'completed':
            changed = db.execute("UPDATE refunds SET status='completed', refund_tx=? WHERE original_tx=? AND status IN ('attempted', 'uncertain')", (refund_tx, original)).rowcount
            require(changed == 1, 'refund_state_unavailable')
        db.commit()
    return {'status': 'completed', 'simulated': True, 'original_tx': original, 'refund_tx': refund_tx, 'refund_wei': amount}


def submit(original, kit):
    buyer, amount, marker = reserve(original, kit)
    refund_tx = None
    try:
        candidate = tx_id(kit.pay(buyer, amount, marker, role='shop'))
        require(candidate != original, 'invalid_refund_transaction')
        refund_tx = candidate
        result = reconcile(original, refund_tx, kit)
    except Exception:
        try:
            record_uncertain(original, refund_tx)
        except (sqlite3.Error, Refusal):
            # The committed attempt still blocks further sends.
            pass
        return {'approved': False, 'reason': 'refund_uncertain'}
    return {'approved': True, 'simulated': True, 'refund_tx': result['refund_tx'], 'refund_wei': result['refund_wei']}


def run(args, kit):
    if kit.testing is not True:
        return {'approved': False, 'reason': 'development_only'}
    recovery = isinstance(args, dict) and args.get('operation') == 'reconcile'
    failure = {'status': 'no_change'} if recovery else {'approved': False}
    try:
        if recovery:
            require('original_tx' in args and set(args) <= {'operation', 'original_tx', 'refund_tx'}, 'invalid_arguments')
            candidate = tx_id(args['refund_tx']) if 'refund_tx' in args else None
            return reconcile(tx_id(args['original_tx']), candidate, kit)
        require(isinstance(args, dict) and set(args) == {'original_tx'}, 'original_tx_only')
        return submit(tx_id(args['original_tx']), kit)
    except Refusal as exc:
        return dict(failure, reason=str(exc))
    except sqlite3.Error:
        return dict(failure, reason='refund_state_unavailable')
    except (KeyError, TypeError, ValueError, AttributeError, httpx.HTTPError):
        return dict(failure, reason='evidence_unavailable')
