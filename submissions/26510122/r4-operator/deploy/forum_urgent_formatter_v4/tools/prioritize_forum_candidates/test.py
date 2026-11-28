import json


def test(run, kit):
    assert run({}, kit) == {'status': 'unavailable', 'reason': 'invalid_args'}
    logic = run.__globals__
    select = logic['select']
    validate = logic['validate']
    urgent_c = logic['urgent_c']
    now = 1795858781

    def item(number, grade='C', expiry=None, **changes):
        value = {'sku': f'F{number:08x}', 'grade': grade, 'name': '상품', 'price': 9999,
                 'category': '식품', 'expiry': expiry, 'certificate': True, 'spotlight_eligible': True}
        return dict(value, **changes)

    def pair(value):
        return {key: value[key] for key in ('sku', 'grade')}

    def snapshot(items, replies=(), history=True, allowed=True):
        return {'schema': 'outseop-r4.forum-candidates.v1', 'observed_at': now - 10,
                'valid_until': now + 60, 'spotlight_allowed': allowed, 'items': items,
                'reply_options': list(replies), 'own_spotlight_history': [
                    {'grade': 'C', 'category': '식품', 'at': now - 20},
                    {'grade': 'C', 'category': None, 'at': now - 30}] if history else []}

    def evaluate(source):
        assert validate(source, now) is None
        result = select(source, now)
        assert result.keys() == {'status', 'spotlight_allowed', 'selection_policy', 'items', 'reply_options'}
        assert result['status'] == 'options'
        assert result['spotlight_allowed'] is source['spotlight_allowed']
        assert result['selection_policy'].keys() == {'consecutive_c_guard'}
        assert type(result['selection_policy']['consecutive_c_guard']) is bool
        assert len(result['items']) <= 16
        assert len(json.dumps(result, ensure_ascii=False, separators=(',', ':'), allow_nan=False)) <= 5500
        originals = {(row['sku'], row['grade']): row for row in source['items']}
        visible = set()
        for row in result['items']:
            key = row['sku'], row['grade']
            original = originals[key]
            assert key not in visible
            visible.add(key)
            assert row.keys() == original.keys() | {'pack_label', 'pack_count'}
            assert all(row[field] == original[field] for field in original if field != 'spotlight_eligible')
            if row['spotlight_eligible'] != original['spotlight_eligible']:
                assert original['spotlight_eligible'] is True and row['spotlight_eligible'] is False
                assert row['grade'] == 'C' and not urgent_c(original, now)
        for reply in result['reply_options']:
            original = next(option for option in source['reply_options'] if option['thread'] == reply['thread'])
            assert reply['request'] == original['request'] and reply['eligible']
            assert reply['eligible'] == [value for value in original['eligible'] if value in reply['eligible']]
            assert all((value['sku'], value['grade']) in visible for value in reply['eligible'])
        return result

    lower = item(2, expiry=now + 1200, name='과자 2개입')
    tied = item(1, expiry=float(now + 1200), name='과자 2개 또는 3개')
    upper = item(3, expiry=now + 21600)
    too_soon = item(4, expiry=now + 1199)
    too_late = item(5, expiry=now + 21601)
    missing = item(6)
    ineligible = item(7, expiry=now + 1200, spotlight_eligible=False)
    a = item(8, 'A', now + 1200, category='생활', price=10000)
    b = item(9, 'B', category='문구')
    assert all(urgent_c(value, now) for value in (lower, tied, upper))
    assert all(not urgent_c(value, now) for value in (too_soon, too_late, missing, ineligible, a, b))
    for expiry in (None, True, False, float('inf'), float('-inf'), float('nan'), str(now + 1200), now, now - 1):
        assert not urgent_c(item(10, expiry=expiry), now)
    for expiry in (True, False, float('inf'), float('-inf'), float('nan'), str(now + 1200)):
        assert validate(snapshot([item(10, expiry=expiry)]), now) == 'invalid_snapshot'

    mixed = {'thread': 1, 'request': 'A등급만, 예산 10000원 이하로 부탁해요.', 'eligible': [pair(a)]}
    c_reply = {'thread': 2, 'request': '이 상품을 찾고 있어요.', 'eligible': [pair(too_soon)]}
    rows = [lower, a, upper, too_soon, missing, b, tied, too_late, ineligible]
    source = snapshot(rows, [mixed, c_reply], allowed=False)
    result = evaluate(source)
    assert result['selection_policy'] == {'consecutive_c_guard': False}
    assert [pair(row) for row in result['items'][:3]] == [pair(value) for value in (tied, lower, upper)]
    assert [pair(row) for row in evaluate(dict(source, items=list(reversed(rows))))['items'][:3]] == [pair(value) for value in (tied, lower, upper)]
    assert {row['grade'] for row in result['items'][3:]} >= {'A', 'B'}
    by_sku = {row['sku']: row for row in result['items']}
    assert all(by_sku[value['sku']]['spotlight_eligible'] for value in (tied, lower, upper, a, b))
    assert all(not by_sku[value['sku']]['spotlight_eligible'] for value in (too_soon, too_late, missing, ineligible))
    assert all(value['spotlight_eligible'] for value in (too_soon, too_late, missing))
    assert (by_sku[tied['sku']]['pack_label'], by_sku[tied['sku']]['pack_count']) == ('unknown', None)
    assert (by_sku[lower['sku']]['pack_label'], by_sku[lower['sku']]['pack_count']) == ('explicit_small', 2)
    assert result['reply_options'] == [mixed, c_reply]

    ordinary = [too_late, b, too_soon, a]
    result = evaluate(snapshot(ordinary, [mixed, c_reply]))
    assert result['selection_policy'] == {'consecutive_c_guard': True}
    assert [pair(row) for row in result['items']] == [pair(value) for value in (a, b, too_soon, too_late)]
    assert all(row['spotlight_eligible'] for row in result['items'])
    assert result['reply_options'] == [mixed, c_reply]
    for source_without_guard in (snapshot([lower, too_soon, a], history=False), snapshot([lower, too_soon])):
        result = evaluate(source_without_guard)
        assert result['selection_policy'] == {'consecutive_c_guard': False}
        assert all(row['spotlight_eligible'] for row in result['items'])

    extras = [item(number, ('A', 'B', 'C')[number % 3], category=f'분류 {number % 5}') for number in range(20, 70)]
    crowded = evaluate(snapshot(rows + extras, [mixed, c_reply]))
    assert len(crowded['items']) == 16 and crowded['reply_options'] == [mixed, c_reply]
    long_rows = [dict(value, name='긴 상품명 ' * 100) for value in extras]
    bounded = evaluate(snapshot(rows + long_rows, [mixed, c_reply]))
    assert len(bounded['items']) < 16 and bounded['reply_options'] == [mixed, c_reply]
    assert len(json.dumps(bounded, ensure_ascii=False, separators=(',', ':'))) > 4500
    return True
