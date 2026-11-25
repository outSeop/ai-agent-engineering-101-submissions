import hashlib
import json
import os
import re
import stat
import time

SCHEMA = 'outseop-r4.customer-offers.v1'
SHOP = 'outseop-r4'
DIRECTORY = 'host_inputs'
FILENAME = 'customer_offer_context.json'
MAX_BYTES = 512 * 1024
PAGE_BUDGET = 4600
FRAGMENT_SIZE = 1600
DOC_FIELDS = {'schema', 'shop', 'observed_at', 'valid_until', 'units'}
UNIT_FIELDS = {'unit_ref', 'sku', 'name', 'category_path', 'state', 'grade', 'price_credits', 'standard_fee_credits', 'expires_at'}
ARG_FIELDS = {'op', 'skus', 'min_remaining_seconds', 'offset', 'snapshot', 'fragment_offset', 'fragment_as_of'}
SKU = re.compile(r'G[0-9a-f]{8}')
DIGEST = re.compile(r'[0-9a-f]{64}')


def integer(value, lower=0):
    return type(value) is int and value >= lower


def string(value):
    if type(value) is not str or not value:
        return False
    value.encode('utf-8', errors='strict')
    return True


def matches(pattern, value):
    return type(value) is str and pattern.fullmatch(value) is not None


def fields(value, expected):
    return type(value) is dict and set(value) == expected


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError('duplicate key')
        obj[key] = value
    return obj


def invalid_constant(value):
    raise ValueError('invalid JSON constant')


def read_fixed_file():
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    file_flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    directory = os.open(DIRECTORY, directory_flags)
    try:
        before = os.stat(FILENAME, dir_fd=directory, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > MAX_BYTES:
            raise ValueError('unsafe input file')
        fd = os.open(FILENAME, file_flags, dir_fd=directory)
        try:
            opened = os.fstat(fd)
            if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or opened.st_size > MAX_BYTES:
                raise ValueError('unsafe input file')
            if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                raise ValueError('file replaced during open')
            raw = bytearray()
            while len(raw) <= MAX_BYTES:
                chunk = os.read(fd, min(65536, MAX_BYTES + 1 - len(raw)))
                if not chunk:
                    break
                raw.extend(chunk)
            after = os.fstat(fd)
            if (len(raw) > MAX_BYTES or len(raw) != opened.st_size or after.st_nlink != 1
                    or (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns)
                    != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
                raise ValueError('input changed or exceeds limit')
            return bytes(raw)
        finally:
            os.close(fd)
    finally:
        os.close(directory)


def parse_args(args):
    if type(args) is not dict or set(args) - ARG_FIELDS or args.get('op') != 'context':
        raise ValueError('invalid arguments')
    skus = args.get('skus', [])
    minimum = args.get('min_remaining_seconds', 0)
    offset = args.get('offset', 0)
    fragment_offset = args.get('fragment_offset', 0)
    if type(skus) is not list or len(skus) > 200 or any(not matches(SKU, sku) for sku in skus):
        raise ValueError('invalid SKU list')
    if not integer(minimum) or not integer(offset) or offset > 200:
        raise ValueError('invalid filter or offset')
    if 'snapshot' in args and not matches(DIGEST, args['snapshot']):
        raise ValueError('invalid snapshot')
    if 'fragment_offset' in args or 'fragment_as_of' in args:
        if ('offset' not in args or 'snapshot' not in args or not integer(fragment_offset, 1)
                or fragment_offset % FRAGMENT_SIZE or not integer(args.get('fragment_as_of'))):
            raise ValueError('invalid fragment cursor')
    return set(skus), minimum, offset, fragment_offset


def validate(doc, now):
    if not fields(doc, DOC_FIELDS) or doc['schema'] != SCHEMA or doc['shop'] != SHOP:
        raise ValueError('invalid document')
    observed, until = doc['observed_at'], doc['valid_until']
    if not integer(observed) or not integer(until) or not (observed <= now < until <= observed + 150):
        raise ValueError('invalid validity interval')
    if type(doc['units']) is not list or len(doc['units']) > 200:
        raise ValueError('invalid units')
    refs = set()
    for unit in doc['units']:
        if not fields(unit, UNIT_FIELDS):
            raise ValueError('invalid unit shape')
        ref, path = unit['unit_ref'], unit['category_path']
        if not string(ref) or ref in refs or not string(unit['name']) or not matches(SKU, unit['sku']):
            raise ValueError('invalid unit identifier or name')
        refs.add(ref)
        if not (string(path) or (type(path) is list and path and all(string(part) for part in path))):
            raise ValueError('invalid category path')
        if unit['state'] not in ('available', 'reserved', 'sold_out') or unit['grade'] not in ('A', 'B', 'C'):
            raise ValueError('invalid state or grade')
        if not integer(unit['price_credits'], 1):
            raise ValueError('invalid price')
        for key in ('standard_fee_credits', 'expires_at'):
            if unit[key] is not None and not integer(unit[key]):
                raise ValueError('invalid nullable integer')


def offer(unit, as_of):
    row = dict(unit)
    expiry = row['expires_at']
    row['remaining_seconds'] = None if expiry is None else max(0, expiry - as_of)
    if expiry is not None and expiry <= as_of and row['state'] == 'available':
        row['state'] = 'expired'
    return row


def render(value):
    return json.dumps(value, ensure_ascii=True)


def run(args, kit):
    try:
        skus, minimum, offset, fragment_offset = parse_args(args)
    except ValueError:
        return {'error': 'invalid_args'}
    try:
        raw = read_fixed_file()
        doc = json.loads(raw.decode('utf-8'), object_pairs_hook=unique_object, parse_constant=invalid_constant)
        now = time.time_ns() // 1_000_000_000
        validate(doc, now)
    except (AttributeError, NotImplementedError, OSError, ValueError, RecursionError):
        return {'error': 'invalid_or_unavailable_host_input'}

    snapshot = hashlib.sha256(raw).hexdigest()
    if args.get('snapshot', snapshot) != snapshot:
        return {'error': 'snapshot_changed'}
    as_of = args.get('fragment_as_of', now)
    if not doc['observed_at'] <= as_of <= now:
        return {'error': 'invalid_args'}

    candidates = []
    for index, unit in enumerate(doc['units']):
        if 'skus' in args and unit['sku'] not in skus:
            continue
        expiry = unit['expires_at']
        if 'min_remaining_seconds' in args and (expiry is None or expiry <= now or expiry - now < minimum):
            continue
        candidates.append((index, unit))

    result = {'schema': SCHEMA, 'shop': SHOP, 'observed_at': doc['observed_at'],
              'valid_until': doc['valid_until'], 'as_of': now, 'snapshot': snapshot,
              'total_count': len(candidates), 'returned_count': 0, 'offset': offset,
              'units': [], 'next_args': None}
    next_args = {key: args[key] for key in ('op', 'skus', 'min_remaining_seconds') if key in args}
    next_args['snapshot'] = snapshot
    pending = [(index, unit) for index, unit in candidates if index >= offset]
    if fragment_offset and (not pending or pending[0][0] != offset):
        return {'error': 'fragment_no_longer_matches'}

    for position, (index, unit) in enumerate(pending):
        row = offer(unit, as_of)
        if not fragment_offset:
            result['units'].append(row)
            result['returned_count'] = len(result['units'])
            if len(render(result)) <= PAGE_BUDGET:
                continue
            result['units'].pop()
            result['returned_count'] = len(result['units'])
            if result['units']:
                result['next_args'] = dict(next_args, offset=index)
                break

        serialized = render(row)
        if fragment_offset >= len(serialized):
            return {'error': 'invalid_args'}
        end = min(fragment_offset + FRAGMENT_SIZE, len(serialized))
        complete = end == len(serialized)
        result['row_fragment'] = {'unit_index': index, 'offset': fragment_offset,
                                  'as_of': as_of, 'complete': complete,
                                  'text': serialized[fragment_offset:end]}
        if not complete:
            result['next_args'] = dict(next_args, offset=index, fragment_offset=end, fragment_as_of=as_of)
        elif position + 1 < len(pending):
            result['next_args'] = dict(next_args, offset=pending[position + 1][0])
        break

    # The caller retains filters when following the cursor. Keep them out of the
    # response if their echoed representation would push the page over budget.
    cursor = result['next_args']
    if cursor is not None and len(render(result)) > 5500:
        result['next_args'] = {key: value for key, value in cursor.items() if key not in ('skus', 'min_remaining_seconds')}
        result['carry_filters'] = [key for key in ('skus', 'min_remaining_seconds') if key in args]
    return result
