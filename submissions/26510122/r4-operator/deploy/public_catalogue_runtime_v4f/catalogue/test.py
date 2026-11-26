import json
import os
import stat
import time
from types import SimpleNamespace
from unittest.mock import patch

NOW = 1795596402
A, B, C = 'G0026722f', 'Gabcdefab', 'G00000003'
NAME = '[한빛 브랜드] (냉장 닭가슴살 300g/2팩)'
BRANDED = '[가상브랜드] 가상 두부 300g 2팩'
BRANDED_OTHER = '[가상] 상품 300g 2팩'
PAGE_KEYS = {'status', 'coverage', 'observed_at', 'as_of', 'valid_until', 'snapshot', 'query_id',
             'columns', 'common', 'lookup', 'rows', 'text_limit', 'catalogue'}
CATALOGUE_KEYS = {'source_count', 'eligible_count', 'matched_count', 'offset', 'returned_count', 'next_args',
                  'category_counts', 'category_counts_partial', 'criteria', 'excluded_counts', 'missing_skus',
                  'display_counts', 'name_preview_limit', 'coverage', 'search'}


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
            assert set(result) == PAGE_KEYS
            assert set(result['catalogue']) == CATALOGUE_KEYS | ({'hints'} if args['op'] == 'context' else set())
            assert result['columns'] == ['sku', 'grade', 'name', 'preferred_price', 'category_path', 'remaining_seconds']
            assert result['text_limit'] == result['catalogue']['name_preview_limit'] == 1024
            assert result['catalogue']['display_counts']['page_names_shortened'] == 0
            assert len(result['rows']) == result['catalogue']['returned_count'] <= 8
            assert all(len(row) == 6 and isinstance(row[2], str) and 0 < len(row[2]) <= result['text_limit'] for row in result['rows'])
        return result

    def fails(args, reason, **options):
        result = invoke(args, **options)
        assert result == {'status': 'unavailable', 'reason': reason}, (reason, result)

    def rendered(result, sku=None, *, at=NOW):
        assert result['status'] == 'rendered', result
        assert set(result) == {'status', 'reply', 'observed_at', 'valid_until'}
        assert result['observed_at'] == at - 5 and result['valid_until'] == at + 120
        reply = result['reply']
        assert len(reply) <= 450 and 'ref-' not in reply and '91크레딧' not in reply
        assert '시장 판매 단위는 표시된 구성 전체 1개' in reply
        assert '상품가 기준' in reply and '시장 수수료·가스 별도' in reply and '결제 전 재고·조건 재확인' in reply
        assert '지금 구매하려면' in reply and '결제권과 checkout 조건을 확인하세요.' in reply
        if sku is None:
            assert "위 SKU 중 하나를 골라 A2A로 '구매 <원하는 SKU>' 형식으로 보내" in reply
        else:
            assert f"A2A로 '구매 {sku}'를 보내" in reply
        for claim in ('자동결제', '예약확정', '서명 완료', '정산 완료'):
            assert claim not in reply
        return reply

    render_a = {'op': 'render', 'items': [pick_a]}
    render_b = {'op': 'render', 'items': [pick_b]}
    render_two = {'op': 'render', 'items': [pick_a, pick_b]}
    render_three = {'op': 'render', 'items': [pick_a, pick_b, pick_c]}
    fallback_a = {'op': 'fallback', 'text': f'{A.upper()} 상품명과 포장 수량 알려주세요'}
    fallback_b = {'op': 'fallback', 'text': f'{B.upper()} 상품명과 포장 수량 알려주세요'}
    fallback_food = {'op': 'fallback', 'text': '식품 가격과 유통기한 알려주세요'}
    assert f'{A} A등급 · {NAME} · 1,201크레딧 · 남은 시간 300초' in rendered(invoke(render_a), A)
    assert '남은 시간 297초' in rendered(invoke(render_a, times=(NOW, NOW, NOW + 2.1, NOW + 2.2)), A)
    assert '유통기한 미제공' in rendered(invoke(render_b), B)
    assert NAME in rendered(invoke(fallback_a), A)
    for args in (render_two, fallback_food):
        reply = rendered(invoke(args))
        assert f'{A} A등급 · {NAME}' in reply and f'{B} B등급 · {NAME.replace("2팩", "3팩")}' in reply
    triple = rendered(invoke(render_three))
    assert all(sku in triple for sku in (A, B, C))

    branded = snapshot([offer(1, sku=A, name=BRANDED), offer(2, sku=B, grade='B', name=BRANDED_OTHER)])
    for sku, grade, price, name, render_args, fallback_args in (
            (A, 'A', '1,201', BRANDED, render_a, fallback_a), (B, 'B', '1,202', BRANDED_OTHER, render_b, fallback_b)):
        for args in (render_args, fallback_args):
            assert f'{sku} {grade}등급 · {name} · {price}크레딧 · 남은 시간 300초' in rendered(invoke(args, branded), sku)
        result = invoke({'op': 'search', 'q': name}, branded)
        assert [(row[0], row[2]) for row in result['rows']] == [(sku, name)]
    bracket_page = invoke({'op': 'context', 'text': '식품 포장 규격 알려주세요'}, branded)
    assert [(row[0], row[2]) for row in bracket_page['rows']] == [(A, BRANDED), (B, BRANDED_OTHER)]

    for word in ('환불', '계약', '구매', '결제', '송금', '잔액', '대안', '비교', '제외', '또는', 'pay', 'accept quote'):
        fails({'op': 'fallback', 'text': f'{A} 가격과 {word} 알려주세요'}, 'fallback_not_applicable')
    fails({'op': 'fallback', 'text': f'구매 {B}'}, 'fallback_not_applicable')
    fails({'op': 'fallback', 'text': '상품명 알려주세요'}, 'fallback_not_applicable')
    fails({'op': 'fallback', 'text': f'{A} GFFFFFFFF 가격 알려주세요'}, 'selection_unavailable')
    four = snapshot([offer(i) for i in range(1, 5)])
    many_skus = ' '.join(unit['sku'] for unit in four['units'])
    fails({'op': 'fallback', 'text': many_skus + ' 가격 알려주세요'}, 'selection_limit', context=four)
    assert rendered(invoke(fallback_food, four)).startswith('현재 조회 목록 일부\n')

    exact120 = '가' * (120 - len(NAME) - 1) + ' ' + NAME
    sized = snapshot([offer(1, sku=A, name=exact120)])
    assert len(exact120) == 120 and exact120 in rendered(invoke(render_a, sized), A)
    slack = 450 - len(rendered(invoke(render_a), A))
    exact = '가' * slack + NAME
    exact_snapshot = snapshot([offer(1, sku=A, name=exact)])
    for args in (render_a, fallback_a):
        assert len(rendered(invoke(args, exact_snapshot), A)) == 450
        fails(args, 'output_budget', context=snapshot([offer(1, sku=A, name='가' + exact)]))
    long_three = snapshot([offer(1, sku=A, name=exact120), offer(2, sku=B, grade='B', name=exact120), offer(3, name=exact120)])
    fails(render_three, 'output_budget', context=long_three)
    fails(fallback_food, 'output_budget', context=long_three)
    for name in ('https://PRIVATE_TEST_MARKER.com', '메일 test@example.net', '0x1234567890', '표시 ref-1',
                 '제어\u202e문자', '파일 config.json', '경로 foo/bar', 'ghp_abcdef', '', '가' * 1025,
                 '[https://example.net] 상품', '[서울 테헤란로 123] 상품', '[123 Main Street] 상품',
                 '[010-1234-5678] 상품', '[api_key] 상품', '[ghp_abcdef] 상품', '[Bearer abc] 상품',
                 '[0x1234567890] 상품', '[결제권] 상품', '[정산권리] 상품', '[제어\u202e문자] 상품',
                 '[ref-1] 상품', '[브랜드](300g/2팩)', '[미완성 상품'):
        unsafe = snapshot([offer(1, sku=A, name=name), base['units'][1]])
        for args in (render_a, fallback_a, render_two):
            fails(args, 'name_unavailable', context=unsafe)
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
    for args in (render_a, fallback_a):
        fails(args, 'selection_unavailable', context=short_expiry, times=(NOW, NOW, NOW + 8, NOW + 9))
    fails(render_a, 'stale_snapshot', times=(NOW, NOW, NOW + 119, NOW + 120))
    fails(render_a, 'stale_snapshot', context=dict(base, valid_until=NOW + 151))
    fails(render_a, 'stale_snapshot', at=NOW + 120)
    assert [row[0] for row in invoke({'op': 'search', 'min_remaining_seconds': 1})['rows']] == [A, C]

    pack_prefix = '[한빛] 공개 상품 ' + '가' * 140
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
              '서울 테헤란로 123', '123 Main Street', 'dir／file', '[.env]', '[010-1234-5678]', '[결제권]', '[ghp_abcdef]'):
        fails({'op': 'search', 'q': q}, 'unsafe_query_cursor', expect_open=False)
        fails(dict(cursor, q=q), 'unsafe_query_cursor', context=packs, expect_open=False)
    for q in ('ref-1', '[ref-1]'):
        fails({'op': 'search', 'q': q}, 'unsafe_query_cursor')

    name_words = '가나다라마바사아자 ' * 95
    category_words = ('냉장 식품 ' * 18).strip()
    bulk = snapshot([offer(i, name=f'[한빛] {name_words}({300 + i}g/2팩)',
                          category_path=[f'분류 {i:03} {category_words}']) for i in range(1, 118)])
    bulk_raw = json.dumps(bulk, ensure_ascii=False).encode('utf-8')
    expected = [(unit['sku'], unit['name']) for unit in bulk['units']]
    for initial_args in ({'op': 'context', 'text': '상품 목록'}, {'op': 'search', 'q': '[한빛] 2팩'}):
        args = initial_args
        seen = []
        for _ in range(117):
            result = invoke(args, bulk_raw)
            assert result['status'] == 'ready', result
            assert result['catalogue']['offset'] == len(seen)
            assert result['catalogue']['matched_count'] == 117
            assert 0 < len(result['rows']) < 8
            seen.extend((row[0], row[2]) for row in result['rows'])
            args = result['catalogue']['next_args']
            if args is None:
                break
            assert args['offset'] == len(seen) and args['as_of'] == NOW and args['query_id'] == result['query_id']
            assert args['q'] == initial_args.get('q', '') and args['snapshot'] == result['snapshot']
        assert args is None and len(seen) == 117 and seen == expected
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

    # Fresh synthetic observations, separate from the fixed historical regression clock.
    fresh_at = int(time.time())

    def fresh(units):
        return dict(snapshot(units), observed_at=fresh_at - 5, valid_until=fresh_at + 120)

    tuna = '[동원xGS] 라이트스탠다드 참치 85g x12캔 /라이트/고추/콘참치'
    brand_tuna = '[브랜드/공식] 가상 참치 85g x12캔 /라이트/고추/콘참치'
    rice = '[26년산 햅쌀] 쌀명당 완전미 평택 고시히카리 5kg / 특등급'
    tofu = '가상 두부 300g/2팩'
    products = [offer(i, sku=sku, name=name, grade='B', price_credits=price, expires_at=fresh_at + 300)
                for i, (sku, name, price) in enumerate((('G9e816d8b', tuna, 25704), (A, brand_tuna, 17201),
                                                        (B, rice, 19870), (C, tofu, 5200)), 1)]
    source = fresh(products)
    for unit, q in zip(products, ('라이트스탠다드 콘참치', '공식 고추', '특등급', '2팩')):
        sku, name, price = unit['sku'], unit['name'], unit['price_credits']
        text = f'{sku.upper()} 상품명과 포장 수량 알려주세요'
        render_one = {'op': 'render', 'items': [{'sku': sku.upper(), 'grade': 'B'}]}
        fallback_one = {'op': 'fallback', 'text': text}
        exact_row = [sku, 'B', name, price, ['식품'], 300]
        for args in ({'op': 'context', 'text': text}, {'op': 'search', 'skus': [sku.upper()], 'q': q}):
            found = invoke(args, source, at=fresh_at)
            assert found['rows'] == [exact_row] and found['catalogue']['criteria']['skus'] == [sku]
        for args in (render_one, fallback_one):
            reply = rendered(invoke(args, source, at=fresh_at), sku, at=fresh_at)
            assert reply.splitlines()[0] == f'{sku} B등급 · {name} · {price:,}크레딧 · 남은 시간 300초'

    target = products[1]
    target_render = {'op': 'render', 'items': [{'sku': A, 'grade': 'B'}]}
    target_context = {'op': 'context', 'text': f'{A} 상품명과 포장 수량 알려주세요'}
    reply = rendered(invoke(target_render, source, at=fresh_at), A, at=fresh_at)
    exact_brand = brand_tuna.replace('가상', '가상' + '가' * (450 - len(reply)), 1)
    for args in (target_render, dict(target_context, op='fallback')):
        exact_source = fresh([dict(target, name=exact_brand)])
        exact_reply = rendered(invoke(args, exact_source, at=fresh_at), A, at=fresh_at)
        assert exact_brand in exact_reply and len(exact_reply) == 450
        over_source = fresh([dict(target, name=exact_brand.replace('가상', '가상가', 1))])
        fails(args, 'output_budget', context=over_source, at=fresh_at)

    for name in (
            brand_tuna + ' /https://example.net', brand_tuna + ' /evil.com/상품',
            brand_tuna + ' /10.0.0.1/상품', brand_tuna + ' /test@example.net',
            brand_tuna + ' /010-1234-5678', brand_tuna + ' /0xabcdef1234567890',
            brand_tuna + ' /api_key', brand_tuna + ' /Bearer abc', brand_tuna + ' /owner 기록',
            brand_tuna + ' /.env', brand_tuna + ' /config.json', brand_tuna + ' /ref-2',
            brand_tuna + ' /home/demo/.ssh/id_ed25519', brand_tuna + ' C:/Users/demo/notes',
            brand_tuna + ' /상위/../하위', brand_tuna + ' //상위/하위',
            brand_tuna + ' /설명\u202e', brand_tuna + ' /<img src=x>',
            '[브랜드/공식](https://example.net) 참치 85g /고추', brand_tuna + ' /{"x":"y"}',
            '[브랜드/ref-2] 참치 85g /고추', '[foo/bar] 상품 85g /고추', '/자료/목록 상품 85g /고추'):
        unsafe = fresh([dict(target, name=name)])
        for args in (target_render, dict(target_context, op='fallback')):
            fails(args, 'name_unavailable', context=unsafe, at=fresh_at)
        for args in (target_context, {'op': 'search', 'skus': [A]}):
            found = invoke(args, unsafe, at=fresh_at)
            assert found['rows'] == [] and found['catalogue']['missing_skus'] == [A]
    for q in ('/home/demo/.ssh/id_ed25519', 'C:/Users/demo', '[브랜드/공식]', '라이트/고추'):
        fails({'op': 'search', 'q': q}, 'unsafe_query_cursor', context=source, at=fresh_at, expect_open=False)

    page_args = {'op': 'search'}
    page_units = [offer(i, name=brand_tuna, category_path=[], expires_at=fresh_at + 300) for i in range(1, 7)]
    initial = invoke(page_args, fresh(page_units), at=fresh_at)
    assert len(initial['rows']) == len(page_units) and initial['catalogue']['next_args'] is None
    padding, remainder = divmod(5500 - len(json.dumps(initial, ensure_ascii=False)), len(page_units))
    for index, unit in enumerate(page_units):
        unit['name'] = brand_tuna.replace('가상', '가상' + '가' * (padding + (index < remainder)), 1)
        assert len(unit['name']) <= 1024
    exact_page = invoke(page_args, fresh(page_units), at=fresh_at)
    assert len(json.dumps(exact_page, ensure_ascii=False)) == 5500
    assert [row[2] for row in exact_page['rows']] == [unit['name'] for unit in page_units]
    page_units[-1]['name'] = page_units[-1]['name'].replace('가상', '가상가', 1)
    over = fresh(page_units)
    first_page = invoke(page_args, over, at=fresh_at)
    assert len(first_page['rows']) < len(page_units)
    second_page = invoke(first_page['catalogue']['next_args'], over, at=fresh_at)
    assert second_page['catalogue']['next_args'] is None
    assert [(row[0], row[2]) for row in first_page['rows'] + second_page['rows']] == [
        (unit['sku'], unit['name']) for unit in page_units]
