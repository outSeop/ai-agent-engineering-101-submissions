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
            assert set(result['catalogue']) == CATALOGUE_KEYS | ({'hints'} if args['op'] in ('context', 'prepare') else set())
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

    five = offer(11, sku=A, name=rice, category_path=['곡물'], grade='B', price_credits=19870)
    ten = offer(12, sku=B, name='쌀 10kg', category_path=['곡물'], grade='B', price_credits=31000)
    almond = offer(13, name='아몬드 200g', category_path=['식품', '견과류'], grade='C')
    mix = offer(14, name='아몬드 호두 혼합 견과 200g', category_path=['식품', '견과류'])
    nutless = offer(15, name='유리병', category_path=['생활'])
    tofu_unit = offer(16, sku=C, name=tofu, category_path=['식품', '두부'])
    offers = snapshot([ten, mix, nutless, five, almond, tofu_unit])
    missing = 'GFFFFFFFF'

    def prepared(text, skus, kinds, *, context=offers, missing_sku=False, unverified=None, **args):
        result = invoke(dict(op='prepare', text=text, **args), context)
        assert result['status'] == 'ready', result
        assert len(json.dumps(result, ensure_ascii=False)) < 5500
        assert result['catalogue']['next_args'] is None
        rows = result['rows']
        assert [row[0] for row in rows] == skus, result
        evidence = result['catalogue']['hints']['preparation']
        assert set(evidence) == {'fits', 'requested_sku_missing', 'constraints_unverified'}
        assert evidence['requested_sku_missing'] is missing_sku
        assert type(evidence['constraints_unverified']) is bool
        if unverified is not None:
            assert evidence['constraints_unverified'] is unverified, result
        assert evidence['fits'] == [{'sku': row[0], 'grade': row[1], 'kind': kind} for row, kind in zip(rows, kinds)], (text, evidence['fits'], kinds)
        return rows

    assert prepared('백미 5kg 가격 알려주세요', [A], ['category_alternative'], unverified=False) == [
        [A, 'B', rice, 19870, ['곡물'], 300]]
    prepared('백미 10kg 재고 알려주세요', [B], ['category_alternative'])
    prepared('쌀 10kg 가격 알려주세요', [B], ['named_pack'])
    prepared('쌀 7kg 가격 알려주세요', [], [])
    prepared('쌀 10kg 말고 5kg 추천', [A], ['category_alternative'])
    prepared('쌀 5kg 가격 알려주세요', [A], ['category_alternative'])
    prepared('쌀 5kg 가격 알려주세요', [A], ['named_pack'],
             context=snapshot([dict(five, name='햅쌀 쌀 5kg')]))
    prepared('쌀 제외 곡물 재고', [], [])
    prepared('백미 5kg B등급 20,000크레딧 이하 남은 시간 4분 이상', [A], ['category_alternative'])
    prepared('백미 5kg A등급', [], [])
    prepared('백미 5kg 19,870크레딧 미만', [], [])
    prepared('백미 5kg 남은 시간 6분 이상', [], [])
    prepared('견과 상품 목록', [almond['sku'], mix['sku']], ['related_literal', 'category_alternative'],
             context=snapshot([dict(almond, name='아몬드 견과 200g'), dict(mix, name='아몬드 호두 혼합 200g', category_path=['식품'])]))
    prepared('아몬드 재고', [almond['sku'], mix['sku']], ['related_literal', 'related_literal'])
    prepared('호두 제외 아몬드 재고', [almond['sku']], ['related_literal'])
    prepared('마카다미아 재고', [], [])
    prepared('육류 재고', [], [])
    prepared(f'{missing} 재고', [], [], missing_sku=True)
    prepared(f'{missing} 곡물 5kg 재고', [A], ['category_alternative'], missing_sku=True)
    prepared(f'{missing} 곡물 5kg 대체품은 필요 없어요', [], [], missing_sku=True)
    prepared(f'{A.upper()} 가격', [A], ['exact_sku'], unverified=False)
    prepared('가격 알려주세요', [B], ['exact_sku'], focus_skus=[B.upper()])
    prepared('가격 알려주세요', [], [])
    prepared(f'{A} 사진이나 원재료 알려주세요', [A], ['exact_sku'], unverified=True)
    prepared('아몬드 알레르기 배송 원산지 확인', [almond['sku'], mix['sku']], ['related_literal', 'related_literal'], unverified=True)
    prepared('초가상어 정보', [], [], unverified=True)
    prepared(f'{A} 초가상어 가격', [A], ['exact_sku'], unverified=True)
    prepared(f'{A} 가격 test@example.net', [], [], unverified=True)
    prepared('사과 가격', [f'G{number:08X}' for number in range(1, 9)], ['related_literal'] * 8,
             context=maximum_rows)
    prepared('참치 재고', [], [], context=snapshot([offer(1, name='참치', state='reserved')]))
    assert invoke(dict(fallback_a, op='prepared_fallback')) == invoke(render_a)
    assert invoke({'op': 'prepared_fallback', 'text': '두부 가격 알려주세요'}, offers) == invoke(
        {'op': 'render', 'items': [pick_c]}, offers)
    for text in ('백미 가격 알려주세요', '백미 5kg 가격 알려주세요', '곡물 가격 알려주세요',
                 f'{missing} 곡물 가격 알려주세요', f'{A} 구매하고 가격 알려주세요',
                 f'{A} 예약 가능한가요', f'{A} 가격과 성분 알려주세요', f'{A} 재고와 사진 알려주세요',
                 f'{A} 가격을 20000크레딧 이하로', f'{A} 가격과 배송 알려주세요',
                 f'{A} 초가상어 가격 알려주세요', f'{A} 또는 {B} 가격', '재고 알려주세요'):
        fails({'op': 'prepared_fallback', 'text': text}, 'fallback_not_applicable', context=offers)
    fails({'op': 'prepared_fallback', 'text': '쌀 가격 알려주세요'}, 'fallback_not_applicable', context=snapshot([five]))
    fails(dict(fallback_a, op='prepared_fallback'), 'fallback_not_applicable', context=duplicate)
    for args in ({'op': 'prepare'}, {'op': 'prepare', 'text': '', 'wallet': {}},
                 {'op': 'prepare', 'text': '', 'focus_skus': ['invalid']},
                 {'op': 'prepared_fallback', 'text': '', 'focus_skus': [A]}):
        fails(args, 'invalid_args', expect_open=False)

    question = '지금 실제로 파는 쌀과 견과류가 있나요? 있으면 상품명, 등급, 가격과 소비기한을 보여 주세요.'
    busy_rice = [offer(i, name='쌀 5kg', category_path=['곡물'], grade='B') for i in range(20, 32)]
    literal_nut = offer(32, name='견과류 200g', category_path=['식품', '견과류'], grade='B')
    alias_nut = dict(almond, category_path=['식품'])
    crowded = snapshot([*busy_rice, five, literal_nut, alias_nut, nutless])
    expected = [busy_rice[0]['sku'], literal_nut['sku'], busy_rice[1]['sku'], alias_nut['sku'],
                *(unit['sku'] for unit in busy_rice[2:6])]
    kinds = ['related_literal', 'related_literal', 'related_literal', 'category_alternative', *(['related_literal'] * 4)]
    rows = prepared(question, expected, kinds, context=crowded, unverified=False)
    originals = {unit['sku']: [unit['sku'], unit['grade'], unit['name'], unit['price_credits'],
                              unit['category_path'][:1], unit['expires_at'] - NOW] for unit in crowded['units']}
    assert all(row == originals[row[0]] for row in rows)
    page = invoke({'op': 'prepare', 'text': question}, crowded)
    assert page['catalogue']['matched_count'] == 15 and len(rows) == 8
    for variant in ('현재 판매 중인 쌀이랑 견과류를 보여 주세요.',
                    '쌀, 견과류는 있는지 상품명을 알려주세요.',
                    '쌀 및 견과류도 상품명과 가격을 확인해주세요.',
                    '쌀 또는 견과류가 있으면 소비기한을 알려주세요.'):
        prepared(variant, expected, kinds, context=crowded, unverified=False)
    partial = '견과류와 캠핑등 가격 알려주세요'
    prepared(partial, [literal_nut['sku'], alias_nut['sku']], ['related_literal', 'category_alternative'],
             context=crowded, unverified=True)
    lamp = offer(33, name='캠핑등 1개', category_path=['생활'])
    prepared(partial, [literal_nut['sku'], alias_nut['sku']], ['related_literal', 'category_alternative'],
             context=snapshot([literal_nut, alias_nut, lamp]), unverified=True)
    prepared('견과류와 참치 가격 알려주세요', [literal_nut['sku'], alias_nut['sku']],
             ['related_literal', 'category_alternative'], context=crowded, unverified=True)
    prepared('견과류 알레르기, 원산지와 배송 안내', [literal_nut['sku'], alias_nut['sku']],
             ['related_literal', 'category_alternative'], context=crowded, unverified=True)
    prepared(f'{A.upper()} 쌀과 견과류 가격 알려주세요', [A, literal_nut['sku'], alias_nut['sku']],
             ['exact_sku', 'related_literal', 'category_alternative'], context=crowded, unverified=False)
    prepared(f'{A} 아몬드 가격 알려주세요', [], [], context=crowded)
    prepared('쌀과 견과류 제외 두부 가격', [C], ['related_literal'], context=snapshot([five, literal_nut, tofu_unit]))
    prepared('견과류 말고 쌀이랑 두부 재고', [A, C], ['category_alternative', 'related_literal'],
             context=snapshot([five, literal_nut, tofu_unit]))
    prepared(f'{missing} 쌀과 견과류 대체품은 필요 없어요 가격', [literal_nut['sku']], ['related_literal'],
             context=crowded, missing_sku=True, unverified=True)

    qualified_rice = dict(five, name='쌀 5kg', price_credits=2000)
    qualified_nut = dict(literal_nut, name='견과류 5kg', price_credits=2000)
    exclusions = [offer(34, name='쌀 5kg', grade='A', price_credits=1900),
                  offer(35, name='견과류 5kg', grade='B', price_credits=2001),
                  offer(36, name='견과류 5kg', grade='B', price_credits=1900, expires_at=NOW + 239),
                  offer(37, name='쌀 4kg', grade='B', price_credits=1900),
                  offer(38, name='두부 5kg', grade='B', price_credits=1900),
                  offer(39, name='견과류 5kg', grade='B', price_credits=1900, expires_at=None)]
    qualified = snapshot([*exclusions, qualified_rice, qualified_nut])
    filter_text = '쌀과 견과류 5kg B등급이고 2,000크레딧 이하인, 남은 소비기한 4분 이상인 상품의 가격 알려주세요'
    prepared(filter_text, [A, literal_nut['sku']], ['named_pack', 'named_pack'], context=qualified, unverified=False)
    prepared(filter_text.replace('이하인', '미만인'), [], [], context=qualified)
    prepared(filter_text.replace('4분 이상인', '5분 초과인'), [], [], context=qualified)
    prepared('쌀과 견과류 4kg 말고 5kg B등급 2,000크레딧 이하 남은 시간 4분 이상',
             [A, literal_nut['sku']], ['named_pack', 'named_pack'], context=qualified)
    prepared('쌀과 견과류 4kg 또는 5kg 가격', [], [], context=qualified, unverified=True)
    for text in (question, partial, '견과류와 참치 가격 알려주세요', filter_text,
                 f'{A} 쌀과 견과류 가격', f'{A} 지금 구매해 주세요',
                 '쌀과 견과류를 주문하고 결제해 주세요', f'{A} 쌀 가격과 배송 정책 알려주세요'):
        fails({'op': 'prepared_fallback', 'text': text}, 'fallback_not_applicable', context=crowded)
    single_sku = snapshot([dict(literal_nut, sku=B)])
    fails({'op': 'prepared_fallback', 'text': partial}, 'fallback_not_applicable', context=single_sku)
    assert invoke({'op': 'prepared_fallback', 'text': '지금 파는 견과류의 상품명과 가격을 보여 주세요.'}, single_sku) == invoke(
        {'op': 'render', 'items': [pick_b]}, single_sku)

    compound = offer(101, name='하루한줌넛츠 20봉', category_path=['식품'], grade='B', price_credits=2000)
    generic = offer(102, name='일반 견과류 20봉', category_path=['식품'], grade='B', price_credits=1700)
    wrong_pack = offer(103, name='하루한줌넛츠 10봉', category_path=['식품'], grade='B', price_credits=1800)
    inner_alias = offer(104, name='한줌너츠믹스 20봉', category_path=['식품'], grade='B', price_credits=2100)
    labelled_only = offer(105, name='가상 상품 20봉', category_path=['식품', '하루한줌넛츠'])
    nuts_source = snapshot([generic, wrong_pack, compound, inner_alias, labelled_only])
    compound_sku = compound['sku']
    mixed_question = '하루한줌넛츠 20봉과 캠핑 조명도 있나요? 현재 가격 알려주세요'
    assert prepared(mixed_question, [compound_sku], ['named_pack'], context=nuts_source, unverified=True) == [
        [compound_sku, 'B', '하루한줌넛츠 20봉', 2000, ['식품'], 300]]
    mixed_page = invoke({'op': 'prepare', 'text': mixed_question}, nuts_source)
    assert mixed_page['catalogue']['matched_count'] == 1
    assert all(claim not in json.dumps(mixed_page, ensure_ascii=False)
               for claim in ('캠핑 조명', '원재료', '알레르기', 'checkout', '결제권'))
    prepared('하루한줌넛츠는 20봉 가격', [compound_sku], ['named_pack'], context=nuts_source, unverified=False)
    prepared('한줌너츠믹스 20봉 가격', [inner_alias['sku']], ['named_pack'], context=nuts_source, unverified=False)
    prepared('하루한줌넛츠 20봉 가격', [], [], context=snapshot([wrong_pack, generic, labelled_only]))
    prepared('가상하루한줌넛츠 20봉 가격', [], [], context=nuts_source, unverified=True)
    prepared('초가상너츠 20봉 가격', [], [], context=nuts_source, unverified=True)
    prepared('하루한줌넛츠 20봉 성분과 알레르기 정보', [compound_sku], ['named_pack'],
             context=nuts_source, unverified=True)
    prepared('하루한줌넛츠 20봉 B등급 2,000크레딧 이하 남은 시간 5분 이상', [compound_sku], ['named_pack'],
             context=nuts_source, unverified=False)
    for text in ('하루한줌넛츠 20봉 A등급', '하루한줌넛츠 20봉 2,000크레딧 미만',
                 '하루한줌넛츠 20봉 남은 시간 5분 초과'):
        prepared(text, [], [], context=nuts_source)
    prepared('캠핑 조명 제외 하루한줌넛츠 20봉 가격', [], [], context=nuts_source, unverified=True)
    prepared('미확인너츠 10봉 제외 하루한줌넛츠 20봉 가격', [], [], context=nuts_source, unverified=True)
    prepared(f'{compound_sku} 하루한줌넛츠 20봉 가격', [compound_sku], ['exact_sku'], context=nuts_source, unverified=False)
    prepared(f'{compound_sku} 하루한줌넛츠 10봉 가격', [], [], context=nuts_source)
    for alias in ('넛츠', '너츠'):
        prepared(f'{alias} 20봉 가격', [generic['sku'], compound_sku, inner_alias['sku']],
                 ['category_alternative'] * 3, context=nuts_source, unverified=False)
        fails({'op': 'prepared_fallback', 'text': f'{alias} 가격'}, 'fallback_not_applicable', context=snapshot([compound]))
    prepared('하루한줌넛츠와 두부 가격', [wrong_pack['sku'], C, compound_sku], ['related_literal'] * 3,
             context=snapshot([wrong_pack, compound, tofu_unit]), unverified=False)
    for text in (mixed_question, '하루한줌넛츠 20봉 원재료', '하루한줌넛츠 20봉 가격'):
        fails({'op': 'prepared_fallback', 'text': text}, 'fallback_not_applicable', context=nuts_source)
    assert invoke({'op': 'prepared_fallback', 'text': '하루한줌넛츠 가격'}, snapshot([compound])) == invoke(
        {'op': 'render', 'items': [{'sku': compound_sku, 'grade': 'B'}]}, snapshot([compound]))
    prepared('캠핑 조명 재고', [], [], context=snapshot([offer(106, name='캠핑 조명 20봉')]), unverified=True)

    food = [offer(i, name='가상 식품', category_path=['식품']) for i in range(201, 211)]
    cups = offer(211, name='유리컵', category_path=['생활'])
    grain = offer(212, name='현미 5kg', category_path=['곡물'])
    unsafe_cup = offer(213, name='https://example.net', category_path=['생활'])
    expired = offer(214, name='유리병', category_path=['생활'], expires_at=NOW)
    reserved = offer(215, name='가상 조명', category_path=['생활'], state='reserved')
    other_grade = dict(food[0], unit_ref='ref-216', grade='B')
    inventory_source = snapshot([food[0], other_grade, *food[1:], unsafe_cup, expired, reserved, cups, grain])
    inventory_skus = [food[0]['sku'], cups['sku'], grain['sku'], *(unit['sku'] for unit in food[1:6])]
    for text in ('현재 판매 상품 목록', '지금 어떤 상품 팔아요?'):
        prepared(text, inventory_skus, ['related_literal'] * 8, context=inventory_source, unverified=False)
        result = invoke({'op': 'prepare', 'text': text}, inventory_source)
        assert result['catalogue']['matched_count'] == 13
        fails({'op': 'prepared_fallback', 'text': text}, 'fallback_not_applicable', context=inventory_source)
        fails({'op': 'prepared_fallback', 'text': text}, 'fallback_not_applicable', context=snapshot([compound]))
    for text in ('현재 판매 상품 목록과 초가상어 가격', '지금 어떤 상품 팔아요? 결제권', '현재 판매 상품 목록 초가상어'):
        prepared(text, [], [], context=inventory_source, unverified=True)
    prepared('지금 어떤 상품 팔아요?', [], [], context=snapshot([]), unverified=False)
