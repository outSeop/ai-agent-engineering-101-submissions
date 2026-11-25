import re
import sqlite3
from contextlib import closing

import httpx

DB = 'state/r4-benefits/benefits.sqlite3'
RPC = 'https://rpc-testnet.maroo.io'
CHAIN_FACTS = 'https://market.ourolabs.ai/api/chain'


class Refusal(Exception):
    pass


def require(condition, reason):
    if not condition:
        raise Refusal(reason)


def identifier(value, size):
    require(isinstance(value, str) and re.fullmatch(r'0x[0-9a-fA-F]{%d}' % (size * 2), value) is not None, 'invalid_chain_identifier')
    require(int(value, 16) > 0, 'invalid_chain_identifier')
    return value.lower()


def quantity(value):
    require(isinstance(value, str) and re.fullmatch(r'0x(?:0|[1-9a-fA-F][0-9a-fA-F]{0,63})', value) is not None, 'invalid_chain_quantity')
    return int(value, 16)


def wei(value):
    require(isinstance(value, str) and re.fullmatch(r'0|[1-9][0-9]{0,77}', value) is not None, 'invalid_ledger_amount')
    amount = int(value)
    require(amount < 2**256, 'invalid_ledger_amount')
    return amount


def rpc(method, params):
    response = httpx.post(RPC, json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}, timeout=4)
    response.raise_for_status()
    body = response.json()
    require(isinstance(body, dict) and body.get('jsonrpc') == '2.0' and type(body.get('id')) is int and body['id'] == 1 and 'error' not in body and 'result' in body, 'chain_evidence_unavailable')
    return body['result']


def optional_hash(value):
    return None if value in (None, '') else identifier(value, 32)


def load_attempt(sale_id, kit):
    with closing(sqlite3.connect('file:' + DB + '?mode=ro', uri=True, timeout=2)) as db:
        db.row_factory = sqlite3.Row
        db.execute('BEGIN')
        require([tuple(row) for row in db.execute('PRAGMA quick_check(1)')] == [('ok',)], 'ledger_unavailable')
        identity = db.execute('SELECT singleton, shop, wallet FROM identity LIMIT 2').fetchall()
        require(len(identity) == 1 and identity[0]['singleton'] == 1, 'shop_identity_unavailable')
        sale = db.execute('SELECT * FROM sale WHERE id=?', (sale_id,)).fetchone()
        refund = db.execute('SELECT * FROM refund WHERE sale_id=?', (sale_id,)).fetchone()
        require(sale is not None and refund is not None, 'refund_attempt_unavailable')
        seller = identifier(kit.address('shop'), 20)
        require(identity[0]['shop'] == kit.name and identifier(identity[0]['wallet'], 20) == identifier(sale['wallet'], 20) == seller, 'shop_wallet_mismatch')
        require(sale['status'] in ('paid', 'missing', 'settled') and refund['status'] in ('sending', 'pending_unknown'), 'refund_attempt_unavailable')
        incoming = identifier(sale['payment'], 32)
        buyer = identifier(sale['payer'], 20)
        require(buyer != seller and identifier(refund['payer'], 20) == buyer and identifier(refund['incoming'], 32) == incoming, 'refund_attempt_link_mismatch')
        fee_payment = optional_hash(sale['fee_payment'])
        require(optional_hash(refund['fee_payment']) == fee_payment and fee_payment != incoming, 'refund_attempt_link_mismatch')
        amount = wei(refund['wei'])
        transfer = wei(refund['transfer_wei'])
        fee = wei(refund['fee_wei'])
        gas = wei(refund['gas_wei'])
        require(transfer == wei(sale['expected_wei']) > 0 and fee == wei(sale['fee_wei']) and bool(fee) == bool(fee_payment) and gas <= wei(sale['gas_cap_wei']) and amount == transfer + fee + gas, 'refund_attempt_amount_mismatch')
        outgoing = optional_hash(refund['outgoing'])
        require(outgoing is not None, 'recorded_refund_hash_unavailable')
        require(outgoing not in (incoming, fee_payment), 'refund_attempt_link_mismatch')
        marker = identifier(refund['marker'], 32)
        checks = (
            ('SELECT id FROM sale WHERE payment=? COLLATE NOCASE LIMIT 2', incoming),
            ('SELECT sale_id FROM refund WHERE incoming=? COLLATE NOCASE LIMIT 2', incoming),
            ('SELECT sale_id FROM refund WHERE outgoing=? COLLATE NOCASE LIMIT 2', outgoing),
            ('SELECT sale_id FROM refund WHERE marker=? COLLATE NOCASE LIMIT 2', marker),
        )
        for sql, value in checks:
            require([row[0] for row in db.execute(sql, (value,))] == [sale_id], 'refund_attempt_link_ambiguous')
        return outgoing, seller, buyer, amount, marker


def verify_receipt(outgoing, seller, buyer, amount, marker):
    response = httpx.get(CHAIN_FACTS, timeout=4)
    response.raise_for_status()
    facts = response.json()
    chain = facts['chain_id']
    require(facts['rpc'] == RPC and type(chain) is int and chain > 0 and quantity(rpc('eth_chainId', [])) == chain, 'chain_mismatch')
    tx = rpc('eth_getTransactionByHash', [outgoing])
    receipt = rpc('eth_getTransactionReceipt', [outgoing])
    require(isinstance(tx, dict) and isinstance(receipt, dict), 'refund_receipt_unavailable')
    require(quantity(receipt['status']) == 1, 'refund_receipt_unsuccessful')
    block_hash = identifier(tx['blockHash'], 32)
    block_number = quantity(tx['blockNumber'])
    require(
        identifier(tx['hash'], 32) == identifier(receipt['transactionHash'], 32) == outgoing
        and identifier(receipt['blockHash'], 32) == block_hash
        and quantity(receipt['blockNumber']) == block_number
        and identifier(tx['from'], 20) == identifier(receipt['from'], 20) == seller
        and identifier(tx['to'], 20) == identifier(receipt['to'], 20) == buyer
        and quantity(tx['value']) == amount
        and identifier(tx['input'], 32) == marker,
        'refund_transfer_mismatch',
    )
    block = rpc('eth_getBlockByNumber', [hex(block_number), False])
    require(isinstance(block, dict) and identifier(block['hash'], 32) == block_hash and quantity(block['number']) == block_number and isinstance(block['transactions'], list) and block['transactions'].count(outgoing) == 1, 'refund_block_unverified')


def run(args, kit):
    try:
        require(isinstance(args, dict) and set(args) == {'sale_id'}, 'invalid_request')
        sale_id = args['sale_id']
        require(isinstance(sale_id, str) and 0 < len(sale_id) <= 512, 'invalid_request')
        verify_receipt(*load_attempt(sale_id, kit))
        return {'status': 'refund_receipt_verified'}
    except Refusal as error:
        return {'status': 'unverified', 'reason': str(error)}
    except sqlite3.Error:
        return {'status': 'unverified', 'reason': 'ledger_unavailable'}
    except (httpx.HTTPError, KeyError, ValueError, TypeError, OverflowError, RecursionError):
        return {'status': 'unverified', 'reason': 'chain_or_ledger_evidence_unavailable'}
