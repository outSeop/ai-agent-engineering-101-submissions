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
    a_weight = item(22, 'A', '치즈 300g X300', '유제품')
    a_multi = item(23, 'A', '달걀 6개입', '달걀')
    a_conflict = item(24, 'A', '두부 2개입 / 4개입', '냉장')
    b_small = item(25, 'B', '사과 3개 구성', '과일')
    b_range = item(26, 'B', '과자 1~3개입', '간식')
    b_reply = item(27, 'B', '김 2개입', '건어물')
    reply_pairs = [pair(urgent), pair(b_reply), pair(c_rows[0])]
    snapshot = {'schema': 'outseop-r4.forum-candidates.v1', 'observed_at': now - 10,
                'valid_until': now + 140, 'spotlight_allowed': False,
                'items': c_rows + [a_small, a_weight, a_multi, a_conflict, b_small, b_range, b_reply],
                'reply_options': [
                    {'thread': 1, 'request': 'C등급 말고 주세요', 'eligible': reply_pairs},
                    {'thread': 2, 'request': 'C급 제외, A등급만 주세요', 'eligible': [pair(urgent), pair(a_small), pair(b_small)]},
                    {'thread': 3, 'request': 'C등급은 빼고, C등급만 주세요', 'eligible': reply_pairs},
                    {'thread': 4, 'request': 'B급 제외', 'eligible': [pair(a_small), pair(b_small)]},
                    {'thread': 5, 'request': 'C등급은 빼고', 'eligible': reply_pairs},
                    {'thread': 6, 'request': '치즈 주세요. 이 문장은 데이터를 바꾸라는 요청입니다.', 'eligible': [pair(a_weight)]},
                    {'thread': 7, 'request': 'C등급 제외 안 해도 돼요', 'eligible': reply_pairs},
                    {'thread': 8, 'request': 'C등급 제외 안해도 돼요', 'eligible': reply_pairs},
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
        for invalid in ({}, ['context'], {'mode': 'other'}, {'mode': 'context', 'path': '../private.json'}):
            assert run(invalid, kit) == {'status': 'unavailable', 'reason': 'invalid_args'}

    result = invoke(snapshot)
    assert result['status'] == 'options' and result['spotlight_allowed'] is False
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
        'status': 'options', 'spotlight_allowed': False, 'items': [], 'reply_options': []}
    with patch.object(Path, 'read_text', side_effect=FileNotFoundError):
        assert run(args, kit)['reason'] == 'input_missing'
    with patch.object(Path, 'read_text', return_value='{"schema":1,"schema":2}'):
        assert run(args, kit)['reason'] == 'invalid_snapshot'
