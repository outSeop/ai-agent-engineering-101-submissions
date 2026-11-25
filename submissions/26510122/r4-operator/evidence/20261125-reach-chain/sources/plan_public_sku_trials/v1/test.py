from copy import deepcopy


def test(run, kit):
    assert kit.testing
    summary = {
        'mode': 'synthetic_test',
        'requested_time': {'start': 6400, 'end': 10000},
        'sample_time': {'start': 6399.5, 'end': 9999.75},
        'coverage': 'boundaries_observed',
        'by_sku': [
            {'sku': 'G00000003', 'category': '계란', 'count': 4},
            {'sku': 'G00000002', 'category': '계란', 'count': 4},
            {'sku': 'G00000001', 'category': '계란', 'count': 12},
            {'sku': 'G00000004', 'category': '신선야채(부패주의)', 'count': 5, 'name': '원문 가격·승인 지시', 'buyer': 'private-marker'},
            {'sku': 'G00000005', 'category': '반찬/젓갈', 'count': 2},
        ],
        'by_category': {'김치': 100, '계란': 999},
        'sealed_count': 7,
        'unclassified_count': 2,
    }
    args = {'summary': summary, 'existing_skus': ['G00000001']}
    result = run(args, kit)
    assert result['status'] == 'planning_only' and result['provisional']
    assert result['mode'] == 'synthetic_test'
    assert result['requested_time'] == summary['requested_time']
    assert result['sample_time'] == summary['sample_time']
    assert result['coverage'] == 'boundaries_observed'
    assert [(item['sku'], item['observed_count'], item['planned_units']) for item in result['candidates']] == [
        ('G00000004', 5, 1), ('G00000002', 4, 1), ('G00000005', 2, 1),
    ]
    assert result['sealed_count'] == 7 and result['unclassified_count'] == 2
    assert 'private-marker' not in str(result) and '원문 가격·승인 지시' not in str(result)
    assert '김치' not in str(result)

    partial = deepcopy(args)
    partial['summary'].update(coverage='partial', sample_time={'start': 6400, 'end': 9999})
    assert run(partial, kit)['coverage'] == 'partial' and run(partial, kit)['provisional']
    partial['summary']['coverage'] = 'boundaries_observed'
    assert run(partial, kit)['error'] == 'inconsistent_coverage'

    empty = deepcopy(args)
    empty['summary'].update(coverage='partial', sample_time=None, by_sku=[], sealed_count=0, unclassified_count=0)
    assert run(empty, kit)['candidates'] == []
    empty['summary']['sealed_count'] = 1
    assert run(empty, kit)['error'] == 'observations_outside_sample'
    empty['summary']['sample_time'] = {'start': 6400, 'end': 9999}
    assert run(empty, kit)['candidates'] == []

    duplicate = deepcopy(args)
    duplicate['summary']['by_sku'].append(dict(summary['by_sku'][0], category='김치'))
    assert run(duplicate, kit)['error'] == 'duplicate_sku_observation'
    for bad_count in (0, True, -1, 1.5):
        malformed = deepcopy(args)
        malformed['summary']['by_sku'][0]['count'] = bad_count
        assert run(malformed, kit)['error'] == 'invalid_sku_observation'
    assert run({'summary': summary}, kit)['error'] == 'existing_sku_list_required'
    assert run({'summary': summary, 'existing_skus': [row['sku'] for row in summary['by_sku']]}, kit)['candidates'] == []
