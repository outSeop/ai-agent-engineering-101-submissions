import copy
import json
import os
import stat
import time
from types import SimpleNamespace
from unittest.mock import patch

NOW = 1795596402
FILENAME = 'customer_offer_context.json'
A = 'G00000001'
B = 'G00000002'
C = 'G00000003'


class NoKitAccess:
    def __getattribute__(self, name):
        raise AssertionError('unexpected kit access')


def offer(number, **changes):
    unit = {'unit_ref': f'ref-{number}', 'sku': f'G{number:08X}', 'name': '신선한 빨간 사과',
            'category_path': ['식품', '과일'], 'state': 'available', 'grade': 'A',
            'price_credits': number + 100, 'standard_fee_credits': 2, 'expires_at': NOW + 80}
    return dict(unit, **changes)


def snapshot(units):
    return {'schema': 'outseop-r4.customer-offers.v1', 'shop': 'outseop-r4', 'observed_at': NOW - 5,
            'valid_until': NOW + 120, 'units': units}


def info(inode, mode, size=0, uid=1001, links=1, modified=9000):
    return SimpleNamespace(st_dev=1, st_ino=inode, st_mode=mode, st_uid=uid, st_gid=1001,
                           st_nlink=links, st_size=size, st_mtime_ns=modified, st_ctime_ns=9000)


def test(run, kit):
    base = snapshot([offer(1), offer(2, grade='B', expires_at=None),
                     offer(3, name='파란 컵', category_path='생활', expires_at=NOW + 30)])
    render_a = {'op': 'render', 'items': [{'sku': A, 'grade': 'A'}]}

    def invoke(args, context=base, at=NOW, times=None, fault=None, expect_open=True):
        raw = context if type(context) is bytes else json.dumps(context, ensure_ascii=False).encode('utf-8')
        root = os.getcwd()
        dirs = {20: info(2, stat.S_IFDIR | 0o700), 21: info(3, stat.S_IFDIR | 0o700)}
        file_info = info(4, stat.S_IFREG | 0o400, len(raw))
        if fault == 'root_mode':
            dirs[20].st_mode |= 0o002
        if fault == 'parent_mode':
            dirs[21].st_mode |= 0o020
        if fault == 'parent_owner':
            dirs[21].st_uid = 2
        if fault == 'owner':
            file_info.st_uid = 2
        if fault == 'mode':
            file_info.st_mode |= 0o200
        if fault == 'hardlink':
            file_info.st_nlink = 2
        if fault == 'fifo':
            file_info.st_mode = stat.S_IFIFO | 0o400
        if fault == 'oversize':
            file_info.st_size = 2 * 1024 * 1024 + 1
        nodes = {**dirs, 22: file_info}
        paths = {(root, None): 20, ('host_inputs', 20): 21, (FILENAME, 21): 22}
        opens, closes, stats = [], [], []
        position = 0

        def open_file(path, flags, *, dir_fd=None):
            fd = paths[path, dir_fd]
            opens.append(fd)
            assert flags & os.O_NOFOLLOW and flags & os.O_CLOEXEC
            assert flags & os.O_ACCMODE == os.O_RDONLY
            assert not flags & (os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            assert flags & (os.O_DIRECTORY if fd != 22 else os.O_NONBLOCK)
            if (fault, fd) in (('root_link', 20), ('parent_link', 21), ('file_link', 22)):
                raise OSError('PRIVATE_TEST_MARKER')
            return fd

        def fstat(fd):
            stats.append(fd)
            if fault == 'mtime' and stats == [20, 21, 22, 22]:
                return info(4, stat.S_IFREG | 0o400, len(raw), modified=9001)
            return nodes[fd]

        def path_stat(path, *, dir_fd=None, follow_symlinks=True):
            assert follow_symlinks is False
            fd = paths[path, dir_fd]
            if fault == 'replaced' and fd == 22:
                return info(9, stat.S_IFREG | 0o400, len(raw))
            if fault == 'parent_replaced' and fd == 21:
                return info(9, stat.S_IFDIR | 0o700)
            return nodes[fd]

        def read_file(fd, count):
            nonlocal position
            assert fd == 22 and 0 < count <= 65536
            source = raw[:-1] if fault == 'short' else raw + b'x' if fault == 'grown' else raw
            chunk = source[position:position + count]
            position += len(chunk)
            return chunk

        with (patch.object(os, 'geteuid', return_value=1001), patch.object(os, 'open', side_effect=open_file),
              patch.object(os, 'fstat', side_effect=fstat), patch.object(os, 'stat', side_effect=path_stat),
              patch.object(os, 'read', side_effect=read_file), patch.object(os, 'close', side_effect=closes.append),
              patch.object(os, 'write', side_effect=AssertionError('unexpected write')),
              patch.object(time, 'time', return_value=at, side_effect=times)):
            result = run(args, NoKitAccess())
        assert bool(opens) == expect_open
        if fault is None and expect_open:
            assert opens == [20, 21, 22] and closes == [22, 21, 20] and stats == [20, 21, 22, 22]
        encoded = json.dumps(result, ensure_ascii=False)
        assert len(encoded) <= 5500 and 'PRIVATE_TEST_MARKER' not in encoded
        if result['status'] == 'ready':
            assert set(result) == {'status', 'coverage', 'observed_at', 'as_of', 'valid_until', 'snapshot', 'query_id',
                                   'columns', 'common', 'lookup', 'rows', 'text_limit', 'catalogue'}
            assert result['columns'] == ['sku', 'grade', 'name', 'preferred_price', 'category_path', 'remaining_seconds']
            assert result['common'] == {'category': None, 'stock_status': 'available', 'available': True,
                                        'wait_eligible': False, 'state': 'available'}
            assert result['lookup'] == {} and result['text_limit'] == 24
            assert len(result['rows']) <= 8 and all(len(row) == 6 for row in result['rows'])
            assert len(result['rows']) == result['catalogue']['returned_count']
        return result

    def fails(args, reason, **options):
        actual = invoke(args, **options)
        assert actual == {'status': 'unavailable', 'reason': reason}, (reason, actual)

    def rendered(result):
        assert set(result) == {'status', 'reply', 'observed_at', 'valid_until'}
        assert result['status'] == 'rendered' and len(result['reply']) <= 450
        assert '상품가 기준' in result['reply'] and '수수료·가스 별도' in result['reply'] and '결제 전' in result['reply']
        assert '사과' not in result['reply'] and 'ref-' not in result['reply']
        return result['reply']

    result = invoke({'op': 'context', 'text': '식품 가격 알려주세요', 'focus_skus': [C]})
    assert [row[0] for row in result['rows']] == [A, B]
    assert result['catalogue']['hints']['focus_skus'] == [C]
    assert result['rows'][0] == [A, 'A', '신선한 빨간 사과', 101, ['식품'], 80]
    assert result['rows'][1][-1] is None
    mixed = invoke({'op': 'context', 'text': f'{A} 말고 {B} 또는 다른 상품 비교'})
    assert [row[0] for row in mixed['rows']] == [A, B, C]
    assert mixed['catalogue']['hints']['literal_skus'] == [A, B]
    assert '말고' not in json.dumps(mixed, ensure_ascii=False)
    assert '101크레딧 · 남은 시간 80초' in rendered(invoke(render_a))
    food_null = {'op': 'render', 'items': [{'sku': B, 'grade': 'B'}]}
    assert '102크레딧 · 유통기한 미제공' in rendered(invoke(food_null))
    assert '남은 시간 77초' in rendered(invoke(render_a, times=(NOW, NOW, NOW + 2.1, NOW + 2.2)))
    fails(render_a, 'selection_unavailable', times=(NOW, NOW, NOW + 79, NOW + 80))
    fails(render_a, 'stale_snapshot', times=(NOW, NOW, NOW + 119, NOW + 120))

    fallback = {'op': 'fallback', 'text': '식품 가격과 유통기한 알려주세요'}
    reply = rendered(invoke(fallback))
    assert reply.startswith('현재 조회 목록 일부\n') and '101크레딧' in reply and '102크레딧' in reply and C not in reply
    assert '101크레딧' in rendered(invoke({'op': 'fallback', 'text': f'{A} 가격 알려주세요'}))
    fails({'op': 'fallback', 'text': f'{A} GFFFFFFFF 가격 알려주세요'}, 'selection_unavailable')
    fails(fallback, 'selection_unavailable', times=(NOW, NOW, NOW + 79, NOW + 80))
    for word in ('환불', '구매', '계약', '원송금', '권리', '견적수락', '대기권', '마일리지', '개인잔액', '취소', '결제',
                 '흥정', '제외', '대안', '비교', '다른', 'pay', 'refund', 'accept quote', '대신', '진행해 주세요'):
        fails({'op': 'fallback', 'text': f'{A} 가격과 {word} 알려주세요'}, 'fallback_not_applicable')
    for text in (f'{A}', '가격 알려주세요', f'{A} 가격 주소 test@example.net', f'{A} 가격 https://example.net'):
        fails({'op': 'fallback', 'text': text}, 'fallback_not_applicable')

    filters = {'op': 'search', 'q': '  APPLE   과일  ', 'skus': [A, B, C], 'exclude_skus': [B],
               'category': '식품', 'grade': 'A', 'max_price': 103, 'min_remaining_seconds': 40,
               'sort': 'price_asc', 'limit': 1}
    changed = snapshot([offer(1, name='APPLE 사과'), offer(2, name='apple 사과'), offer(3, name='apple 사과', expires_at=NOW + 65)])
    first = invoke(filters, changed)
    assert [row[0] for row in first['rows']] == [A] and first['catalogue']['matched_count'] == 2
    cursor = first['catalogue']['next_args']
    assert cursor == {**filters, 'q': 'APPLE 과일', 'offset': 1, 'snapshot': first['snapshot'],
                      'as_of': NOW, 'query_id': first['query_id']}
    assert [row[0] for row in invoke(cursor, changed, at=NOW + 1)['rows']] == [C]
    fails(dict(cursor, max_price=104), 'query_restart_required', context=changed)
    fails(dict(cursor, as_of=NOW - 1), 'query_restart_required', context=changed)
    fails(dict(cursor, limit=2), 'query_restart_required', context=changed)
    incomplete_cursor = dict(cursor)
    del incomplete_cursor['q']
    fails(incomplete_cursor, 'query_restart_required', context=changed)
    fails(cursor, 'query_restart_required', context=changed, at=NOW + 26)
    fails(cursor, 'query_restart_required', context=changed, at=NOW + 120)
    fails(cursor, 'query_restart_required', context=dict(changed, units=list(reversed(changed['units']))))
    fails(cursor, 'query_restart_required', context=changed, times=(NOW, NOW, NOW + 26))
    expiry = invoke({'op': 'search', 'sort': 'expiry_asc'})
    assert [row[0] for row in expiry['rows']] == [C, A, B]
    assert [row[0] for row in invoke({'op': 'search', 'min_remaining_seconds': 1})['rows']] == [A, C]
    empty = invoke({'op': 'search', 'q': '../.*person@example.net', 'skus': ['GFFFFFFFF']})
    assert empty['status'] == 'ready' and empty['rows'] == [] and empty['catalogue']['matched_count'] == 0
    assert empty['catalogue']['missing_skus'] == ['GFFFFFFFF'] and 'example.net' not in str(empty)

    for size in (117, 200, 500, 1000, 5000):
        bulk = snapshot([offer(i, name='한글 상품 ' + '길' * 45, category_path=[f'공개 분류 {i % 17}', '세부 과일'])
                         for i in range(1, size + 1)])
        args = {'op': 'search', 'q': '상품 과일', 'grade': 'A', 'sort': 'price_asc', 'limit': 8}
        result = invoke(args, bulk)
        assert result['catalogue']['source_count'] == size and result['catalogue']['matched_count'] == size
        assert result['catalogue']['category_counts_partial'] and len(result['catalogue']['category_counts']) <= 12
        assert all(len(row[2]) <= 24 for row in result['rows'])
        seen = []
        pages_to_check = size if size == 117 else 4
        for _ in range(pages_to_check):
            assert result['catalogue']['offset'] == len(seen)
            seen.extend(row[0] for row in result['rows'])
            assert seen == [f'G{i:08X}' for i in range(1, len(seen) + 1)]
            following = result['catalogue']['next_args']
            if following is None:
                break
            assert following['offset'] == len(seen) and all(following[key] == value for key, value in args.items())
            assert following['snapshot'] == result['snapshot'] and following['query_id'] == result['query_id']
            result = invoke(following, bulk, at=NOW + 1)
        if size == 117:
            assert len(seen) == size and following is None

    crowded = snapshot([offer(i, category_path=[f'분류 {i:03} ' + '길' * 110], name='이름 ' + '가' * 160)
                        for i in range(1, 35)])
    crowded_result = invoke({'op': 'context', 'text': ' '.join(f'G{i:08X}' for i in range(40, 60)),
                             'focus_skus': [f'G{i:08X}' for i in range(60, 80)]}, crowded)
    assert crowded_result['status'] == 'ready' and crowded_result['catalogue']['next_args']['offset'] == crowded_result['catalogue']['returned_count']

    for price in (-1, 0, True, 10**12 + 1):
        invalid = snapshot([offer(1, price_credits=price), offer(2)])
        partial = invoke({'op': 'search'}, invalid)
        assert partial['catalogue']['excluded_counts']['invalid_rows'] == 1 and '불완전' in partial['coverage']
        assert [row[0] for row in partial['rows']] == [B]
        fails(render_a, 'selection_unavailable', context=invalid)
    duplicate = snapshot([offer(1), offer(1, state='reserved'), offer(2)])
    duplicated = invoke({'op': 'search'}, duplicate)
    assert [row[0] for row in duplicated['rows']] == [B] and duplicated['catalogue']['excluded_counts']['ambiguous_pairs'] == 1
    fails(render_a, 'selection_ambiguous', context=duplicate)
    invalid_duplicate = snapshot([offer(1), {'sku': A, 'grade': 'A'}, offer(2)])
    fails(render_a, 'selection_ambiguous', context=invalid_duplicate)
    fails({'op': 'render', 'items': [{'sku': A, 'grade': 'A'}, {'sku': B, 'grade': 'B'}]},
          'selection_unavailable', context=snapshot([offer(1), offer(2, grade='B', state='reserved')]))

    display = snapshot([offer(1, name='https://PRIVATE_TEST_MARKER.com', category_path=['PRIVATE_TEST_MARKER']),
                        offer(2, name='판매자 0x1234567890'), offer(3, name='메일 test@example.net'),
                        offer(4, name='길게 ' + '가' * 1200), offer(5, name='제어\u202e문자'),
                        offer(6, name='표시 ref-6'), offer(7, name='정상 이름', category_path='생활')])
    public = invoke({'op': 'search'}, display)
    assert public['catalogue']['display_counts']['names_omitted'] == 6
    assert public['rows'][0][2:5] == [None, 101, None] and public['rows'][-1][2:5] == ['정상 이름', 107, '생활']
    for private in ('0x1234567890', 'test@example.net', 'ref-6', 'unit_ref'):
        assert private not in str(public)
    assert '101크레딧' in rendered(invoke(render_a, display))

    raw = json.dumps(base, ensure_ascii=False).encode('utf-8')
    fails(render_a, 'invalid_snapshot', context=b'{"shop":"outseop-r4",' + raw[1:])
    fails(render_a, 'invalid_snapshot', context=raw.replace(b'"grade": "A"', b'"grade": "A", "grade": "A"'))
    for number in (b'NaN', b'Infinity', b'-Infinity', b'1e400', b'101.0'):
        fails(render_a, 'invalid_snapshot', context=raw.replace(b'101', number))
    fails(render_a, 'invalid_snapshot', context=b'\xff')
    fails(render_a, 'invalid_snapshot', context=dict(base, observed_at=True))
    fails(render_a, 'invalid_snapshot', context=dict(base, owner='PRIVATE_TEST_MARKER'))
    fails(render_a, 'invalid_snapshot', context=snapshot([None] * 5001))
    fails(render_a, 'stale_snapshot', context=dict(base, valid_until=NOW + 151))
    fails(render_a, 'stale_snapshot', at=NOW + 120)
    for changed_row in ({'unit_ref': '../bad'}, {'expires_at': True}, {'standard_fee_credits': False}, {'category_path': [1]}):
        fails(render_a, 'selection_unavailable', context=snapshot([offer(1, **changed_row)]))
    for bad in (None, True, [], {'op': 1}, {'op': 'search', 'path': FILENAME}, {'op': 'search', 'limit': True},
                {'op': 'search', 'offset': 1}, {'op': 'search', 'max_price': -1}, {'op': 'search', 'max_price': 1.0},
                {'op': 'search', 'q': 'x' * 65}, {'op': 'search', 'skus': ['../' + A]}, {'op': 'search', 'grade': ''},
                {'op': 'search', 'exclude_skus': 'bad'}, {'op': 'context', 'text': 'x' * 1501},
                {'op': 'context', 'text': '', 'focus_skus': [A] * 21}, {'op': 'fallback', 'text': '', 'focus_skus': []},
                {'op': 'render', 'items': [{'sku': A, 'grade': 'A', 'price': 1}]},
                {'op': 'render', 'items': [{'sku': 'G000000af', 'grade': 'A'}, {'sku': 'G000000AF', 'grade': 'A'}]}):
        fails(bad, 'invalid_args', expect_open=False)
    for fault in ('root_link', 'parent_link', 'file_link', 'root_mode', 'parent_mode', 'parent_owner', 'owner', 'mode',
                  'hardlink', 'fifo', 'oversize', 'mtime', 'replaced', 'parent_replaced', 'short', 'grown'):
        fails(render_a, 'source_unavailable', fault=fault)
