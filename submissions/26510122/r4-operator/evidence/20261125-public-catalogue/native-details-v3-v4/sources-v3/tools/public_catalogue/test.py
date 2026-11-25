import json
import os
import stat
import time
from types import SimpleNamespace
from unittest.mock import patch

NOW = 1795596402
A, B, C = 'G0026722f', 'Gabcdefab', 'G00000003'
NAME = '한빛 브랜드 (냉장 닭가슴살 300g/2팩)'


class NoKitAccess:
    def __getattribute__(self, name):
        raise AssertionError('unexpected kit access')


def offer(number, **changes):
    values = {'unit_ref': f'ref-{number}', 'sku': f'G{number:08X}', 'name': NAME,
              'category_path': ['식품', '냉장'], 'state': 'available', 'grade': 'A',
              'price_credits': number + 1200, 'standard_fee_credits': 91, 'expires_at': NOW + 300}
    return dict(values, **changes)


def snapshot(units):
    return {'schema': 'outseop-r4.customer-offers.v1', 'shop': 'outseop-r4',
            'observed_at': NOW - 5, 'valid_until': NOW + 120, 'units': units}


def info(inode, mode, size=0):
    return SimpleNamespace(st_dev=1, st_ino=inode, st_mode=mode, st_uid=1001, st_gid=1001,
                           st_nlink=1, st_size=size, st_mtime_ns=9000, st_ctime_ns=9000)


def test(run, kit):
    base = snapshot([offer(1, sku=A), offer(2, sku=B, grade='B', name=NAME.replace('2팩', '3팩'), expires_at=None),
                     offer(3, name='유리컵', category_path='생활', expires_at=NOW + 30)])
    pick_a = {'sku': A.upper(), 'grade': 'A'}
    pick_b = {'sku': B.upper(), 'grade': 'B'}
    pick_c = {'sku': C, 'grade': 'A'}

    def invoke(args, context=base, at=NOW, times=None, fault=None, expect_open=True):
        raw = context if type(context) is bytes else json.dumps(context, ensure_ascii=False).encode('utf-8')
        root = os.getcwd()
        nodes = {20: info(2, stat.S_IFDIR | 0o700), 21: info(3, stat.S_IFDIR | 0o700),
                 22: info(4, stat.S_IFREG | 0o400, len(raw))}
        if fault == 'oversize':
            nodes[22].st_size = 2 * 1024 * 1024 + 1
        if fault == 'hardlink':
            nodes[22].st_nlink = 2
        paths = {(root, None): 20, ('host_inputs', 20): 21, ('customer_offer_context.json', 21): 22}
        opens, closes = [], []
        position = 0

        def open_file(path, flags, *, dir_fd=None):
            fd = paths[path, dir_fd]
            opens.append(fd)
            assert flags & os.O_NOFOLLOW and flags & os.O_CLOEXEC
            assert flags & os.O_ACCMODE == os.O_RDONLY
            assert not flags & (os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            assert flags & (os.O_DIRECTORY if fd != 22 else os.O_NONBLOCK)
            if fault == 'symlink' and fd == 22:
                raise OSError('PRIVATE_TEST_MARKER')
            return fd

        def path_stat(path, *, dir_fd=None, follow_symlinks=True):
            assert follow_symlinks is False
            fd = paths[path, dir_fd]
            if fault == 'replaced' and fd == 22:
                return info(9, stat.S_IFREG | 0o400, len(raw))
            return nodes[fd]

        def read_file(fd, count):
            nonlocal position
            assert fd == 22 and 0 < count <= 65536
            chunk = raw[position:position + count]
            position += len(chunk)
            return chunk

        with (patch.object(os, 'geteuid', return_value=1001), patch.object(os, 'open', side_effect=open_file),
              patch.object(os, 'fstat', side_effect=nodes.__getitem__), patch.object(os, 'stat', side_effect=path_stat),
              patch.object(os, 'read', side_effect=read_file), patch.object(os, 'close', side_effect=closes.append),
              patch.object(os, 'write', side_effect=AssertionError('unexpected write')),
              patch.object(time, 'time', return_value=at, side_effect=times)):
            result = run(args, NoKitAccess())
        assert bool(opens) == expect_open
        if fault is None and expect_open:
            assert opens == [20, 21, 22] and closes == [22, 21, 20]
        encoded = json.dumps(result, ensure_ascii=False)
        assert len(encoded) <= 5500 and 'PRIVATE_TEST_MARKER' not in encoded
        if result['status'] == 'ready':
            assert result['columns'] == ['sku', 'grade', 'name', 'preferred_price', 'category_path', 'remaining_seconds']
            assert result['text_limit'] == result['catalogue']['name_preview_limit'] == 1024
            assert result['catalogue']['display_counts']['page_names_shortened'] == 0
            assert len(result['rows']) == result['catalogue']['returned_count'] <= 8
            assert all(len(row) == 6 and isinstance(row[2], str) and 0 < len(row[2]) <= result['text_limit'] for row in result['rows'])
        return result

    def fails(args, reason, **options):
        result = invoke(args, **options)
        assert result == {'status': 'unavailable', 'reason': reason}, (reason, result)

    def rendered(result):
        assert result['status'] == 'rendered', result
        assert set(result) == {'status', 'reply', 'observed_at', 'valid_until'}
        assert result['observed_at'] == NOW - 5 and result['valid_until'] == NOW + 120
        reply = result['reply']
        assert len(reply) <= 450 and 'ref-' not in reply and '91크레딧' not in reply
        assert '판매 단위는 표시된 구성 전체 1개(1份)' in reply
        assert '상품가 기준' in reply and '시장 수수료·가스 별도' in reply and '결제 전 재고·조건 재확인' in reply
        assert '지금 구매' in reply and 'SKU와 등급을 A2A로 보내 결제권과 checkout 조건을 확인' in reply
        return reply

    render_a = {'op': 'render', 'items': [pick_a]}
    render_b = {'op': 'render', 'items': [pick_b]}
    render_two = {'op': 'render', 'items': [pick_a, pick_b]}
    render_three = {'op': 'render', 'items': [pick_a, pick_b, pick_c]}
    fallback_a = {'op': 'fallback', 'text': f'{A.upper()} 상품명과 포장 수량 알려주세요'}
    fallback_food = {'op': 'fallback', 'text': '식품 가격과 유통기한 알려주세요'}
    assert f'{A} A등급 · {NAME} · 1,201크레딧 · 남은 시간 300초' in rendered(invoke(render_a))
    assert '남은 시간 297초' in rendered(invoke(render_a, times=(NOW, NOW, NOW + 2.1, NOW + 2.2)))
    assert '유통기한 미제공' in rendered(invoke(render_b))
    assert NAME in rendered(invoke(fallback_a))
    for args in (render_two, fallback_food):
        reply = rendered(invoke(args))
        assert f'{A} A등급 · {NAME}' in reply and f'{B} B등급 · {NAME.replace("2팩", "3팩")}' in reply
    for pick in (pick_a, pick_b, pick_c):
        assert pick['sku'].upper() in rendered(invoke(render_three)).upper()
    for word in ('환불', '계약', '구매', '결제', '송금', '잔액', '대안', '비교', '제외', '또는', 'pay', 'accept quote'):
        fails({'op': 'fallback', 'text': f'{A} 가격과 {word} 알려주세요'}, 'fallback_not_applicable')
    fails({'op': 'fallback', 'text': '상품명 알려주세요'}, 'fallback_not_applicable')
    fails({'op': 'fallback', 'text': f'{A} GFFFFFFFF 가격 알려주세요'}, 'selection_unavailable')
    four = snapshot([offer(i) for i in range(1, 5)])
    many_skus = ' '.join(unit['sku'] for unit in four['units'])
    fails({'op': 'fallback', 'text': many_skus + ' 가격 알려주세요'}, 'selection_limit', context=four)
    assert rendered(invoke(fallback_food, four)).startswith('현재 조회 목록 일부\n')

    exact120 = '가' * (120 - len(NAME) - 1) + ' ' + NAME
    sized = snapshot([offer(1, sku=A, name=exact120)])
    assert len(exact120) == 120 and exact120 in rendered(invoke(render_a, sized))
    initial = rendered(invoke(render_a))
    slack = 450 - len(initial)
    exact = '가' * slack + NAME
    exact_snapshot = snapshot([offer(1, sku=A, name=exact)])
    assert len(rendered(invoke(render_a, exact_snapshot))) == 450
    over = snapshot([offer(1, sku=A, name='가' + exact)])
    fails(render_a, 'output_budget', context=over)
    fails(fallback_a, 'output_budget', context=over)
    long_three = snapshot([offer(1, sku=A, name=exact120), offer(2, sku=B, grade='B', name=exact120), offer(3, name=exact120)])
    fails(render_three, 'output_budget', context=long_three)
    for name in ('https://PRIVATE_TEST_MARKER.com', '메일 test@example.net', '0x1234567890', '표시 ref-1',
                 '제어\u202e문자', '파일 config.json', '경로 foo/bar', 'ghp_abcdef', '', '가' * 1025):
        unsafe = snapshot([offer(1, sku=A, name=name), base['units'][1]])
        fails(render_a, 'name_unavailable', context=unsafe)
        fails(fallback_a, 'name_unavailable', context=unsafe)
        fails(render_two, 'name_unavailable', context=unsafe)
        page = invoke({'op': 'search', 'skus': [A.upper()]}, unsafe)
        assert page['rows'] == [] and page['catalogue']['missing_skus'] == [A]
        assert page['catalogue']['excluded_counts']['name_unavailable_rows'] == 1 and '불완전' in page['coverage']
        assert [row[0] for row in invoke({'op': 'context', 'text': '식품 재고'}, unsafe)['rows']] == [B]

    duplicate = snapshot([base['units'][0], offer(2, sku=A.upper(), state='reserved'), offer(3, sku=A, grade='B')])
    fails(render_a, 'selection_ambiguous', context=duplicate)
    fails(fallback_a, 'selection_unavailable', context=duplicate)
    assert invoke({'op': 'search'}, duplicate)['catalogue']['excluded_counts']['ambiguous_pairs'] == 1
    fails({'op': 'render', 'items': [pick_a, {'sku': A, 'grade': 'A'}]}, 'invalid_args', expect_open=False)
    fails(render_a, 'selection_unavailable', context=snapshot([offer(1, sku=A, state='reserved')]))
    fails(render_a, 'selection_unavailable', context=snapshot([offer(1, sku=A, price_credits=True)]))
    short_expiry = snapshot([offer(1, sku=A, expires_at=NOW + 9)])
    fails(render_a, 'selection_unavailable', context=short_expiry, times=(NOW, NOW, NOW + 8, NOW + 9))
    fails(fallback_a, 'selection_unavailable', context=short_expiry, times=(NOW, NOW, NOW + 8, NOW + 9))
    fails(render_a, 'stale_snapshot', times=(NOW, NOW, NOW + 119, NOW + 120))
    fails(render_a, 'stale_snapshot', context=dict(base, valid_until=NOW + 151))
    fails(render_a, 'stale_snapshot', at=NOW + 120)
    assert [row[0] for row in invoke({'op': 'search', 'min_remaining_seconds': 1})['rows']] == [A, C]

    pack_prefix = '공개 한빛 상품 ' + '가' * 140
    packs = snapshot([offer(1, sku=A, name=pack_prefix + ' (300g/2팩)'),
                      offer(2, sku=B, name=pack_prefix + ' (300g/3팩)')])
    context = invoke({'op': 'context', 'text': '식품 포장 규격 알려주세요'}, packs)
    assert [row[2] for row in context['rows']] == [unit['name'] for unit in packs['units']]
    assert [row[0] for row in invoke({'op': 'search', 'q': '3팩'}, packs)['rows']] == [B]
    focused = invoke({'op': 'context', 'text': f'{A.upper()} 재고', 'focus_skus': [A.upper()]}, packs)
    assert focused['catalogue']['criteria']['skus'] == [A] and focused['catalogue']['hints']['focus_skus'] == [A]
    filtered = {'op': 'search', 'q': '  한빛   냉장  ', 'skus': [C, B.upper(), A.upper()], 'exclude_skus': [C],
                'category': '식품', 'grade': 'A', 'max_price': 1202, 'min_remaining_seconds': 40, 'sort': 'price_asc', 'limit': 1}
    first = invoke(filtered, packs)
    cursor = first['catalogue']['next_args']
    assert first['rows'][0][0] == A and cursor == dict(filtered, q='한빛 냉장', skus=[C, A, B], offset=1,
                                                      snapshot=first['snapshot'], as_of=NOW, query_id=first['query_id'])
    assert invoke(cursor, packs, at=NOW + 1)['rows'][0][0] == B
    for change in ({'limit': 2}, {'max_price': 1203}, {'exclude_skus': []}, {'as_of': NOW - 1}):
        fails(dict(cursor, **change), 'query_restart_required', context=packs)
    fails(cursor, 'query_restart_required', context=snapshot(list(reversed(packs['units']))))
    fails(cursor, 'query_restart_required', context=packs, at=NOW + 120)
    for key in ('q', 'skus', 'exclude_skus', 'category', 'grade', 'max_price', 'min_remaining_seconds', 'sort', 'offset', 'limit'):
        fails({k: v for k, v in cursor.items() if k != key}, 'query_restart_required', context=packs, expect_open=False)
    for q in ('test@example.net', 'https://example.net', './local', '.env', 'config.json', 'Bearer abc', 'ghp_abcdef',
              '서울 테헤란로 123', '123 Main Street', 'dir／file'):
        fails({'op': 'search', 'q': q}, 'unsafe_query_cursor', expect_open=False)
        fails(dict(cursor, q=q), 'unsafe_query_cursor', context=packs, expect_open=False)
    fails({'op': 'search', 'q': 'ref-1'}, 'unsafe_query_cursor')

    bulk = snapshot([offer(i, name='한빛 ' + '가' * 950 + f' ({300 + i}g/2팩)',
                          category_path=[f'분류 {i:03} ' + '길' * 110]) for i in range(1, 19)])
    args = {'op': 'context', 'text': '상품 목록'}
    seen = []
    for _ in range(len(bulk['units'])):
        result = invoke(args, bulk)
        assert result['status'] == 'ready', result
        assert result['catalogue']['offset'] == len(seen)
        assert 0 < len(result['rows']) < 8
        seen.extend((row[0], row[2]) for row in result['rows'])
        args = result['catalogue']['next_args']
        if args is None:
            break
        assert args['offset'] == len(seen) and args['as_of'] == NOW and args['query_id'] == result['query_id']
    assert args is None and seen == [(unit['sku'], unit['name']) for unit in bulk['units']]
    maximum_rows = snapshot([offer(i, name='한빛 사과') for i in range(1, 5001)])
    listing = invoke({'op': 'search', 'limit': 8}, maximum_rows)
    assert listing['catalogue']['source_count'] == 5000 and len(listing['rows']) == 8
    fails(render_a, 'invalid_snapshot', context=snapshot([None] * 5001))
    for fault in ('oversize', 'hardlink', 'symlink', 'replaced'):
        fails(render_a, 'source_unavailable', fault=fault)
    raw = json.dumps(base, ensure_ascii=False).encode('utf-8')
    fails(render_a, 'invalid_snapshot', context=b'{"shop":"outseop-r4",' + raw[1:])
    for value in (b'NaN', b'1201.0'):
        fails(render_a, 'invalid_snapshot', context=raw.replace(b'"price_credits": 1201', b'"price_credits": ' + value))
