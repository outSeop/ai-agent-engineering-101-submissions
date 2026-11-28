from functools import partial
from random import Random
import re
from types import FunctionType, SimpleNamespace


def synthetic_sku(pattern):
    try:
        from re import _parser as parser
    except ImportError:
        import sre_parse as parser
    tree = parser.parse(pattern.pattern, pattern.flags)
    random = Random(12)
    categories = {
        'CATEGORY_DIGIT': '1234567890', 'CATEGORY_NOT_DIGIT': 'AB-_',
        'CATEGORY_WORD': 'ABC123_', 'CATEGORY_NOT_WORD': '-:@',
        'CATEGORY_SPACE': ' ', 'CATEGORY_NOT_SPACE': 'ABC123',
        'CATEGORY_LINEBREAK': '\n', 'CATEGORY_NOT_LINEBREAK': 'ABC123',
    }

    def emit(nodes, first, groups):
        def choose(values):
            return values[0] if first else random.choice(values)

        def characters(op, value):
            kind = str(op)
            if kind == 'LITERAL':
                return chr(value)
            if kind == 'RANGE':
                low, high = value
                return chr(low) + chr((low + high) // 2) + chr(high)
            if kind == 'CATEGORY':
                return categories[str(value)]
            raise AssertionError(f'unsupported v9 SKU character class opcode {kind}')

        parts = []
        for op, value in nodes:
            kind = str(op)
            if kind in ('LITERAL', 'CATEGORY'):
                parts.append(choose(characters(op, value)))
            elif kind == 'NOT_LITERAL':
                parts.append(choose(tuple(c for c in 'ABC123_-' if ord(c) != value)))
            elif kind == 'IN':
                if str(value[0][0]) == 'NEGATE':
                    excluded = ''.join(characters(item, arg) for item, arg in value[1:])
                    choices = tuple(c for c in 'ABC123_-:@' if c not in excluded)
                else:
                    choices = ''.join(characters(item, arg) for item, arg in value)
                parts.append(choose(choices))
            elif kind == 'SUBPATTERN':
                group, _, _, body = value
                text = emit(body, first, groups)
                if group is not None:
                    groups[group] = text
                parts.append(text)
            elif kind == 'BRANCH':
                parts.append(emit(choose(value[1]), first, groups))
            elif kind in ('MAX_REPEAT', 'MIN_REPEAT', 'POSSESSIVE_REPEAT'):
                minimum, maximum, body = value
                count = choose(tuple(range(minimum, min(maximum, minimum + 6) + 1)))
                parts.extend(emit(body, first, groups) for _ in range(count))
            elif kind == 'GROUPREF':
                parts.append(groups.get(value, ''))
            elif kind == 'ANY':
                parts.append(choose('ABC123'))
            elif kind not in ('AT', 'ASSERT', 'ASSERT_NOT'):
                raise AssertionError(f'unsupported v9 SKU opcode {kind}')
        return ''.join(parts)

    for attempt in range(128):
        candidate = emit(tree, attempt == 0, {})
        if candidate and pattern.fullmatch(candidate) and pattern.findall(candidate) == [candidate]:
            return candidate
    raise AssertionError(f'no synthetic SKU satisfied the inherited expression {pattern.pattern!r}')


def test(run, kit):
    env = run.__globals__
    raw = env['load_verified11']()
    optimized = env['optimize_classifier'](env['load_verified11']())
    v9 = raw.load_owner().load_v9()
    now = 1795861675
    sku = synthetic_sku(v9.SKU)
    post = {'id': 1, 'round': 4, 'role': 'buyer', 'author': 'synthetic-buyer', 'ts': now - 60,
            'visibility': 'public', 'public': True, 'is_public': True, 'private': False, 'is_private': False,
            'parent': None, 'parent_id': None, 'thread': None, 'thread_id': None, 'reply_to': None}
    assert v9.public_root(dict(post, text='사과 필요해요'))
    offer = {'sku': sku, 'name': '사과 500g', 'category': '식품>음료', 'grade': 'C',
             'price': 100, 'expiry': now + 7200, 'certificate': True, '_base': 100, '_unit': 101}
    cases = [
        '사과 필요해요', '사과 찾고 있어요', '사과 가격을 알려 주세요',
        '사과 산뜻한 맛 찾고 있어요', '사과 고소한 느낌 필요해요',
        '사과 C등급 필요해요', '사과 A등급 필요해요',
        '사과 150 크레딧 이하로 필요해요', '사과 50 크레딧 이하로 필요해요',
        '사과 유통기한 1시간 이상 필요해요', '사과 유통기한 3시간 이상 필요해요',
        '사과 시장 인증서 필요해요', '사과 500g이 필요해요', '사과 250g 필요해요',
        f'{sku}만 필요해요', f'only {sku} please send a quote',
        '사과 제외하고 찾고 있어요', '사과 필요해요. 카톡으로 알려 주세요', '사과를 샀어요. 후기입니다',
    ]
    inputs = [(dict(post, text=text), offer, now) for text in cases]
    request = dict(post, text=cases[0])
    inputs += [
        (request, dict(offer, expiry=now - 1), now),
        (request, offer, now + 21601),
        (dict(request, role='shop'), offer, now),
        (dict(request, visibility='private', public=False, is_public=False, private=True, is_private=True), offer, now),
        (dict(request, text=cases[8]), dict(offer, price=1), now),
        (dict(request, text=cases[11]), dict(offer, certificate=False), now),
        (dict(request, text=cases[5]), dict(offer, grade='A'), now),
    ]
    expected = [raw.classify(v9, *args) for args in inputs]
    assert set(expected) == {None, 'strict', 'reference'}
    assert expected[0] == 'strict' and expected[len(cases)] is None
    assert expected[len(cases) + 1] is None

    bulk = []
    for index in range(540):
        word = chr(0xB000 + index) + '나무'
        item = dict(offer, name=word)
        bulk.append((dict(post, text=word + ' 필요해요'), item, now))
    bulk_expected = [raw.classify(v9, *args) for args in bulk]
    compiler_calls = []
    scopes = []
    scope = env['COMPILER']

    def counting_compile(pattern, flags):
        compiler_calls.append((pattern, type(flags), flags))
        return re.compile(pattern, flags)

    def compare_errors():
        broken = dict(offer)
        del broken['expiry']
        errors = []
        for classifier in (raw.classify, optimized.classify):
            try:
                classifier(v9, request, broken, now)
            except KeyError as error:
                errors.append((type(error), error.args))
        assert errors == [(KeyError, ('expiry',))] * 2

    def exercise(args, received_kit):
        assert args == {'action': 'slate_context'} and received_kit is kit
        compiler = scope.get()
        assert compiler.cache_info().maxsize == 8192 and compiler.cache_info().currsize == 0
        scopes.append(compiler)
        start = len(compiler_calls)
        assert [optimized.classify(v9, *item) for item in inputs] == expected
        compare_errors()
        before_bulk = len(compiler_calls)
        assert [optimized.classify(v9, *item) for item in bulk] == bulk_expected
        loaded = len(compiler_calls)
        assert len(set(compiler_calls[before_bulk:loaded])) > 512
        assert loaded > start
        assert [optimized.classify(v9, *item) for item in bulk] == bulk_expected
        assert [optimized.classify(v9, *item) for item in reversed(inputs)] == expected[::-1]
        assert len(compiler_calls) == loaded
        return {'checked': True}

    call = FunctionType(run.__code__, dict(env, OWNER=SimpleNamespace(run=exercise),
                                          new_compiler=partial(env['new_compiler'], counting_compile)))
    for _ in range(2):
        assert call({'action': 'slate_context'}, kit) == {'checked': True}
        assert scope.get() is None and scopes[-1].cache_info().currsize == 0
    assert scopes[0] is not scopes[1]

    small = env['new_compiler'](counting_compile, maxsize=3)
    small('same', int(re.I))
    small('same', re.I)
    small('same', 0)
    assert small.cache_info().misses == 3
    small('other', 0)
    assert small.cache_info().currsize == 3
    small('same', int(re.I))
    assert small.cache_info().misses == 5
    small.cache_clear()

    def unavailable():
        raise ValueError('synthetic publisher digest mismatch')

    raw_fail = FunctionType(raw.run.__code__, dict(raw.run.__globals__, OWNER=None, load_owner=unavailable))
    wrapped_fail = FunctionType(run.__code__, dict(env, OWNER=None, load_verified11=unavailable))
    assert raw_fail({}, kit) == wrapped_fail({}, kit) == {'status': 'hold'}
    assert scope.get() is None
