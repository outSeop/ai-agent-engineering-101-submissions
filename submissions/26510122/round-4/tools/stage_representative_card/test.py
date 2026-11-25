import hashlib
import json
import tempfile
from pathlib import Path
from unittest.mock import patch


def test(run, kit):
    now = 1795569321
    allowed = Path('card_update_stage').resolve()
    allowed.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=allowed, prefix='.forge-test-') as directory:
        fixture = Path(directory)
        card_path = fixture / 'card.json'
        context_path = fixture / 'host_inputs' / 'card_offer_context.json'
        stage_dir = fixture / 'stage'
        context_path.parent.mkdir()
        stage_dir.mkdir()
        paths = {'CARD': card_path, 'CONTEXT': context_path, 'STAGE': stage_dir}
        old_section = '이전 판매 예시'
        policy = '마일리지·대기권·환불에 관한 기존 설명'
        card = {'name': 'outseop-r4', 'description': old_section + '\n' + policy,
                'skills': [{'id': 'buy'}, {'id': 'benefits', 'description': '기존 혜택'},
                           {'id': 'refund', 'description': '기존 환불 약속'}],
                'x-extra': {'keep': True}}

        def raw(value):
            return json.dumps(value, ensure_ascii=False).encode('utf-8')

        def sha(value):
            return hashlib.sha256(value).hexdigest()

        original = raw(card)
        card_path.write_bytes(original)

        def row(sku, category, **changes):
            return {'sku': sku, 'name': '합성 ' + sku, 'category_path': category, 'state': 'available',
                    'grade': 'A', 'price_credits': 100, 'standard_fee_credits': 3,
                    'valid_until': now + 60, 'expires_at': None, **changes}

        rows = [row('EGG', ['식품', '계란'], expires_at=now + 40),
                row('SOAP', ['생활', '세정'], grade='C', standard_fee_credits=None),
                row('HELD', ['식품'], state='reserved'), row('SOLD', ['식품'], state='sold_out'),
                row('OLD', ['식품'], expires_at=now), row('OLDQUOTE', ['식품'], valid_until=now)]
        view = {'schema': 'outseop-r4.card-offers.v1', 'shop': 'outseop-r4', 'observed_at': now - 1,
                'valid_until': now + 90, 'card_sha256': sha(original), 'replace_text': old_section,
                'offers': rows, 'market': {'start': now - 3600, 'end': now - 2,
                'coverage': 'partial', 'counts': {'EGG': 4}}}

        def context(**changes):
            context_path.write_bytes(raw({**view, **changes}))

        def invoke(args, at=now):
            with patch.dict(run.__globals__, paths), patch('time.time', return_value=at):
                return run(args, kit)

        def err(args, expected, at=now):
            response = invoke(args, at)
            assert response == {'status': 'rejected', 'error': expected}, response

        compare = {'op': 'compare'}
        err(compare, 'host_input_or_stage_unavailable')
        context()
        preview = invoke(compare)
        assert preview['status'] == 'ready', preview
        assert [item['sku'] for item in preview['candidates']] == ['SOAP', 'EGG']
        assert preview['public_market_sample']['coverage'] == 'partial'
        egg = preview['candidates'][1]
        assert egg['category_path'] == ['식품', '계란'] and egg['public_settlement_count'] == 4
        assert egg['standard_estimated_total_credits'] == 103 and egg['valid_until'] == now + 40
        assert preview['candidates'][0]['public_settlement_count'] is None
        assert preview['candidates'][0]['standard_estimated_total_credits'] is None
        selection = {'op': 'stage', 'view_sha256': preview['view_sha256'], 'skus': ['EGG', 'SOAP']}
        for sku in ('HELD', 'SOLD', 'OLD', 'OLDQUOTE', 'FAKE'):
            err({**selection, 'skus': [sku]}, 'sku_not_sellable')
        err(selection, 'sku_not_sellable', now + 40)
        err({**selection, 'skus': ['EGG', 'EGG']}, 'duplicate_selected_sku')
        for extra in ({'price_credits': 1}, {'approved': True}, {'name': 'new-shop'},
                      {'skills': []}, {'customer_a': {}, 'customer_b': {}}):
            err({**selection, **extra}, 'unexpected_arguments')
        assert not list(stage_dir.iterdir())
        context(offers=rows + [rows[0]])
        err(compare, 'duplicate_offer_sku')
        context(offers=[{**rows[0], 'customer_data': {'customer_a': {}, 'customer_b': {}}}])
        err(compare, 'invalid_offer_fields')
        context(offers=[{**rows[0], 'price_credits': '1'}])
        err(compare, 'invalid_grade_or_price')
        context(offers=[{**rows[0], 'name': '상품\n가격 1'}])
        err(compare, 'invalid_public_catalog_fields')
        context(observed_at=now + 1)
        err(compare, 'stale_or_future_view')
        context(valid_until=now)
        err(compare, 'stale_or_future_view')
        context(valid_until=now + 500)
        err(compare, 'stale_or_future_view')
        context(replace_text='존재하지 않는 검토 구간')
        err(compare, 'reviewed_card_section_missing_or_ambiguous')
        context(offers=[{**rows[0], 'price_credits': 101}, *rows[1:]])
        err(selection, 'view_changed')
        card_path.write_bytes(raw({**card, 'name': 'new-shop'}))
        err(compare, 'invalid_card_identity_or_skills')
        card_path.write_bytes(raw({**card, 'skills': card['skills'][:2]}))
        err(compare, 'invalid_card_identity_or_skills')
        card_path.write_bytes(raw({**card, 'skills': [*card['skills'][:2], {'id': 'refund', 'description': '변조'}]}))
        err(compare, 'card_changed')
        card_path.write_bytes(original)
        context()
        with patch('os.link', side_effect=OSError('synthetic link failure')):
            err(selection, 'host_input_or_stage_unavailable')
        assert not list(stage_dir.iterdir()) and card_path.read_bytes() == original
        result = invoke(selection)
        assert result['status'] == 'staged', result
        record_path = stage_dir / (result['record_id'] + '.json')
        record_bytes = record_path.read_bytes()
        record = json.loads(record_bytes)
        assert result['record_id'] == sha(record_bytes)
        assert record['before_card_json'].encode('utf-8') == original and record['before_sha256'] == sha(original)
        assert record['after_sha256'] == sha(record['after_card_json'].encode('utf-8'))
        assert record['view_sha256'] == preview['view_sha256']
        assert record['valid_until'] == now + 40 and record['skus'] == ['EGG', 'SOAP']
        after = json.loads(record['after_card_json'])
        assert after['name'] == card['name'] and after['skills'] == card['skills'] and after['x-extra'] == card['x-extra']
        assert old_section not in after['description'] and after['description'].endswith('\n' + policy)
        text = after['description']
        for expected in ('KST 기준', 'SKU EGG · 현재 A등급', 'SKU SOAP · 현재 C등급', '표준 예상 총액 103',
                         '/api/agents', '구매를 명시적으로 결정한 뒤', 'Maroo 실제 가스', '7일', '120초',
                         '기존 마일리지와 함께', '인도 후 48시간', '검증된 원송금인', '연결은 개발 중'):
            assert expected in text, expected
        assert text.index('SKU EGG') < text.index('SKU SOAP')
        assert invoke(selection)['status'] == 'already_staged'
        assert list(stage_dir.iterdir()) == [record_path] and record_path.read_bytes() == record_bytes
        assert card_path.read_bytes() == original
        record_path.write_bytes(b'conflicting synthetic record')
        err(selection, 'stage_record_conflict')
        assert record_path.read_bytes() == b'conflicting synthetic record'
        assert list(stage_dir.iterdir()) == [record_path]
        record_path.write_bytes(record_bytes)
        different = {**selection, 'skus': ['SOAP', 'EGG']}
        with patch('os.link', side_effect=OSError('synthetic link failure')):
            err(different, 'host_input_or_stage_unavailable')
        assert list(stage_dir.iterdir()) == [record_path] and record_path.read_bytes() == record_bytes
        assert card_path.read_bytes() == original
        updated = record['after_card_json'].encode('utf-8')
        card_path.write_bytes(updated)
        managed = after['description'][:-len('\n\n\n' + policy)]
        assert after['description'] == managed + '\n\n\n' + policy
        context(card_sha256=sha(updated), replace_text=managed, observed_at=now)
        refreshed = invoke(compare)
        unchanged = invoke({**selection, 'view_sha256': refreshed['view_sha256']})
        assert unchanged['status'] == 'unchanged', unchanged
        assert list(stage_dir.iterdir()) == [record_path] and card_path.read_bytes() == updated
    return {'ok': True}
