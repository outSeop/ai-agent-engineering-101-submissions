import json
import math
import os
import re
import stat
import time
from contextlib import ExitStack

MAX_BYTES = 512 * 1024
MAX_CREDITS = 10**12
FILENAME = 'customer_offer_context.json'
SKU = re.compile(r'G[0-9A-Fa-f]{8}')
UNIT_REF = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}')
GRADES = ('A', 'B', 'C')
CONTEXT_KEYS = {'schema', 'shop', 'observed_at', 'valid_until', 'units'}
UNIT_KEYS = {'unit_ref', 'sku', 'name', 'category_path', 'state', 'grade', 'price_credits', 'standard_fee_credits', 'expires_at'}


def unavailable(reason):
    return {'status': 'unavailable', 'reason': reason}


def valid_sku(value):
    return type(value) is str and SKU.fullmatch(value) is not None


def selection(args):
    if type(args) is not dict or set(args) != {'items'}:
        return None
    items = args['items']
    if type(items) is not list or not 1 <= len(items) <= 3:
        return None
    pairs = []
    for item in items:
        if type(item) is not dict or set(item) != {'sku', 'grade'}:
            return None
        sku, grade = item['sku'], item['grade']
        if not valid_sku(sku) or type(grade) is not str or grade not in GRADES:
            return None
        pair = (sku, grade)
        if pair in pairs:
            return None
        pairs.append(pair)
    return pairs


def check_directory(info, uid):
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or info.st_mode & 0o022:
        raise OSError('unsafe directory')


def check_file(info, uid):
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != uid or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o400 or not 0 < info.st_size <= MAX_BYTES):
        raise OSError('unsafe file')


def identity(info):
    return info.st_dev, info.st_ino


def file_metadata(info):
    return (*identity(info), info.st_mode, info.st_uid, info.st_gid, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def read_snapshot():
    uid = os.geteuid()
    root = os.getcwd()
    base_flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
    directory_flags = base_flags | os.O_DIRECTORY
    with ExitStack() as stack:
        root_fd = os.open(root, directory_flags)
        stack.callback(os.close, root_fd)
        root_info = os.fstat(root_fd)
        check_directory(root_info, uid)
        parent_fd = os.open('host_inputs', directory_flags, dir_fd=root_fd)
        stack.callback(os.close, parent_fd)
        parent_info = os.fstat(parent_fd)
        check_directory(parent_info, uid)
        fd = os.open(FILENAME, base_flags | os.O_NONBLOCK, dir_fd=parent_fd)
        stack.callback(os.close, fd)
        before = os.fstat(fd)
        check_file(before, uid)
        data = bytearray()
        while len(data) <= before.st_size:
            chunk = os.read(fd, min(65536, before.st_size + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        after = os.fstat(fd)
        named_file = os.stat(FILENAME, dir_fd=parent_fd, follow_symlinks=False)
        named_parent = os.stat('host_inputs', dir_fd=root_fd, follow_symlinks=False)
        named_root = os.stat(root, follow_symlinks=False)
        check_file(after, uid)
        check_file(named_file, uid)
        check_directory(named_parent, uid)
        check_directory(named_root, uid)
        if (len(data) != before.st_size or file_metadata(before) != file_metadata(after)
                or file_metadata(after) != file_metadata(named_file)
                or identity(parent_info) != identity(named_parent)
                or identity(root_info) != identity(named_root)):
            raise OSError('source changed')
        return data


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate key')
        result[key] = value
    return result


def reject_number(_):
    raise ValueError('invalid number')


def integer(value, minimum=0, maximum=None):
    return type(value) is int and value >= minimum and (maximum is None or value <= maximum)


def valid_unit(unit):
    if type(unit) is not dict or set(unit) != UNIT_KEYS:
        return False
    ref = unit['unit_ref']
    path = unit['category_path']
    fee = unit['standard_fee_credits']
    expiry = unit['expires_at']
    return (type(ref) is str and UNIT_REF.fullmatch(ref) is not None and '..' not in ref
            and valid_sku(unit['sku']) and type(unit['name']) is str
            and (type(path) is str or (type(path) is list and all(type(part) is str for part in path)))
            and type(unit['state']) is str and bool(unit['state'])
            and type(unit['grade']) is str and unit['grade'] in GRADES
            and integer(unit['price_credits'], 1, MAX_CREDITS)
            and (fee is None or integer(fee))
            and (expiry is None or integer(expiry)))


def run(args, kit):
    requested = selection(args)
    if requested is None:
        return unavailable('invalid_args')
    read_start = time.time()
    try:
        raw = read_snapshot()
    except (OSError, AttributeError, NotImplementedError):
        return unavailable('source_unavailable')
    try:
        context = json.loads(raw.decode('utf-8'), object_pairs_hook=unique_object,
                             parse_constant=reject_number, parse_float=reject_number)
    except (ValueError, RecursionError):
        return unavailable('invalid_snapshot')
    if (type(context) is not dict or set(context) != CONTEXT_KEYS
            or context['schema'] != 'outseop-r4.customer-offers.v1' or context['shop'] != 'outseop-r4'
            or not integer(context['observed_at']) or not integer(context['valid_until'])
            or type(context['units']) is not list):
        return unavailable('invalid_snapshot')
    observed, valid_until = context['observed_at'], context['valid_until']
    if not observed <= read_start < valid_until <= observed + 150:
        return unavailable('stale_snapshot')
    matches = {pair: [] for pair in requested}
    for unit in context['units']:
        if not valid_unit(unit):
            return unavailable('invalid_snapshot')
        pair = (unit['sku'], unit['grade'])
        if pair in matches:
            matches[pair].append(unit)
    read_end = time.time()
    if not read_start <= read_end < valid_until:
        return unavailable('stale_snapshot')
    selected = []
    for pair in requested:
        rows = matches[pair]
        if len(rows) != 1 or rows[0]['state'] != 'available':
            return unavailable('selection_unavailable')
        selected.append(rows[0])
    output_time = time.time()
    if not read_end <= output_time < valid_until:
        return unavailable('stale_snapshot')
    lines = []
    for row in selected:
        expires_at = row['expires_at']
        if expires_at is not None and expires_at <= output_time:
            return unavailable('selection_unavailable')
        remaining = ('유통기한 미제공(비식품)' if expires_at is None
                     else f'남은 시간 {max(0, expires_at - math.ceil(output_time))}초')
        lines.append(f"{row['sku']} {row['grade']}등급 · {row['price_credits']:,}크레딧 · {remaining}")
    lines.append('상품가 기준, 시장 수수료·가스 별도; 결제 전 재고·조건 재확인')
    reply = '\n'.join(lines)
    if len(reply) > 450:
        return unavailable('reply_too_long')
    final_time = time.time()
    if not output_time <= final_time < valid_until:
        return unavailable('stale_snapshot')
    if any(row['expires_at'] is not None and row['expires_at'] <= final_time for row in selected):
        return unavailable('selection_unavailable')
    return {'status': 'rendered', 'reply': reply, 'observed_at': observed, 'valid_until': valid_until}
