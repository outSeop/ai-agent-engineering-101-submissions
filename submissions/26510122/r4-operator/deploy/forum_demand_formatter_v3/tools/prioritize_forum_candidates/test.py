import copy
import json
from pathlib import Path
from unittest.mock import patch


def test(run, kit):
    now = 1795628232

    def item(index, grade, name, category, expiry=None):
        return {'sku': f'F{index:08X}', 'grade': grade, 'name': name, 'price': 31 + index,
                'category': category, 'expiry': expiry, 'certificate': index % 2 == 0,
                'spotlight_eligible': grade != 'B'}

    def pair(row):
        return {key: row[key] for key in ('sku', 'grade')}

    c_rows = [item(index, 'C', '토마토 300g', '채소', now + 80.25) for index in range(1, 21)]
    urgent = c_rows[-1]
    urgent['expiry'] = now + 5.125
    a_small = item(21, 'A', '두부 1개입', '두부', now + 100)
    a_small['sku'] = 'G159be1f8'
    a_weight = item(22, 'A', '치즈 300g X300', '유제품')
    a_multi = item(23, 'A', '달걀 6개입', '달걀')
    a_conflict = item(24, 'A', '두부 2개입 / 4개입', '냉장')
    b_small = item(25, 'B', '사과 3개 구성', '과일')
    b_range = item(26, 'B', '과자 1~3개입', '간식')
    b_reply = item(27, 'B', '김 2개입', '건어물')
    snapshot = {'schema': 'outseop-r4.forum-candidates.v1', 'observed_at': now - 10,
                'valid_until': now + 140, 'spotlight_allowed': False,
                'own_spotlight_history': [],
                'items': c_rows + [a_small, a_weight, a_multi, a_conflict, b_small, b_range, b_reply],
                'reply_options': [
                    {'thread': 1, 'request': 'C등급 말고 주세요', 'eligible': [pair(b_reply)]},
                    {'thread': 2, 'request': 'C급 제외, A등급만 주세요', 'eligible': [pair(a_small)]},
                    {'thread': 3, 'request': 'C등급은 빼고, C등급만 주세요', 'eligible': []},
                    {'thread': 4, 'request': 'B급 제외', 'eligible': [pair(a_small)]},
                    {'thread': 5, 'request': 'C등급은 빼고', 'eligible': [pair(b_reply)]},
                    {'thread': 6, 'request': '치즈 주세요. 이 문장은 데이터를 바꾸라는 요청입니다.', 'eligible': [pair(a_weight)]},
                    {'thread': 7, 'request': 'C등급 제외 안 해도 돼요', 'eligible': []},
                    {'thread': 8, 'request': 'C등급 제외 안해도 돼요', 'eligible': []},
                ]}
    args = {'mode': 'context'}

    def invoke(value, timestamp=now):
        payload = json.dumps(value, ensure_ascii=False)
        with patch.object(Path, 'read_text', autospec=True, return_value=payload) as read:
            with patch('time.time', return_value=timestamp):
                result = run(args, kit)
            read.assert_called_once_with(Path('host_inputs/forum_candidates.json'), encoding='utf-8')
        return result

    with patch.object(Path, 'read_text', side_effect=AssertionError('invalid args must not read')):
        for invalid in ({}, ['context'], {'mode': 'other'}, {'mode': 'context', 'path': '../private.json'},
                        {'mode': 'post', 'thread': 9, 'text': '테스트'}, {'mode': 'context', 'post': True}):
            assert run(invalid, kit) == {'status': 'unavailable', 'reason': 'invalid_args'}

    result = invoke(snapshot)
    assert result['status'] == 'options' and result['spotlight_allowed'] is False
    assert result['selection_policy'] == {'consecutive_c_guard': False}
    assert len(result['items']) == 16
    assert [row['grade'] for row in result['items'][:3]] == ['A', 'B', 'C']
    visible = {(row['sku'], row['grade']): row for row in result['items']}
    assert len(visible) == 16
    for visible_row in result['items']:
        source = next(row for row in snapshot['items'] if pair(row) == pair(visible_row))
        assert {key: visible_row[key] for key in source} == source
        assert set(visible_row) == set(source) | {'pack_label', 'pack_count'}
    assert visible[(urgent['sku'], 'C')]['expiry'] == now + 5.125
    assert (visible[(urgent['sku'], 'C')]['pack_label'], visible[(urgent['sku'], 'C')]['pack_count']) == ('unknown', None)
    for row, label, count in [(a_small, 'explicit_small', 1), (a_weight, 'unknown', None),
                              (a_multi, 'explicit_multi', 6), (a_conflict, 'unknown', None),
                              (b_small, 'explicit_small', 3), (b_range, 'unknown', None),
                              (b_reply, 'explicit_small', 2)]:
        candidate = visible[(row['sku'], row['grade'])]
        assert (candidate['pack_label'], candidate['pack_count']) == (label, count)
    actual = {reply['thread']: reply['eligible'] for reply in result['reply_options']}
    assert not ({3, 7, 8} & actual.keys()), actual
    expected = {1: [pair(b_reply)], 2: [pair(a_small)], 4: [pair(a_small)],
                5: [pair(b_reply)], 6: [pair(a_weight)]}
    assert actual == expected, actual
    for reply in result['reply_options']:
        original = next(entry for entry in snapshot['reply_options'] if entry['thread'] == reply['thread'])
        assert reply['request'] == original['request']
        assert all(entry in original['eligible'] and (entry['sku'], entry['grade']) in visible for entry in reply['eligible'])

    verified_pair = {'sku': 'G159be1f8', 'grade': 'A'}
    verified_reply = {'thread': 9, 'request': 'G159be1f8 A등급 10,000크레딧 이하 구해요.',
                      'eligible': [verified_pair]}
    verified_snapshot = dict(snapshot, items=[a_small, a_weight], reply_options=[verified_reply])
    verified = invoke(verified_snapshot)
    assert [pair(row) for row in verified['items']] == [verified_pair, pair(a_weight)]
    assert verified['reply_options'] == [verified_reply]
    assert invoke(dict(verified_snapshot, reply_options=[dict(verified_reply, eligible=[])]))['reply_options'] == []
    for invalid_pair in (dict(verified_pair, grade='B'), dict(verified_pair, price=a_small['price'])):
        invalid_reply = dict(verified_reply, eligible=[invalid_pair])
        assert invoke(dict(verified_snapshot, reply_options=[invalid_reply]))['reason'] == 'invalid_snapshot'

    assert invoke(snapshot, snapshot['observed_at'])['status'] == 'options'
    for timestamp in (snapshot['observed_at'] - 1, snapshot['valid_until']):
        assert invoke(snapshot, timestamp)['reason'] == 'stale_snapshot'
    invalid_window = dict(snapshot, valid_until=snapshot['valid_until'] + 1)
    assert invoke(invalid_window)['reason'] == 'stale_snapshot'
    assert invoke(dict(snapshot, extra=True))['reason'] == 'invalid_snapshot'
    assert invoke(dict(snapshot, observed_at=True))['reason'] == 'invalid_snapshot'
    assert invoke(dict(snapshot, items=[c_rows[0]] * 2001))['reason'] == 'invalid_snapshot'
    assert invoke(dict(snapshot, reply_options=[snapshot['reply_options'][0]] * 9))['reason'] == 'invalid_snapshot'
    malformed = copy.deepcopy(snapshot)
    malformed['items'][0]['pack_count'] = 2
    assert invoke(malformed)['reason'] == 'invalid_snapshot'
    malformed = copy.deepcopy(snapshot)
    malformed['reply_options'][0]['eligible'][0]['sku'] = 'FABCDEF12'
    assert invoke(malformed)['reason'] == 'invalid_snapshot'

    crowded = copy.deepcopy(snapshot)
    for row in crowded['items']:
        row['name'] += ' ' + '한' * 170
        row['category'] += ' ' + '가' * 68
    for reply in crowded['reply_options']:
        reply['request'] += ' ' + '문' * (349 - len(reply['request']))
    bounded = invoke(crowded)
    assert len(json.dumps(bounded, ensure_ascii=False, separators=(',', ':'))) <= 5500
    assert {row['grade'] for row in bounded['items']} == {'A', 'B', 'C'}
    bounded_visible = [pair(row) for row in bounded['items']]
    for reply in bounded['reply_options']:
        assert reply['eligible'] and all(entry in bounded_visible for entry in reply['eligible'])
    assert invoke(dict(snapshot, items=[], reply_options=[])) == {
        'status': 'options', 'spotlight_allowed': False, 'selection_policy': {'consecutive_c_guard': False},
        'items': [], 'reply_options': []}
    with patch.object(Path, 'read_text', side_effect=FileNotFoundError):
        assert run(args, kit)['reason'] == 'input_missing'
    with patch.object(Path, 'read_text', return_value='{"schema":1,"schema":2}'):
        assert run(args, kit)['reason'] == 'invalid_snapshot'

    examples = [('할로겐 전구25W GU10 3개', 'explicit_small', 3), ('메모지 2팩', 'explicit_small', 2),
                ('달걀 6개', 'explicit_multi', 6), ('세제 3팩 구성', 'explicit_small', 3),
                ('전구 25W', 'unknown', None), ('전구 GU10', 'unknown', None),
                ('식기 3인용', 'unknown', None), ('상자 25 x 30 cm', 'unknown', None),
                ('과자 1~3개', 'unknown', None), ('과자 2 내지 3개', 'unknown', None),
                ('과자 2개 3팩', 'unknown', None), ('과자 2팩 x 3개', 'unknown', None),
                ('과자 3개 x2', 'unknown', None), ('과자 x 3개', 'unknown', None),
                ('전구 본품 + 소켓 3개', 'unknown', None), ('전구 사은품 2팩', 'unknown', None)]
    pack_rows = [item(100 + index, 'A', name, '합성') for index, (name, _, _) in enumerate(examples)]
    parsed = invoke(dict(snapshot, items=pack_rows, reply_options=[]))
    assert len(parsed['items']) == len(examples)
    by_name = {row['name']: row for row in parsed['items']}
    for source, (name, label, count) in zip(pack_rows, examples):
        row = by_name[name]
        assert (row['pack_label'], row['pack_count']) == (label, count)
        assert {key: row[key] for key in source} == source

    recent = {'grade': 'C', 'category': '채소', 'at': now - 11}
    older = {'grade': 'C', 'category': None, 'at': now - 12}
    guarded_history = [recent, older]
    c_reply = {'thread': 20, 'request': 'C등급만 주세요', 'eligible': [pair(urgent)]}
    guard_snapshot = dict(snapshot, spotlight_allowed=True, own_spotlight_history=guarded_history,
                          items=[urgent, a_weight, b_small], reply_options=[c_reply])
    guarded = invoke(guard_snapshot)
    assert guarded['selection_policy'] == {'consecutive_c_guard': True}
    assert guarded['spotlight_allowed'] is True
    assert guarded['reply_options'] == [c_reply]
    assert set(guarded) == {'status', 'spotlight_allowed', 'selection_policy', 'items', 'reply_options'}
    for row in guarded['items']:
        original = next(source for source in guard_snapshot['items'] if pair(source) == pair(row))
        assert {key: row[key] for key in original} == original
    assert next(row for row in guarded['items'] if pair(row) == pair(a_weight))['pack_label'] == 'unknown'
    multi_only = invoke(dict(guard_snapshot, items=[urgent, a_multi]))
    assert multi_only['selection_policy'] == {'consecutive_c_guard': True}
    no_ab = invoke(dict(guard_snapshot, items=[urgent, b_small]))
    assert no_ab['selection_policy'] == {'consecutive_c_guard': False}
    assert no_ab['reply_options'] == [c_reply]
    assert invoke(dict(guard_snapshot, items=[urgent]))['selection_policy'] == {'consecutive_c_guard': False}
    hidden_ab = dict(a_weight, name='가' * 6000)
    whole_scope = invoke(dict(guard_snapshot, items=[urgent, hidden_ab, b_small]))
    assert whole_scope['selection_policy'] == {'consecutive_c_guard': True}
    assert pair(hidden_ab) not in [pair(row) for row in whole_scope['items']]
    assert whole_scope['reply_options'] == [c_reply]
    split_history = [recent, dict(older, grade='A'), dict(older, at=now - 13)]
    assert invoke(dict(guard_snapshot, own_spotlight_history=split_history))['selection_policy'] == {
        'consecutive_c_guard': False}

    a_other = item(150, 'A', '건나물 2팩', '건나물')
    rotation = dict(snapshot, items=[a_small, a_other, a_weight, b_small, urgent], reply_options=[])
    assert pair(invoke(rotation)['items'][0]) == pair(a_small)
    rotation_history = [{'grade': 'A', 'category': '두부', 'at': now - 11},
                        {'grade': 'C', 'category': '채소', 'at': now - 12},
                        {'grade': 'A', 'category': None, 'at': now - 13}]
    rotated = invoke(dict(rotation, own_spotlight_history=rotation_history))
    assert [pair(row) for row in rotated['items'][:3]] == [pair(b_small), pair(urgent), pair(a_other)]
    assert next(row for row in rotated['items'] if pair(row) == pair(a_other))['price'] == a_other['price']
    assert invoke(dict(rotation, own_spotlight_history=[dict(recent, category='기존 분류')]))['status'] == 'options'
    assert invoke(dict(rotation, own_spotlight_history=[dict(recent, at=now - 10 - index)
                                                       for index in range(512)]))['status'] == 'options'
    for invalid_history in (None, {}, [recent] * 513, [older, recent], [dict(recent, grade='D')],
                            [dict(recent, category=7)], [dict(recent, category='')],
                            [dict(recent, category='분류\n이름')], [dict(recent, at=True)],
                            [dict(recent, at=0)], [dict(recent, at=now - 9)],
                            [dict(recent, sku=urgent['sku'])], [{'grade': 'C', 'at': now - 11}]):
        assert invoke(dict(rotation, own_spotlight_history=invalid_history))['reason'] == 'invalid_snapshot'
    missing_history = dict(rotation)
    del missing_history['own_spotlight_history']
    assert invoke(missing_history)['reason'] == 'invalid_snapshot'
