READER_SHA = 'a122aed15c9462dfb6ed2c77665e6fbb82de7720633adb03ccf0ec7b1b4e45ff'
READER_SOURCE = '''import hashlib
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
PAGE_BUDGET = 5400
FRAGMENT_SIZE = 800
DOC_FIELDS = {'schema', 'shop', 'observed_at', 'valid_until', 'units'}
UNIT_FIELDS = {'unit_ref', 'sku', 'name', 'category_path', 'state', 'grade', 'price_credits', 'standard_fee_credits', 'expires_at'}
FILTER_FIELDS = ('skus', 'min_remaining_seconds')
ARG_FIELDS = {'op', *FILTER_FIELDS, 'offset', 'snapshot', 'query_as_of', 'filter_digest', 'fragment_offset', 'fragment_as_of'}
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
    if 'query_as_of' in args or 'filter_digest' in args:
        if ('offset' not in args or 'snapshot' not in args or not integer(args.get('query_as_of'))
                or not matches(DIGEST, args.get('filter_digest'))):
            raise ValueError('invalid page cursor')
    if 'fragment_offset' in args or 'fragment_as_of' in args:
        if ('offset' not in args or 'snapshot' not in args or not integer(fragment_offset, 1)
                or fragment_offset % FRAGMENT_SIZE or not integer(args.get('fragment_as_of'))):
            raise ValueError('invalid fragment cursor')
    return set(skus) if 'skus' in args else None, args.get('min_remaining_seconds'), offset, fragment_offset


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


def meets_minimum(expiry, minimum, as_of):
    return minimum is None or (expiry is not None and expiry > as_of and expiry - as_of >= minimum)


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
        fingerprint = render([None if skus is None else sorted(skus), minimum])
        filter_digest = hashlib.sha256(fingerprint.encode('ascii')).hexdigest()
    except ValueError:
        return {'error': 'invalid_args'}
    if args.get('filter_digest', filter_digest) != filter_digest:
        return {'error': 'cursor_filters_changed'}

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
    query_as_of = args.get('query_as_of', now)
    as_of = args.get('fragment_as_of', now)
    observed = doc['observed_at']
    if not observed <= query_as_of <= now or not observed <= as_of <= now:
        return {'error': 'invalid_args'}
    if 'query_as_of' in args and as_of < query_as_of:
        return {'error': 'invalid_args'}

    candidates = []
    for index, unit in enumerate(doc['units']):
        if skus is not None and unit['sku'] not in skus:
            continue
        expiry = unit['expires_at']
        if not meets_minimum(expiry, minimum, query_as_of):
            continue
        if not meets_minimum(expiry, minimum, now):
            return {'error': 'filter_results_changed'}
        candidates.append((index, unit))

    result = {'schema': SCHEMA, 'shop': SHOP, 'observed_at': observed,
              'valid_until': doc['valid_until'], 'as_of': as_of, 'snapshot': snapshot,
              'total_count': len(candidates), 'returned_count': 0, 'offset': offset,
              'units': [], 'next_args': None}
    cursor = {key: args[key] for key in FILTER_FIELDS if key in args}
    cursor.update(op='context', snapshot=snapshot, query_as_of=query_as_of, filter_digest=filter_digest)
    pending = [(index, unit) for index, unit in candidates if index >= offset]
    if fragment_offset and (not pending or pending[0][0] != offset):
        return {'error': 'fragment_no_longer_matches'}

    for position, (index, unit) in enumerate(pending):
        following = dict(cursor, offset=pending[position + 1][0]) if position + 1 < len(pending) else None
        row = offer(unit, as_of)
        if not fragment_offset:
            result['units'].append(row)
            result['returned_count'] = len(result['units'])
            result['next_args'] = following
            if len(render(result)) <= PAGE_BUDGET:
                continue
            result['units'].pop()
            result['returned_count'] = len(result['units'])
            if result['units']:
                result['next_args'] = dict(cursor, offset=index)
                return result

        expiry = row['expires_at']
        if row['state'] == 'available' and expiry is not None and expiry <= now:
            return {'error': 'fragment_unit_expired'}
        serialized = render(row)
        if fragment_offset >= len(serialized):
            return {'error': 'invalid_args'}
        end = min(fragment_offset + FRAGMENT_SIZE, len(serialized))
        complete = end == len(serialized)
        result['row_fragment'] = {'unit_index': index, 'offset': fragment_offset,
                                  'as_of': as_of, 'complete': complete,
                                  'text': serialized[fragment_offset:end]}
        result['next_args'] = following if complete else dict(
            cursor, offset=index, fragment_offset=end, fragment_as_of=as_of)
        if len(render(result)) > PAGE_BUDGET:
            return {'error': 'continuation_exceeds_response_budget'}
        return result

    return result
'''

import hashlib
import json
import os
import re
import stat
import time
import unicodedata
from types import FunctionType

BASE_FILE = 'broker_context_base.json'
LIMIT = 200
OBSERVATION_LIMIT = 6000
BASE_KEYS = {'outcome', 'inventory', 'verified_account', 'redeemable_mileage', 'preferences', 'wait', 'wait_discount', 'prior_offer', 'transfer_reference_present'}
BASE_ROW_KEYS = {'sku', 'name', 'grade', 'category', 'reference_price', 'min_base', 'preferred_price', 'stock_status', 'available', 'wait_eligible'}
SKU_PATTERN = re.compile(r'[FG][A-Fa-f0-9]{8}')
DIGEST_PATTERN = re.compile(r'[0-9a-f]{64}')
CATEGORY_PATTERN = re.compile(r'[a-z][a-z0-9_-]{0,31}')
CATEGORIES = {'appliances', 'clothing', 'food', 'household', 'kitchen', 'stationery'}
SECRET_SHAPE = re.compile(
    r'(?:[0-9a-f]{40,}|[a-z0-9_-]{43,}|(?:sk|pk|ghp|gho|github_pat|xox[baprs]|api[_-]?key)[_:= -][a-z0-9_-]{12,}'
    r'|AIza[a-z0-9_-]{20,}|AKIA[a-z0-9]{16}|eyJ[a-z0-9_-]+\.[a-z0-9_-]+\.[a-z0-9_-]+'
    r'|-----BEGIN [A-Z ]*PRIVATE KEY-----|Bearer\s+\S+'
    r'|[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,})', re.I)
PHONE_SHAPE = re.compile(
    r'(?<!\d)(?:'
    r'(?:\(0(?:1[016789]|2|[3-6][1-5]|[78]0|50[2-8])\)|0(?:1[016789]|2|[3-6][1-5]|[78]0|50[2-8]))'
    r'[ \t.-]*\d{3,4}[ \t.-]*\d{4}'
    r'|\+(?=[1-9])(?:[ \t().-]*\d){8,15}'
    r'|00(?=[1-9]\d{0,2}[ \t(.-])(?:[ \t().-]*\d){8,15}'
    r'|\(?[2-9]\d{2}\)?[ \t.-]+[2-9]\d{2}[ \t.-]+\d{4}'
    r')(?!\d)')
COLUMNS = ('sku', 'name', 'grade', 'category', 'preferred_price', 'stock_status', 'available', 'wait_eligible', 'reference_price', 'min_base', 'state', 'category_path', 'remaining_seconds')
DETAIL_KEYS = {'op', 'snapshot', 'detail_pin', 'as_of', 'row', 'sku'}


class ContextError(ValueError):
    pass


class OwnedInputOS:
    def __getattr__(self, name):
        return getattr(os, name)

    @staticmethod
    def _check(info):
        if info.st_uid not in (0, os.geteuid()) or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise ValueError('unsafe input ownership or mode')
        return info

    def open(self, path, flags, **kwargs):
        fd = os.open(path, flags, **kwargs)
        if flags & os.O_DIRECTORY:
            try:
                info = self._check(os.fstat(fd))
                if not stat.S_ISDIR(info.st_mode):
                    raise ValueError('unsafe directory')
            except Exception:
                os.close(fd)
                raise
        return fd

    def stat(self, path, **kwargs):
        return self._check(os.stat(path, **kwargs))

    def fstat(self, fd):
        return self._check(os.fstat(fd))


def load_reader():
    source = READER_SOURCE.encode('utf-8')
    if hashlib.sha256(source).hexdigest() != READER_SHA:
        raise ContextError('reader_source_pin_mismatch')
    namespace = {'__name__': 'pinned_read_customer_offers_v2'}
    exec(compile(source, '<pinned-read-customer-offers-v2>', 'exec'), namespace)
    namespace['os'] = OwnedInputOS()
    return namespace


def exact(obj, keys):
    return type(obj) is dict and set(obj) == keys


def matches(pattern, value):
    return type(value) is str and pattern.fullmatch(value) is not None


def integer(value, minimum=0):
    return type(value) is int and value >= minimum


def sku(value):
    return matches(SKU_PATTERN, value)


def check_public_text(value):
    value.encode('utf-8', errors='strict')
    normalized = ''.join(char for char in unicodedata.normalize('NFKC', value)
                         if unicodedata.category(char) != 'Cf')
    if not normalized.strip() or SECRET_SHAPE.search(normalized) or PHONE_SHAPE.search(normalized):
        raise ValueError('unsafe public text')


def validate_base(base):
    if not exact(base, BASE_KEYS) or base['outcome'] != 'context':
        raise ValueError('base shape')
    for flag in ('verified_account', 'transfer_reference_present'):
        if type(base[flag]) is not bool:
            raise ValueError('base flag')
    for amount in ('redeemable_mileage', 'wait_discount'):
        if not integer(base[amount]):
            raise ValueError('base amount')
    if base['wait'] is not None and not sku(base['wait']):
        raise ValueError('base wait')
    prior = base['prior_offer']
    if prior is not None and not (exact(prior, {'sku', 'base'}) and sku(prior['sku']) and integer(prior['base'], 1)):
        raise ValueError('base prior offer')
    preferences = base['preferences']
    if type(preferences) is not list or len(preferences) > 10:
        raise ValueError('base preferences')
    for row in preferences:
        if not exact(row, {'kind', 'value', 'sentiment', 'provenance'}):
            raise ValueError('base preference shape')
        kind, value = row['kind'], row['value']
        allowed_value = (kind == 'sku' and sku(value)) or (kind == 'category' and type(value) is str and value in CATEGORIES)
        if not allowed_value or row['sentiment'] not in ('likes', 'avoids') or row['provenance'] != 'customer_self_report':
            raise ValueError('base preference value')
    inventory = base['inventory']
    if type(inventory) is not list:
        raise ValueError('base inventory type')
    if len(inventory) > LIMIT:
        raise ContextError('inventory_capacity_exceeded')
    available_skus = set()
    pending = []
    for row in inventory:
        if not exact(row, BASE_ROW_KEYS) or not sku(row['sku']):
            raise ValueError('base inventory shape')
        name, category = row['name'], row['category']
        if type(name) is not str or len(name) > 120:
            raise ValueError('base product name')
        check_public_text(name)
        if category is not None:
            if not matches(CATEGORY_PATTERN, category):
                raise ValueError('base category')
            check_public_text(category)
        if row['grade'] not in ('A', 'B', 'C'):
            raise ValueError('base grade')
        if any(not integer(row[key], 1) for key in ('reference_price', 'min_base', 'preferred_price')):
            raise ValueError('base inventory price')
        status = row['stock_status']
        if status not in ('available', 'reserved_pending', 'reconciling'):
            raise ValueError('base stock status')
        if row['available'] is not (status == 'available') or type(row['wait_eligible']) is not bool:
            raise ValueError('base stock flags')
        if row['wait_eligible'] and status != 'reserved_pending':
            raise ValueError('base wait status')
        if row['available']:
            available_skus.add(row['sku'].lower())
        else:
            pending.append(row)
    if any(row['wait_eligible'] and row['sku'].lower() in available_skus for row in pending):
        raise ValueError('base wait conflicts with available stock')
    return pending


def collect(reader, kit, query):
    filters = {key: query[key] for key in ('skus', 'min_remaining_seconds') if key in query}
    sku_filter = sorted(set(filters['skus'])) if 'skus' in filters else None
    fingerprint = json.dumps([sku_filter, filters.get('min_remaining_seconds')], ensure_ascii=True)
    digest = hashlib.sha256(fingerprint.encode('ascii')).hexdigest()
    req = dict(query)
    first = None
    units = []
    fragments = []
    fragment_length = 0
    pages = 0
    metadata = ('schema', 'shop', 'snapshot', 'observed_at', 'valid_until', 'total_count')
    for _ in range(5000):
        page = reader(req, kit)
        pages += 1
        if 'error' in page:
            raise ContextError(page['error'])
        if first is None:
            first = page
        if any(page[key] != first[key] for key in metadata):
            raise ContextError('page_context_changed')
        if (page['offset'] != req.get('offset', 0) or page['returned_count'] != len(page['units'])
                or not first['as_of'] <= page['as_of'] < first['valid_until']):
            raise ContextError('invalid_page')
        if not integer(page['total_count']) or page['total_count'] > LIMIT:
            raise ContextError('inventory_capacity_exceeded')
        units.extend(page['units'])
        fragment = page.get('row_fragment')
        following = page['next_args']
        if fragment is not None:
            if (page['units'] or fragment['unit_index'] != page['offset']
                    or fragment['offset'] != fragment_length or fragment['as_of'] != page['as_of']
                    or not 0 < len(fragment['text']) <= 800):
                raise ContextError('invalid_fragment_sequence')
            fragments.append(fragment['text'])
            fragment_length += len(fragment['text'])
            if fragment['complete']:
                units.append(json.loads(''.join(fragments)))
                fragments = []
                fragment_length = 0
        elif fragments:
            raise ContextError('missing_fragment')
        if len(units) > page['total_count']:
            raise ContextError('page_count_mismatch')
        if following is None:
            break
        expected = dict(filters, op='context', snapshot=first['snapshot'], query_as_of=first['as_of'], filter_digest=digest)
        if fragments:
            expected.update(offset=page['offset'], fragment_offset=fragment_length, fragment_as_of=page['as_of'])
        else:
            offset = following.get('offset')
            if not integer(offset) or not page['offset'] < offset < LIMIT:
                raise ContextError('invalid_page_progress')
            expected['offset'] = offset
        if following != expected:
            raise ContextError('cursor_context_changed')
        req = following
    else:
        raise ContextError('page_capacity_exceeded')
    if fragments or len(units) != first['total_count'] or len({row['unit_ref'] for row in units}) != len(units):
        raise ContextError('incomplete_inventory')
    verification = reader(dict(filters, op='context', offset=LIMIT, snapshot=first['snapshot'], query_as_of=first['as_of'], filter_digest=digest), kit)
    if 'error' in verification:
        raise ContextError(verification['error'])
    if (any(verification[key] != first[key] for key in metadata) or verification['offset'] != LIMIT
            or verification['returned_count'] != 0 or verification['next_args'] is not None
            or not first['as_of'] <= verification['as_of'] < first['valid_until']):
        raise ContextError('final_snapshot_changed')
    return first, units, pages, verification['as_of']


def combine(units, pending, as_of, checked_at):
    rows = []
    excluded = {'expired': 0, 'reserved': 0, 'sold_out': 0}
    available_skus = set()
    for unit in units:
        state, expiry = unit['state'], unit['expires_at']
        path = unit['category_path']
        parts = path if type(path) is list else [path]
        try:
            check_public_text(unit['name'])
            for part in parts:
                check_public_text(part)
            if len(parts) > 1:
                check_public_text(' '.join(parts))
        except ValueError:
            raise ContextError('unsafe_public_text') from None
        if state == 'expired' and expiry > as_of:
            raise ContextError('availability_changed_during_collection')
        if state != 'available':
            excluded[state] += 1
            continue
        if expiry is not None and expiry <= checked_at:
            raise ContextError('availability_changed_during_collection')
        root = parts[0]
        rows.append({'sku': unit['sku'], 'name': unit['name'], 'grade': unit['grade'],
                     'category': root if root in CATEGORIES else None, 'category_path': path,
                     'preferred_price': unit['price_credits'], 'stock_status': 'available',
                     'available': True, 'wait_eligible': False, 'state': state,
                     'reference_price': None, 'min_base': None,
                     'remaining_seconds': None if expiry is None else expiry - as_of})
        available_skus.add(unit['sku'].lower())
    for row in pending:
        rows.append(dict(row, state=None, category_path=None, remaining_seconds=None,
                         wait_eligible=row['wait_eligible'] and row['sku'].lower() not in available_skus))
    if len(rows) > LIMIT:
        raise ContextError('inventory_capacity_exceeded')
    return rows, excluded


def render(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def pack(rows, limit):
    common, columns, lookup, values_by_column = {}, [], {}, []
    for key in COLUMNS:
        values = [row[key] for row in rows]
        if limit is not None and key == 'name':
            values = [value[:limit] for value in values]
        if limit is not None and key == 'category_path':
            values = [value[:1] if type(value) is list else value for value in values]
        if values and all(value == values[0] for value in values):
            common[key] = values[0]
            continue
        columns.append(key)
        if values:
            indexes = {}
            unique = []
            for value in values:
                encoded = render(value)
                if encoded not in indexes:
                    indexes[encoded] = len(unique)
                    unique.append(value)
            indices = [indexes[render(value)] for value in values]
            if len(render({key: unique})) + len(render(indices)) + 1 < len(render(values)):
                values = indices
                lookup[key] = unique
        values_by_column.append(values)
    return {'columns': columns, 'common': common, 'lookup': lookup,
            'rows': [list(cells) for cells in zip(*values_by_column)] if columns else [[] for row in rows],
            'text_limit': limit}


def detail(args, rows, metadata):
    index = args['row']
    if index >= len(rows) or rows[index]['sku'] != args['sku']:
        raise ContextError('detail_row_not_found')
    row = rows[index]
    result = dict(metadata, row=index, sku=row['sku'], name=row['name'], category_path=row['category_path'], category=row['category'])
    if 'offset' not in args and len(render(result)) <= OBSERVATION_LIMIT:
        return result
    text = render({'name': row['name'], 'category_path': row['category_path'], 'category': row['category']})
    offset = args.get('offset', 0)
    if offset >= len(text):
        raise ContextError('invalid_args')
    end = min(len(text), offset + 800)
    following = dict(args, offset=end) if end < len(text) else None
    return dict(metadata, row=index, sku=row['sku'], fragment={'offset': offset, 'text': text[offset:end]}, next_args=following)


def run(args, kit):
    is_detail = type(args) is dict and args.get('op') == 'details'
    if is_detail:
        if (set(args) - {'offset'} != DETAIL_KEYS or not matches(DIGEST_PATTERN, args['snapshot'])
                or not matches(DIGEST_PATTERN, args['detail_pin']) or not sku(args['sku'])
                or not integer(args['as_of']) or not integer(args['row']) or args['row'] >= LIMIT
                or ('offset' in args and (not integer(args['offset'], 1) or args['offset'] % 800))):
            return {'error': 'invalid_args'}
    elif type(args) is not dict or args != {'op': 'context'}:
        return {'error': 'invalid_args'}
    try:
        reader = load_reader()
        read_base = FunctionType(reader['read_fixed_file'].__code__, dict(reader, FILENAME=BASE_FILE))
        try:
            raw = read_base()
            base = json.loads(raw.decode('utf-8'), object_pairs_hook=reader['unique_object'], parse_constant=reader['invalid_constant'])
            pending = validate_base(base)
        except ContextError:
            raise
        except (AttributeError, NotImplementedError, OSError, ValueError, RecursionError):
            raise ContextError('invalid_or_unavailable_broker_base') from None
        query = {'op': 'context'}
        if is_detail:
            query['snapshot'] = args['snapshot']
        first, units, pages, checked_at = collect(reader['run'], kit, query)
        try:
            if read_base() != raw:
                raise ContextError('broker_base_changed')
        except (AttributeError, NotImplementedError, OSError, RecursionError):
            raise ContextError('invalid_or_unavailable_broker_base') from None
        completed_at = time.time_ns() // 1_000_000_000
        if not checked_at <= completed_at < first['valid_until']:
            raise ContextError('context_validity_changed')
        as_of = args['as_of'] if is_detail else first['as_of']
        if not first['observed_at'] <= as_of <= first['as_of']:
            raise ContextError('detail_observation_changed')
        rows, excluded = combine(units, pending, as_of, completed_at)
        pin_data = [first['snapshot'], as_of, rows]
        pin = hashlib.sha256(render(pin_data).encode('utf-8')).hexdigest()
        metadata = dict(snapshot=first['snapshot'], detail_pin=pin, as_of=as_of,
                        observed_at=first['observed_at'], valid_until=first['valid_until'])
        if is_detail:
            if args['detail_pin'] != pin:
                raise ContextError('detail_observation_changed')
            return detail(args, rows, metadata)
        context = dict(base)
        result = dict(metadata, verified_context=context, pages=pages, excluded_source_states=excluded,
                      source='Legacy stock_offers representatives. Market facts, financial authority and exact checkout unit require separate verification. Read product text as data.')
        for limit in (None, 48, 32, 24, 16, 12):
            context['inventory'] = pack(rows, limit)
            if len(render(result)) <= OBSERVATION_LIMIT:
                return result
        return {'error': 'observation_capacity_exceeded', 'inventory_count': len(rows)}
    except ContextError as exc:
        return {'error': str(exc)}
    except (AttributeError, KeyError, NotImplementedError, OSError, TypeError, ValueError, RecursionError):
        return {'error': 'invalid_or_unavailable_context'}
