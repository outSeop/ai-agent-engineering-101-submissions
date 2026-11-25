import hashlib
import json
import re
import sqlite3
from contextlib import closing

import httpx

DB = 'refund_dev_fixture.sqlite3'
RPC = 'https://rpc-testnet.maroo.io'
CHAIN_FACTS = 'https://market.ourolabs.ai/api/chain'


class Refusal(Exception):
    pass


def require(condition, reason):
    if not condition:
        raise Refusal(reason)


def identifier(value, size):
    require(isinstance(value, str) and re.fullmatch(r'0[xX][0-9a-fA-F]{%d}' % (2 * size), value), 'invalid_chain_identifier')
    return value.lower()


def quantity(value):
    require(isinstance(value, str) and re.fullmatch(r'0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)', value), 'invalid_chain_quantity')
    return int(value, 16)


def rpc(method, params):
    response = httpx.post(RPC, json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}, timeout=4)
    response.raise_for_status()
    body = response.json()
    require(body.get('id') == 1 and 'error' not in body and 'result' in body, 'chain_evidence_unavailable')
    return body['result']


def verify_receipt(tx_hash, seller, recipient, amount, marker):
    response = httpx.get(CHAIN_FACTS, timeout=4)
    response.raise_for_status()
    facts = response.json()
    require(facts['rpc'] == RPC and type(facts['chain_id']) is int and facts['chain_id'] > 0 and quantity(rpc('eth_chainId', [])) == facts['chain_id'], 'chain_mismatch')
    tx = rpc('eth_getTransactionByHash', [tx_hash])
    receipt = rpc('eth_getTransactionReceipt', [tx_hash])
    require(isinstance(tx, dict) and isinstance(receipt, dict), 'refund_receipt_unavailable')
    require(quantity(receipt['status']) == 1, 'refund_receipt_unsuccessful')
    require(
        identifier(tx['hash'], 32) == identifier(receipt['transactionHash'], 32) == tx_hash
        and identifier(tx['blockHash'], 32) == identifier(receipt['blockHash'], 32)
        and quantity(tx['blockNumber']) == quantity(receipt['blockNumber'])
        and identifier(tx['from'], 20) == identifier(receipt['from'], 20) == seller
        and identifier(tx['to'], 20) == identifier(receipt['to'], 20) == recipient
        and quantity(tx['value']) == amount
        and identifier(tx['input'], 32) == marker,
        'refund_transfer_mismatch',
    )


def run(args, kit):
    if kit.testing is not True:
        return {'status': 'no_change', 'reason': 'development_only'}
    try:
        require(isinstance(args, dict) and 'original_tx' in args and set(args) <= {'original_tx', 'refund_tx'}, 'invalid_arguments')
        original = identifier(args['original_tx'], 32)
        require(original != '0x' + '0' * 64, 'invalid_chain_identifier')
        candidate = identifier(args['refund_tx'], 32) if 'refund_tx' in args else None
        with closing(sqlite3.connect('file:' + DB + '?mode=rw', uri=True, timeout=2, isolation_level=None)) as db:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            require(db.execute('PRAGMA quick_check').fetchall() == [('ok',)] and db.execute('PRAGMA user_version').fetchone() == (1,), 'refund_state_unavailable')
            row = db.execute('SELECT status, recipient, amount_wei, marker, refund_tx FROM refunds WHERE original_tx=?', (original,)).fetchone()
            require(row is not None, 'refund_attempt_unavailable')
            status, recipient, amount, marker, recorded_hash = row
            require(status in ('attempted', 'uncertain', 'completed') and (status != 'completed' or recorded_hash is not None), 'refund_state_unavailable')
            if recorded_hash is not None:
                recorded_hash = identifier(recorded_hash, 32)
                require(candidate is None or candidate == recorded_hash, 'recorded_refund_hash_mismatch')
            refund_tx = recorded_hash or candidate
            require(refund_tx is not None, 'refund_transaction_hash_required')
            require(refund_tx not in (original, '0x' + '0' * 64), 'invalid_refund_transaction')

            order_row = db.execute('SELECT evidence FROM orders WHERE original_tx=?', (original,)).fetchone()
            require(order_row is not None and isinstance(amount, str) and re.fullmatch(r'[1-9][0-9]*', amount), 'refund_state_unavailable')
            order = json.loads(order_row[0])
            seller = identifier(kit.address('shop'), 20)
            recipient = identifier(recipient, 20)
            amount = int(amount)
            expected_marker = '0x' + hashlib.sha256(('round4-refund:' + original).encode('ascii')).hexdigest()
            require(
                order['shop'] == kit.name and identifier(order['seller'], 20) == seller
                and recipient != seller and identifier(order['buyer'], 20) == recipient
                and order['decision'] == 'approved' and order['approval_ref'] and order['review_ref']
                and type(order['approved_wei']) is int and order['approved_wei'] == amount
                and identifier(marker, 32) == expected_marker,
                'refund_attempt_evidence_mismatch',
            )
            verify_receipt(refund_tx, seller, recipient, amount, expected_marker)
            if status != 'completed':
                changed = db.execute("UPDATE refunds SET status='completed', refund_tx=? WHERE original_tx=? AND status IN ('attempted', 'uncertain')", (refund_tx, original)).rowcount
                require(changed == 1, 'refund_state_unavailable')
            db.commit()
        return {'status': 'completed', 'simulated': True, 'original_tx': original, 'refund_tx': refund_tx, 'refund_wei': amount}
    except Refusal as exc:
        return {'status': 'no_change', 'reason': str(exc)}
    except sqlite3.Error:
        return {'status': 'no_change', 'reason': 'refund_state_unavailable'}
    except (KeyError, TypeError, ValueError, AttributeError, httpx.HTTPError):
        return {'status': 'no_change', 'reason': 'evidence_unavailable'}
