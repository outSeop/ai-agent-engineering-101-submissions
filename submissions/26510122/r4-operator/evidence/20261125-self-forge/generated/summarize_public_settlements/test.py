import time
from unittest.mock import patch

import httpx


def test(run, kit):
    assert kit.testing
    now = 10000
    start = 6400
    egg = 'G00000001'
    greens = 'G00000002'

    def row(seq, ts, kind='settle', sku=None, sealed=False, round_number=4):
        data = {'sku': sku, 'buyer': 'synthetic_buyer', 'price': 987654321, 'order': 'synthetic_order'}
        if sealed:
            data['sealed'] = 'synthetic_seal'
        return {'seq': seq, 'ts': ts, 'kind': kind, 'round': round_number, 'data': data}

    catalog = {'items': [
        {'sku': egg, 'name': '합성 계란', 'category': '계란', 'list_price': 987654321},
        {'sku': greens, 'name': '합성 채소', 'category': '야채'},
    ]}
    first_page = [
        row(10, start - 1, sku=egg),
        row(11, start, sku=egg),
        row(12, 6500, sku=greens, sealed=True),
        row(13, 6600, kind='supply', sku=egg),
        row(14, 6700, sku=egg, round_number=3),
    ]
    second_page = [
        row(15, 8000, sku=egg), row(16, 9000, sku='uncatalogued'),
        row(17, now, sku=greens), row(18, now + 1, sku=greens),
    ]

    def exercise(pages, product_payload, expected_requests):
        requests = []

        def respond(request):
            assert request.method == 'GET'
            assert request.url.host == 'market.ourolabs.ai'
            assert 'authorization' not in request.headers
            if request.url.path == '/api/catalog':
                requests.append('catalog')
                return httpx.Response(200, json=product_payload)
            assert request.url.path == '/api/ledger'
            after = request.url.params['after']
            requests.append(after)
            return httpx.Response(200, json=pages[after])

        original_client = httpx.Client
        transport = httpx.MockTransport(respond)
        with patch.object(httpx, 'Client', side_effect=lambda **kwargs: original_client(transport=transport, **kwargs)):
            with patch.object(time, 'time', return_value=now):
                result = run({}, kit)
        assert requests == expected_requests
        return result

    result = exercise(
        {'-1': [second_page[-1]], '-2000': first_page, '14': second_page},
        catalog, ['-1', '-2000', '14', 'catalog'],
    )
    assert result == {
        'mode': 'synthetic_test',
        'requested_time': {'start': start, 'end': now},
        'sample_time': {'start': start - 1, 'end': now + 1},
        'coverage': 'boundaries_observed',
        'by_sku': [
            {'sku': egg, 'name': '합성 계란', 'category': '계란', 'count': 2},
            {'sku': greens, 'name': '합성 채소', 'category': '야채', 'count': 1},
        ],
        'by_category': {'계란': 2, '야채': 1},
        'sealed_count': 1,
        'unclassified_count': 1,
    }

    at_start = exercise(
        {'-1': [second_page[-1]], '-2000': first_page[1:], '14': second_page},
        catalog, ['-1', '-2000', '14', 'catalog'],
    )
    assert at_start == {
        **result,
        'sample_time': {'start': start, 'end': now + 1},
        'coverage': 'partial',
    }

    capped_pages = {
        '-1': [row(30, now, sku=egg)],
        '-2000': [row(20, 9001, sku=egg)],
        '20': [row(21, 9002, sku=egg)],
        '21': [row(22, 9003, sku=egg)],
        '22': [row(23, 9004, sku=egg)],
    }
    partial = exercise(capped_pages, catalog, ['-1', '-2000', '20', '21', '22', 'catalog'])
    assert partial['coverage'] == 'partial'
    assert partial['sample_time'] == {'start': 9001, 'end': 9004}
    assert partial['by_category'] == {'계란': 4}

    empty = exercise({'-1': []}, catalog, ['-1'])
    assert empty['sample_time'] is None and empty['by_sku'] == []
    invalid = exercise({'-1': {'private': 'synthetic_row'}}, catalog, ['-1'])
    assert invalid == {'error': 'invalid_public_data'}
    assert run({'window_seconds': True}, kit) == {'error': 'invalid_window_seconds'}
