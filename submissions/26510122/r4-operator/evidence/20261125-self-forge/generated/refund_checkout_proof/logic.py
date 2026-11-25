import base64
import hashlib
import json
import re
import sqlite3
from contextlib import closing

DB = 'state/r4-benefits/benefits.sqlite3'
FIELD = 0xfffffffffffffffffffffffffffffffffffffffffffffffffffffffefffffc2f
ORDER = 0xfffffffffffffffffffffffffffffffebaaedce6af48a03bbfd25e8cd0364141
GENERATOR = (
    0x79be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798,
    0x483ada7726a3c4655da4fbfc0e1108a8fd17b448a68554199c47d08ffb10d4b8,
)
MASK = (1 << 64) - 1
ROTATION = (0, 1, 62, 28, 27, 36, 44, 6, 55, 20, 3, 10, 43, 25, 39, 41, 45, 15, 21, 8, 18, 2, 61, 56, 14)
ROUND_CONSTANT = (
    0x1, 0x8082, 0x800000000000808a, 0x8000000080008000,
    0x808b, 0x80000001, 0x8000000080008081, 0x8000000000008009,
    0x8a, 0x88, 0x80008009, 0x8000000a,
    0x8000808b, 0x800000000000008b, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x800a, 0x800000008000000a,
    0x8000000080008081, 0x8000000000008080, 0x80000001, 0x8000000080008008,
)


class Refusal(Exception):
    pass


def require(condition, reason):
    if not condition:
        raise Refusal(reason)


def keccak256(data):
    rate = 136
    padding = bytearray(rate - len(data) % rate)
    padding[0] = 1
    padding[-1] |= 128
    data += padding
    lanes = [0] * 25
    for offset in range(0, len(data), rate):
        for index in range(rate // 8):
            start = offset + 8 * index
            lanes[index] ^= int.from_bytes(data[start:start + 8], 'little')
        for constant in ROUND_CONSTANT:
            columns = [lanes[x] ^ lanes[x + 5] ^ lanes[x + 10] ^ lanes[x + 15] ^ lanes[x + 20] for x in range(5)]
            mixed = [0] * 25
            for y in range(5):
                for x in range(5):
                    index = x + 5 * y
                    next_column = columns[(x + 1) % 5]
                    value = lanes[index] ^ columns[(x - 1) % 5] ^ (((next_column << 1) | (next_column >> 63)) & MASK)
                    shift = ROTATION[index]
                    mixed[y + 5 * ((2 * x + 3 * y) % 5)] = ((value << shift) | (value >> (64 - shift))) & MASK
            for y in range(5):
                row = 5 * y
                for x in range(5):
                    lanes[row + x] = mixed[row + x] ^ (~mixed[row + (x + 1) % 5] & mixed[row + (x + 2) % 5])
            lanes[0] ^= constant
    return b''.join(lane.to_bytes(8, 'little') for lane in lanes[:4])


def add(left, right):
    if left is None:
        return right
    if right is None:
        return left
    x1, y1 = left
    x2, y2 = right
    if x1 == x2:
        if (y1 + y2) % FIELD == 0:
            return None
        slope = 3 * x1 * x1 * pow(2 * y1, -1, FIELD) % FIELD
    else:
        slope = (y2 - y1) * pow((x2 - x1) % FIELD, -1, FIELD) % FIELD
    x3 = (slope * slope - x1 - x2) % FIELD
    return x3, (slope * (x1 - x3) - y1) % FIELD


def multiply(scalar, point):
    result = None
    while scalar:
        if scalar & 1:
            result = add(result, point)
        point = add(point, point)
        scalar >>= 1
    return result


def personal_hash(message):
    prefix = b'\x19Ethereum Signed Message:\n' + str(len(message)).encode('ascii')
    return keccak256(prefix + message)


def recover_wallet(message, signature):
    reason = 'checkout_signature_invalid'
    require(len(signature) == 65, reason)
    r = int.from_bytes(signature[:32], 'big')
    s = int.from_bytes(signature[32:64], 'big')
    recovery = signature[64]
    if recovery in (27, 28):
        recovery -= 27
    require(recovery in (0, 1) and 0 < r < ORDER and 0 < s < ORDER, reason)
    square = (pow(r, 3, FIELD) + 7) % FIELD
    y = pow(square, (FIELD + 1) // 4, FIELD)
    require(y * y % FIELD == square, reason)
    if y % 2 != recovery:
        y = FIELD - y
    inverse = pow(r, -1, ORDER)
    digest = int.from_bytes(personal_hash(message), 'big')
    public = add(multiply(s * inverse % ORDER, (r, y)), multiply(-digest * inverse % ORDER, GENERATOR))
    require(public is not None, reason)
    encoded = b''.join(coordinate.to_bytes(32, 'big') for coordinate in public)
    return '0x' + keccak256(encoded)[-20:].hex()


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def decode(part):
    require(re.fullmatch(r'[A-Za-z0-9_-]+', part) is not None, 'checkout_encoding_invalid')
    raw = base64.urlsafe_b64decode(part + '=' * (-len(part) % 4))
    require(b64url(raw) == part, 'checkout_encoding_invalid')
    return raw


def claims_from(part):
    raw = decode(part)
    claims = json.loads(raw.decode('utf-8'))
    require(isinstance(claims, dict), 'checkout_encoding_invalid')
    canonical = json.dumps(claims, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')
    require(raw == canonical, 'checkout_encoding_invalid')
    return claims


def address(value):
    require(isinstance(value, str) and re.fullmatch(r'0x[0-9a-fA-F]{40}', value) is not None, 'shop_wallet_mismatch')
    return value.lower()


def load_sale(sale_id):
    with closing(sqlite3.connect('file:' + DB + '?mode=ro', uri=True, timeout=2)) as db:
        db.row_factory = sqlite3.Row
        db.execute('BEGIN')
        require([tuple(row) for row in db.execute('PRAGMA quick_check(1)')] == [('ok',)], 'ledger_unavailable')
        identities = db.execute('SELECT singleton, shop, wallet FROM identity LIMIT 2').fetchall()
        require(len(identities) == 1 and identities[0]['singleton'] == 1, 'shop_identity_unavailable')
        sale = db.execute('SELECT id, unit, sku, price, shop_url, wallet, digest, jwt FROM sale WHERE id=?', (sale_id,)).fetchone()
        require(sale is not None, 'sale_unavailable')
        return identities[0], sale


def run(args, kit):
    try:
        require(isinstance(args, dict) and set(args) == {'sale_id'}, 'invalid_request')
        sale_id = args['sale_id']
        require(isinstance(sale_id, str) and 0 < len(sale_id) <= 512, 'invalid_request')
        identity, sale = load_sale(sale_id)
        seller = address(kit.address('shop'))
        require(identity['shop'] == kit.name and address(identity['wallet']) == address(sale['wallet']) == seller, 'shop_wallet_mismatch')
        checkout = sale['jwt']
        require(isinstance(checkout, str) and 0 < len(checkout) <= 65536, 'checkout_encoding_invalid')
        header, payload, signature = checkout.split('.')
        require(claims_from(header) == {'alg': 'EIP191', 'typ': 'JWT'}, 'checkout_encoding_invalid')
        claims = claims_from(payload)
        signer = recover_wallet((header + '.' + payload).encode('ascii'), decode(signature))
        require(signer == seller, 'checkout_signature_invalid')
        require(
            all(isinstance(sale[key], str) and sale[key] for key in ('shop_url', 'sku', 'unit'))
            and claims.get('id') == sale['id'] and claims.get('shop') == kit.name
            and claims.get('shop_url') == sale['shop_url'] and claims.get('item') == sale['sku']
            and claims.get('unit') == sale['unit'] and claims.get('currency') == 'credits'
            and type(claims.get('price')) is int and type(sale['price']) is int
            and claims['price'] == sale['price'] > 0,
            'checkout_sale_mismatch',
        )
        digest = hashlib.sha256(checkout.encode('ascii')).digest()
        require(sale['digest'] in (digest.hex(), '0x' + digest.hex(), b64url(digest)), 'checkout_digest_mismatch')
        return {'status': 'verified'}
    except Refusal as error:
        return {'status': 'unverified', 'reason': str(error)}
    except sqlite3.Error:
        return {'status': 'unverified', 'reason': 'ledger_unavailable'}
    except (ValueError, TypeError, OverflowError, RecursionError):
        return {'status': 'unverified', 'reason': 'checkout_encoding_invalid'}
