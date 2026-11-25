from copy import deepcopy
import json


def test(run, kit):
    assert kit.testing
    egg = '식품>합성분류>계란'
    other_egg = '식품 > 다른 합성분류 > 계란'
    greens = '식품>신선야채(부패주의)'
    summary = {
        'mode': 'synthetic_test',
        'requested_time': {'start': 6400, 'end': 10000},
        'sample_time': {'start': 6399.5, 'end': 9999.75},
        'coverage': 'boundaries_observed',
        'by_sku': [{'sku': 'G00000001', 'name': '합성 계란', 'category': egg, 'count': 3}],
        'by_category': {egg: 3},
        'sealed_count': 0,
        'unclassified_count': 0,
    }

    def plan(payload, existing=()):
        return run({'summary': payload, 'existing_skus': list(existing)}, kit)

    result = plan(summary)
    assert result['status'] == 'planning_only' and result['provisional']
    for field in ('mode', 'requested_time', 'sample_time', 'coverage'):
        assert result[field] == summary[field]
    assert result['candidates'] == [
        {'sku': 'G00000001', 'category': egg, 'observed_count': 3, 'planned_units': 1},
    ]
    assert plan(summary, ['G00000001'])['candidates'] == []

    mixed = deepcopy(summary)
    mixed.update({
        'by_sku': [
            {'sku': 'G00000001', 'name': '합성 기존 계란', 'category': egg, 'count': 12},
            {'sku': 'G00000004', 'name': '합성 원문 지시 표식', 'category': greens, 'count': 5},
            {'sku': 'G00000002', 'name': '합성 계란 A', 'category': egg, 'count': 4},
            {'sku': 'G00000003', 'name': '합성 계란 B', 'category': egg, 'count': 4},
            {'sku': 'G00000005', 'name': '합성 다른 계란', 'category': other_egg, 'count': 2},
        ],
        'by_category': {egg: 20, greens: 5, other_egg: 2},
        'coverage': 'partial',
        'sample_time': {'start': 6400.25, 'end': 9999.75},
        'sealed_count': 7,
        'unclassified_count': 2,
    })
    mixed['by_sku'][1]['untrusted_extra'] = '합성 비공개 필드 표식'
    mixed['by_sku'].reverse()
    result = plan(mixed, ['G00000001'])
    assert result['coverage'] == 'partial' and result['provisional']
    assert result['sample_time'] == mixed['sample_time']
    assert result['candidates'] == [
        {'sku': 'G00000004', 'category': greens, 'observed_count': 5, 'planned_units': 1},
        {'sku': 'G00000002', 'category': egg, 'observed_count': 4, 'planned_units': 1},
        {'sku': 'G00000005', 'category': other_egg, 'observed_count': 2, 'planned_units': 1},
    ]
    assert result['sealed_count'] == 7 and result['unclassified_count'] == 2
    encoded = json.dumps(result, ensure_ascii=False)
    assert '합성 원문 지시 표식' not in encoded and '합성 비공개 필드 표식' not in encoded

    for totals in ({egg: 8, greens: 5, other_egg: 2}, {egg: 20, greens: 5, '계란': 2},
                   {egg: 20, greens: 5, other_egg: 2, '김치': 1}, {egg: 20, greens: 5}):
        assert plan(dict(mixed, by_category=totals), ['G00000001']) == {
            'error': 'inconsistent_category_totals',
        }
    for totals in (None, {egg: True}, {egg: 0}, {egg: -1}, {egg: 3.0}, {' ': 3}):
        assert plan(dict(summary, by_category=totals)) == {'error': 'invalid_category_totals'}
    for count in (0, True, -1, 3.0):
        rows = [dict(summary['by_sku'][0], count=count)]
        assert plan(dict(summary, by_sku=rows)) == {'error': 'invalid_sku_observation'}
    rows = mixed['by_sku'] + [dict(mixed['by_sku'][-1], category=other_egg)]
    assert plan(dict(mixed, by_sku=rows), ['G00000001']) == {'error': 'duplicate_sku_observation'}
    assert plan(dict(mixed, coverage='boundaries_observed')) == {'error': 'inconsistent_coverage'}
    assert plan(dict(summary, sample_time={'start': 6400, 'end': 9999.75})) == {
        'error': 'inconsistent_coverage',
    }
    for sample_time in (None, {'start': 6200, 'end': 6399.75}, {'start': 10000.25, 'end': 10020}):
        assert plan(dict(mixed, sample_time=sample_time)) == {'error': 'observations_outside_sample'}
    empty = dict(mixed, by_sku=[], by_category={})
    empty_result = plan(empty)
    assert empty_result['candidates'] == []
    assert empty_result['sealed_count'] == 7 and empty_result['unclassified_count'] == 2
    assert plan(dict(empty, by_category={egg: 9})) == {'error': 'inconsistent_category_totals'}
    for counts in ({'sealed_count': -1}, {'unclassified_count': False}):
        assert plan(dict(empty, **counts)) == {'error': 'invalid_settlement_summary'}
    assert plan(dict(empty, sample_time=None)) == {'error': 'observations_outside_sample'}
    no_rows = plan(dict(empty, sample_time=None, sealed_count=0, unclassified_count=0))
    assert no_rows['candidates'] == [] and no_rows['sample_time'] is None and no_rows['provisional']
