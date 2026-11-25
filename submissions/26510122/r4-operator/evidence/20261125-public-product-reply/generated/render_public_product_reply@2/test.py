import copy
import json
import os
import stat
import time
from types import SimpleNamespace
from unittest.mock import patch

NOW = 1795586230
SKU_A = 'G000000a1'
SKU_B = 'G000000b2'
SKU_C = 'G000000c3'
FILENAME = 'customer_offer_context.json'


class NoKitAccess:
    def __getattribute__(self, name):
        raise AssertionError('tool accessed kit')


def offer(sku, grade, price, expiration):
    return {'unit_ref': 'unit-' + sku, 'sku': sku, 'name': 'PRIVATE_TEST_MARKER',
            'category_path': ['상품'], 'state': 'available', 'grade': grade,
            'price_credits': price, 'standard_fee_credits': 120, 'expires_at': expiration}


def args_for(*pairs):
    return {'items': [{'sku': sku, 'grade': grade} for sku, grade in pairs]}


def metadata(inode, mode, size, uid=1001, links=1, modified=9000):
    return SimpleNamespace(st_dev=1, st_ino=inode, st_mode=mode, st_uid=uid, st_gid=1001,
                           st_nlink=links, st_size=size, st_mtime_ns=modified, st_ctime_ns=9000)


def test(run, kit):
    snapshot = {'schema': 'outseop-r4.customer-offers.v1', 'shop': 'outseop-r4',
                'observed_at': NOW - 5, 'valid_until': NOW + 120,
                'units': [offer(SKU_A, 'A', 43900, NOW + 97), offer(SKU_B, 'B', 2500, None),
                          offer(SKU_C, 'C', 10**12, NOW + 180)]}
    one = args_for((SKU_A, 'A'))
    without_expiry = args_for((SKU_B, 'B'))
    three = args_for((SKU_C, 'C'), (SKU_A, 'A'), (SKU_B, 'B'))

    def invoke(args, context=snapshot, times=(NOW, NOW, NOW, NOW), fault=None, expect_open=True):
        raw = context if type(context) is bytes else json.dumps(context, ensure_ascii=False).encode('utf-8')
        root = os.getcwd()
        root_info = metadata(2, stat.S_IFDIR | 0o700, 0)
        parent_info = metadata(3, stat.S_IFDIR | 0o700, 0)
        file_info = metadata(4, stat.S_IFREG | 0o400, len(raw))
        if fault == 'foreign_owner':
            file_info.st_uid = 2
        if fault == 'parent_owner':
            parent_info.st_uid = 2
        if fault == 'writable_parent':
            parent_info.st_mode |= 0o020
        if fault == 'writable_file':
            file_info.st_mode |= 0o002
        if fault == 'hardlink':
            file_info.st_nlink = 2
        if fault == 'oversize':
            file_info.st_size = 512 * 1024 + 1
        if fault == 'fifo':
            file_info.st_mode = stat.S_IFIFO | 0o400
        opens, closes, reads, checks = [], [], [], []
        position = 0

        def open_file(path, flags, *, dir_fd=None):
            opens.append((path, dir_fd))
            assert flags & os.O_NOFOLLOW
            assert flags & os.O_ACCMODE == os.O_RDONLY
            assert not flags & (os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            if (path, dir_fd) == (root, None):
                assert flags & os.O_DIRECTORY
                if fault == 'root_symlink':
                    raise OSError('PRIVATE_TEST_MARKER')
                return 20
            if (path, dir_fd) == ('host_inputs', 20):
                assert flags & os.O_DIRECTORY
                if fault == 'parent_symlink':
                    raise OSError('PRIVATE_TEST_MARKER')
                return 21
            assert (path, dir_fd) == (FILENAME, 21) and flags & os.O_NONBLOCK
            if fault == 'file_symlink':
                raise OSError('PRIVATE_TEST_MARKER')
            return 22

        def file_stat(fd):
            checks.append(fd)
            if fd == 22 and fault == 'changed' and checks.count(fd) == 2:
                return metadata(4, stat.S_IFREG | 0o400, len(raw), modified=9001)
            return {20: root_info, 21: parent_info, 22: file_info}[fd]

        def path_stat(path, *, dir_fd=None, follow_symlinks=True):
            assert follow_symlinks is False
            if fault == 'replaced' and (path, dir_fd) == (FILENAME, 21):
                return metadata(5, stat.S_IFREG | 0o400, len(raw))
            return {(root, None): root_info, ('host_inputs', 20): parent_info,
                    (FILENAME, 21): file_info}[path, dir_fd]

        def read_file(fd, count):
            nonlocal position
            assert fd == 22 and 0 < count <= 65536
            reads.append(count)
            chunk = raw[position:position + count]
            position += len(chunk)
            return chunk

        with (patch.object(os, 'geteuid', return_value=1001), patch.object(os, 'open', side_effect=open_file),
              patch.object(os, 'fstat', side_effect=file_stat), patch.object(os, 'stat', side_effect=path_stat),
              patch.object(os, 'read', side_effect=read_file), patch.object(os, 'close', side_effect=closes.append),
              patch.object(os, 'write', side_effect=AssertionError('unexpected write')),
              patch.object(time, 'time', side_effect=times)):
            result = run(args, NoKitAccess())
        assert bool(opens) == expect_open
        if fault is None and expect_open:
            assert opens == [(root, None), ('host_inputs', 20), (FILENAME, 21)]
            assert closes == [22, 21, 20] and reads and checks == [20, 21, 22, 22]
        assert 'PRIVATE_TEST_MARKER' not in str(result)
        return result

    def fails(args, reason, **options):
        actual = invoke(args, **options)
        assert actual == {'status': 'unavailable', 'reason': reason}, (reason, actual)

    result = invoke(three)
    assert set(result) == {'status', 'reply', 'observed_at', 'valid_until'}
    assert (result['status'], result['observed_at'], result['valid_until']) == ('rendered', NOW - 5, NOW + 120)
    assert result['reply'].splitlines() == [
        f'{SKU_C} C등급 · 1,000,000,000,000크레딧 · 남은 시간 180초',
        f'{SKU_A} A등급 · 43,900크레딧 · 남은 시간 97초',
        f'{SKU_B} B등급 · 2,500크레딧 · 유통기한 미제공',
        '상품가 기준, 시장 수수료·가스 별도; 결제 전 재고·조건 재확인',
    ]
    assert len(result['reply']) <= 450
    food_snapshot = copy.deepcopy(snapshot)
    food_snapshot['units'][1]['category_path'] = ['food']
    food_reply = invoke(without_expiry, context=food_snapshot)
    assert food_reply == {
        'status': 'rendered',
        'reply': f'{SKU_B} B등급 · 2,500크레딧 · 유통기한 미제공\n'
                 '상품가 기준, 시장 수수료·가스 별도; 결제 전 재고·조건 재확인',
        'observed_at': NOW - 5,
        'valid_until': NOW + 120,
    }
    assert '남은 시간 94초' in invoke(one, times=(NOW, NOW + 2, NOW + 2.5, NOW + 2.5))['reply']
    for bad_args in (None, [], {'items': []}, {'items': True}, {'items': tuple(one['items'])},
                     {'items': one['items'] * 4}, {'items': one['items'] * 2},
                     dict(one, path=FILENAME), dict(one, shop='other'),
                     {'items': [dict(one['items'][0], price_credits=43900)]},
                     {'items': [dict(one['items'][0], text='임의 문구')]},
                     args_for(('../' + SKU_A, 'A')), args_for((SKU_A + '\n', 'A')),
                     args_for((SKU_A, ' A')), args_for((SKU_A, True)), args_for((1.0, 'A')),
                     args_for((True, 'A')), {'items': [None]}, {'items': [{'sku': SKU_A}]}):
        fails(bad_args, 'invalid_args', expect_open=False)

    for key, value in [('observed_at', True), ('valid_until', 1.5), ('schema', 'unknown'), ('shop', 'other')]:
        fails(one, 'invalid_snapshot', context=dict(snapshot, **{key: value}))
    for observed, valid_until in [(NOW + 1, NOW + 80), (NOW - 20, NOW), (NOW, NOW + 151), (NOW, NOW - 1)]:
        fails(one, 'stale_snapshot', context=dict(snapshot, observed_at=observed, valid_until=valid_until))
    fails(without_expiry, 'stale_snapshot', times=(NOW, NOW + 120))
    fails(without_expiry, 'stale_snapshot', times=(NOW, NOW + 119, NOW + 120))
    fails(without_expiry, 'stale_snapshot', times=(NOW, NOW + 119, NOW + 119, NOW + 120))
    fails(without_expiry, 'stale_snapshot', times=(NOW, NOW - 1))
    assert invoke(one, context=dict(snapshot, observed_at=NOW, valid_until=NOW + 150))['status'] == 'rendered'

    raw = json.dumps(snapshot).encode('utf-8')
    fails(one, 'invalid_snapshot', context=b'{"shop":"outseop-r4",' + raw[1:])
    fails(one, 'invalid_snapshot', context=raw.replace(b'"grade": "A"', b'"grade": "A", "grade": "B"'))
    for bad_number in (b'NaN', b'Infinity', b'-Infinity', b'1e400', b'43900.0'):
        fails(one, 'invalid_snapshot', context=raw.replace(b'43900', bad_number))
    fails(one, 'invalid_snapshot', context=b'\xff')
    for key, value in [('unit_ref', '../PRIVATE_TEST_MARKER'), ('unit_ref', ''),
                       ('price_credits', -1), ('price_credits', 0), ('price_credits', True),
                       ('price_credits', 10**12 + 1), ('expires_at', True),
                       ('standard_fee_credits', False), ('category_path', ['상품', 9])]:
        changed = copy.deepcopy(snapshot)
        changed['units'][0][key] = value
        fails(three, 'invalid_snapshot', context=changed)
    changed = copy.deepcopy(snapshot)
    del changed['units'][0]['standard_fee_credits']
    fails(three, 'invalid_snapshot', context=changed)

    for state in ('reserved', 'sold_out', 'expired'):
        changed = copy.deepcopy(snapshot)
        changed['units'][0]['state'] = state
        fails(three, 'selection_unavailable', context=changed)
    changed = copy.deepcopy(snapshot)
    changed['units'][0]['expires_at'] = NOW
    fails(three, 'selection_unavailable', context=changed)
    fails(three, 'selection_unavailable', times=(NOW, NOW + 96, NOW + 96, NOW + 97))
    fails(three, 'selection_unavailable', context=dict(snapshot, units=snapshot['units'][1:]))
    fails(three, 'selection_unavailable', context=dict(snapshot, units=snapshot['units'] + [snapshot['units'][0]]))
    duplicate_reserved = dict(snapshot['units'][0], state='reserved')
    fails(three, 'selection_unavailable', context=dict(snapshot, units=snapshot['units'] + [duplicate_reserved]))
    fails(args_for((SKU_A, 'B')), 'selection_unavailable')

    for fault in ('root_symlink', 'parent_symlink', 'file_symlink', 'foreign_owner', 'parent_owner',
                  'writable_parent', 'writable_file', 'hardlink', 'oversize', 'fifo', 'changed', 'replaced'):
        fails(one, 'source_unavailable', fault=fault)
