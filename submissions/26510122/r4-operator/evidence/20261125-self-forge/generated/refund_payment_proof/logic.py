import base64
import hashlib
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


def chain_id(value, size):
    require(isinstance(value, str) and re.fullmatch(r'0x[0-9a-fA-F]{%d}' % (size * 2), value) is not None, 'invalid_chain_identifier')
    normalized = value.lower()
    require(int(normalized, 16) != 0, 'invalid_chain_identifier')
    return normalized


def quantity(value):
    require(isinstance(value, str) and re.fullmatch(r'0x(?:0|[1-9a-fA-F][0-9a-fA-F]{0,63})', value) is not None, 'invalid_rpc_quantity')
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


def load_sale(sale_id):
    with closing(sqlite3.connect('file:' + DB + '?mode=ro', uri=True, timeout=2)) as db:
        db.row_factory = sqlite3.Row
        db.execute('BEGIN')
        require([tuple(row) for row in db.execute('PRAGMA quick_check(1)')] == [('ok',)], 'ledger_unavailable')
        identities = db.execute('SELECT singleton, shop, wallet FROM identity LIMIT 2').fetchall()
        require(len(identities) == 1 and identities[0]['singleton'] == 1, 'shop_identity_unavailable')
        sale = db.execute('SELECT id, wallet, payer, payment, fee_payment, jwt, digest, status, price, expected_wei, fee_wei, gas_cap_wei, fee_wallet FROM sale WHERE id=?', (sale_id,)).fetchone()
        require(sale is not None, 'sale_unavailable')
        require(sale['status'] in ('paid', 'missing', 'settled'), 'payment_state_unverified')
        payment = chain_id(sale['payment'], 32)
        matches = db.execute('SELECT id FROM sale WHERE payment = ? COLLATE NOCASE LIMIT 2', (payment,)).fetchall()
        require([row['id'] for row in matches] == [sale_id], 'original_payment_link_ambiguous')
        return identities[0], sale


def receipt_gas(tx_hash, sender, recipient, amount, checkout_data):
    tx = rpc('eth_getTransactionByHash', [tx_hash])
    receipt = rpc('eth_getTransactionReceipt', [tx_hash])
    require(isinstance(tx, dict) and isinstance(receipt, dict), 'chain_evidence_unavailable')
    require(quantity(receipt['status']) == 1, 'original_transfer_unsuccessful')
    require(
        chain_id(tx['hash'], 32) == chain_id(receipt['transactionHash'], 32) == tx_hash
        and chain_id(tx['blockHash'], 32) == chain_id(receipt['blockHash'], 32)
        and quantity(tx['blockNumber']) == quantity(receipt['blockNumber'])
        and chain_id(tx['from'], 20) == chain_id(receipt['from'], 20) == sender
        and chain_id(tx['to'], 20) == chain_id(receipt['to'], 20) == recipient
        and quantity(tx['value']) == amount
        and isinstance(tx['input'], str) and tx['input'].lower() == checkout_data,
        'original_transfer_mismatch',
    )
    return quantity(receipt['gasUsed']) * quantity(receipt['effectiveGasPrice'])


def verify_payments(sale, seller):
    buyer = chain_id(sale['payer'], 20)
    require(buyer != seller, 'original_payer_mismatch')
    price = sale['price']
    require(type(price) is int and price > 0, 'invalid_ledger_amount')
    received = wei(sale['expected_wei'])
    market_fee = wei(sale['fee_wei'])
    gas_cap = wei(sale['gas_cap_wei'])
    checkout = sale['jwt']
    require(isinstance(checkout, str) and 0 < len(checkout) <= 65536, 'checkout_binding_unverified')
    digest = hashlib.sha256(checkout.encode('ascii')).digest()
    data = '0x' + digest.hex()
    encoded = base64.urlsafe_b64encode(digest).decode('ascii').rstrip('=')
    require(sale['digest'] in (data, digest.hex(), encoded), 'checkout_binding_unverified')
    response = httpx.get(CHAIN_FACTS, timeout=4)
    response.raise_for_status()
    facts = response.json()
    configured_chain = facts['chain_id']
    require(facts['rpc'] == RPC and type(configured_chain) is int and configured_chain > 0 and quantity(rpc('eth_chainId', [])) == configured_chain, 'chain_mismatch')
    credit = facts['credit_wei']
    bps = facts['market_fee_bps']
    network_fee = facts['network_fee_credits']
    require(type(credit) is int and credit > 0 and type(bps) is int and 0 <= bps <= 10000 and type(network_fee) is int and network_fee >= 0 and network_fee % 2 == 0, 'fee_terms_unverified')
    market = chain_id(facts['market_address'], 20)
    require(chain_id(sale['fee_wallet'], 20) == market and market not in (buyer, seller), 'market_fee_wallet_mismatch')
    fee_credits = price * bps // 10000
    require(received > 0 and received == (price - fee_credits - network_fee // 2) * credit and market_fee == 2 * fee_credits * credit, 'original_amount_mismatch')
    original = chain_id(sale['payment'], 32)
    fee_payment = sale['fee_payment']
    if market_fee:
        fee_payment = chain_id(fee_payment, 32)
        require(fee_payment != original, 'original_transfer_mismatch')
    else:
        require(fee_payment in ('', None), 'unexpected_fee_transfer')
    actual_gas = receipt_gas(original, buyer, seller, received, data)
    if market_fee:
        actual_gas += receipt_gas(fee_payment, buyer, market, market_fee, data)
    return received, market_fee, min(actual_gas, gas_cap)


def run(args, kit):
    try:
        require(isinstance(args, dict) and set(args) == {'sale_id'}, 'invalid_request')
        sale_id = args['sale_id']
        require(isinstance(sale_id, str) and 0 < len(sale_id) <= 512, 'invalid_request')
        identity, sale = load_sale(sale_id)
        seller = chain_id(kit.address('shop'), 20)
        require(identity['shop'] == kit.name and chain_id(identity['wallet'], 20) == chain_id(sale['wallet'], 20) == seller, 'shop_wallet_mismatch')
        verify_payments(sale, seller)
        return {'status': 'payment_evidence_verified'}
    except Refusal as error:
        return {'status': 'unverified', 'reason': str(error)}
    except sqlite3.Error:
        return {'status': 'unverified', 'reason': 'ledger_unavailable'}
    except (httpx.HTTPError, KeyError, TypeError, ValueError, OverflowError):
        return {'status': 'unverified', 'reason': 'chain_or_ledger_evidence_unavailable'}
