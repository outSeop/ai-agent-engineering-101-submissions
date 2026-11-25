import math
from collections import Counter


def catalog_text(value):
    return isinstance(value, str) and bool(value.strip())


def whole(value):
    return type(value) is int and value >= 0


def timestamp(value):
    return whole(value) or (type(value) is float and math.isfinite(value) and value >= 0)


def times(value, check):
    if isinstance(value, dict):
        start, end = value.get('start'), value.get('end')
        if check(start) and check(end) and start <= end:
            return {'start': start, 'end': end}
    return None


def run(args, kit):
    if not isinstance(args, dict):
        return {'error': 'invalid_input'}
    existing = args.get('existing_skus')
    if not isinstance(existing, list) or not all(catalog_text(sku) for sku in existing):
        return {'error': 'existing_sku_list_required'}
    summary = args.get('summary')
    if not isinstance(summary, dict) or 'error' in summary:
        return {'error': 'settlement_summary_required'}

    mode, coverage = summary.get('mode'), summary.get('coverage')
    requested = times(summary.get('requested_time'), whole)
    raw_sample = summary.get('sample_time')
    sample = times(raw_sample, timestamp)
    rows = summary.get('by_sku')
    reported_categories = summary.get('by_category')
    sealed = summary.get('sealed_count')
    unclassified = summary.get('unclassified_count')
    if (mode not in ('synthetic_test', 'public_market_sample')
            or coverage not in ('boundaries_observed', 'partial')
            or requested is None or not 60 <= requested['end'] - requested['start'] <= 86400
            or 'sample_time' not in summary or (raw_sample is not None and sample is None)
            or not isinstance(rows, list) or not whole(sealed) or not whole(unclassified)):
        return {'error': 'invalid_settlement_summary'}
    if coverage == 'boundaries_observed' and (sample is None or sample['start'] >= requested['start']):
        return {'error': 'inconsistent_coverage'}
    if rows or sealed or unclassified:
        if sample is None or sample['end'] < requested['start'] or sample['start'] > requested['end']:
            return {'error': 'observations_outside_sample'}
    if not isinstance(reported_categories, dict) or not all(
        catalog_text(category) and whole(count) and count > 0
        for category, count in reported_categories.items()
    ):
        return {'error': 'invalid_category_totals'}

    known = set(existing)
    seen_skus = set()
    category_counts = Counter()
    eligible = []
    for row in rows:
        if not isinstance(row, dict):
            return {'error': 'invalid_sku_observation'}
        sku, category, count = row.get('sku'), row.get('category'), row.get('count')
        if not catalog_text(sku) or not catalog_text(category) or not whole(count) or count == 0:
            return {'error': 'invalid_sku_observation'}
        if sku in seen_skus:
            return {'error': 'duplicate_sku_observation'}
        seen_skus.add(sku)
        # 정산 v2의 전체 분류 문자열을 변환 없이 집계 키로 사용한다.
        category_counts[category] += count
        if sku not in known:
            eligible.append({'sku': sku, 'category': category, 'observed_count': count, 'planned_units': 1})

    if dict(category_counts) != reported_categories:
        return {'error': 'inconsistent_category_totals'}

    selected = []
    selected_categories = set()
    for candidate in sorted(eligible, key=lambda item: (-item['observed_count'], item['sku'])):
        category = candidate['category']
        if category not in selected_categories:
            selected.append(candidate)
            selected_categories.add(category)
    return {
        'mode': mode,
        'status': 'planning_only',
        'coverage': coverage,
        'provisional': coverage == 'partial' or mode == 'synthetic_test',
        'requested_time': requested,
        'sample_time': sample,
        'candidates': selected,
        'sealed_count': sealed,
        'unclassified_count': unclassified,
        'basis': '공개 정산 요약에서 카탈로그에 연결된 정확한 SKU의 표본 관측 건수. 후보 제외는 입력된 기존 취급 목록에 따름.',
        'limits': '입력 출처와 신규 여부는 별도 확인이 필요하다. 실제 고객 선호, 전환 효과, 수요 예측, 우리 매출·판매율, 최종 매입 판단은 미확인이다.',
        'before_purchase': ['공급가', '수수료·가스', '보관비·폐기 위험', '유통기한', '환불·혜택 비용', '현금 하한'],
    }
