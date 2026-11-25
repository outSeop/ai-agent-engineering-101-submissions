import json
import os
import tempfile
import time
from pathlib import Path

_APPLY_TEST_SHA = 'c96e43d06d9d30a2548d35e59a2628d0552b2a36978fba2b8d67d715d5041e55'
_GUARD_LOGIC_SHA = 'cb3c5a6e5c6ca36fb329e4b2279c2b718a304386665707ecaf9a7e21eb887dc2'


def test(run, kit):
    env = run.__globals__
    pin = env['_pinned_source']
    load = env['_pinned_namespace']
    encode, sha = env['encode'], env['sha']
    load(pin('apply_staged_card', 'test.py', _APPLY_TEST_SHA, archived=True))['test'](run, kit)
    stage_source = pin('stage_representative_card', 'logic.py', env['_STAGE_LOGIC_SHA'])
    guard_source = pin('publish_shop_info', 'logic.py', _GUARD_LOGIC_SHA)
    workspace = Path('card_publication').resolve()
    workspace.mkdir(exist_ok=True)
    previous_root, previous_cwd = env['ROOT'], Path.cwd()
    with tempfile.TemporaryDirectory(dir=workspace) as directory:
        root = Path(directory)
        env['ROOT'] = root
        try:
            os.chdir(root)
            stage = load(stage_source)
            if 'ROOT' in stage:
                stage['ROOT'] = root
            guard = load(guard_source)
            guard['ROOT'] = root
            pub = root / 'card_publication'
            host = root / 'host_inputs'
            original = host / 'card_offer_original'
            fresh = host / 'card_offer_fresh'
            stage_dir = root / 'card_update_stage'
            for path in (pub, original, fresh, stage_dir):
                path.mkdir(parents=True, exist_ok=True)
            (pub / 'lock').touch()
            card_path = root / 'card.json'
            intro = 'outseop-r4에 처음 연락할 때 원하는 상품명이나 SKU와 필요한 조건을 알려 주세요. 재방문 시 비공개 권리코드로 누적 혜택을 확인할 수 있습니다.\n\n'
            old_block = '2026-11-25 10:00 KST 확인 재고\n합성상품 (G00000001) · A등급 · 1,000 크레딧'
            suffix = '\n\n표시는 조사 시점 기준입니다. 구매 전 A2A에서 재고·현재 등급·가격과 별도 시장 수수료·가스 조건을 확인해 주세요.'
            policies = {
                'mileage': '정상 정산·인도 후 상품 기준가의 1%를 적립합니다. 마일리지는 7일 동안 다음 구매부터 사용됩니다.',
                'wait': '실제 앞선 결제로 발급된 대기권은 120초 안에 같은 상품을 다시 문의해 구매할 때 기준가의 1%를 할인합니다.',
                'refund': '원결제 증빙이 필요하며 승인 후 원송금 주소로 처리합니다.',
            }
            card = {
                'name': 'outseop-r4',
                'url': 'https://example.invalid/agent',
                'description': intro + old_block + suffix,
                'skills': [
                    {'id': 'a2a-checkout', 'name': '상품·등급 확인과 구매', 'description': '원하는 상품명 또는 SKU와 가격·등급 조건을 A2A에 보내세요. 구매를 결정하면 서명된 결제권을 받을 수 있습니다.', 'tags': ['inventory', 'checkout'], 'examples': ['키친타올 걸이의 현재 등급과 가격을 알려주세요.']},
                    {'id': 'repeat-benefits', 'name': '대기할인 및 재방문 마일리지', 'description': policies['mileage'] + ' ' + policies['wait'] + ' 유효한 기존 마일리지와 대기할인은 조건을 충족하면 함께 사용할 수 있습니다. 대기권이 재고 확보나 자동 알림을 보장하지 않습니다.', 'tags': ['mileage', 'wait-voucher'], 'examples': ['보유 마일리지와 대기할인을 함께 쓸 수 있나요?']},
                    {'id': 'refund-review', 'name': '증빙 기반 환불 검토', 'description': '인도 후 48시간 내 증빙이 확인된 초기 문제나 확인된 판매자 귀책 미인도는 운영자가 환불을 검토합니다. ' + policies['refund'], 'tags': ['warranty', 'refund'], 'examples': ['원결제 증빙으로 환불 검토를 요청합니다.']},
                ],
            }
            before = encode(card)
            card_path.write_bytes(before)
            t = int(time.time())
            rows = [dict(sku='G00000002', name='합성상품', category_path=['합성'], state='available', grade='B', price_credits=1250, standard_fee_credits=30, valid_until=t + 100, expires_at=t + 90)]
            view = dict(schema='outseop-r4.card-offers.v1', shop=card['name'], observed_at=t - 5, valid_until=t + 80, card_sha256=sha(before), replace_text=old_block, offers=rows, market=None)
            view_bytes = encode(view)
            view_id = sha(view_bytes)
            (host / 'card_offer_context.json').write_bytes(view_bytes)
            (original / (view_id + '.json')).write_bytes(view_bytes)
            staged = stage['run']({'op': 'stage', 'skus': [rows[0]['sku']], 'view_sha256': view_id}, kit)
            paths = list(stage_dir.glob('*.json'))
            assert len(paths) == 1, staged
            stage_path = paths[0]
            record_bytes = stage_path.read_bytes()
            record = json.loads(record_bytes)
            assert stage_path.stem == sha(record_bytes)
            candidate = json.loads(record['after_card_json'])
            block = stage['render'](rows, view['observed_at'])
            assert candidate == dict(card, description=block + '\n\n' + intro + suffix)
            assert len(candidate['description']) <= 1000
            timestamp = stage_path.stat().st_mtime_ns
            fresh_at = max(view['observed_at'] + 1, (timestamp + 999_999_999) // 1_000_000_000)
            time.sleep(max(0, fresh_at - time.time()))
            fresh_bytes = encode(dict(view, observed_at=fresh_at))
            fresh_id = sha(fresh_bytes)
            (fresh / (fresh_id + '.json')).write_bytes(fresh_bytes)

            def grant_and_call(record_id, after_hash, replacement):
                request = {'op': 'apply', 'record_id': record_id}
                now = int(time.time())
                authority = dict(schema='outseop-r4.card-publication-authority.v1', shop=card['name'], owner='native', head=None, before_sha256=sha(before), after_sha256=after_hash, issued_at=now, valid_until=now + 25, details=dict(fresh_view_sha256=fresh_id, replacement_sha256=sha(replacement.encode('utf-8')), policies=policies), **request)
                (host / 'card_publication_authority.json').write_bytes(encode(authority))
                return run(request, kit)

            changed_skills = [dict(skill) for skill in candidate['skills']]
            changed_skills[2]['description'] = '합성 변조'
            fake_block = block + '\n환불 자동 완료'
            tampered_cards = [
                (dict(candidate, skills=changed_skills), block),
                (dict(candidate, description=block + '\n\n' + suffix), block),
                (dict(candidate, description=fake_block + '\n\n' + intro + suffix), fake_block),
            ]
            for tampered, replacement in tampered_cards:
                tampered_bytes = encode(tampered)
                tampered_hash = sha(tampered_bytes)
                bad_record = encode(dict(record, after_card_json=tampered_bytes.decode('utf-8'), after_sha256=tampered_hash))
                bad_id = sha(bad_record)
                bad_path = stage_dir / (bad_id + '.json')
                bad_path.write_bytes(bad_record)
                os.utime(bad_path, ns=(timestamp, timestamp))
                result = grant_and_call(bad_id, tampered_hash, replacement)
                assert result.get('reason') not in (None, 'fresh_view_must_follow_stage'), result
                assert card_path.read_bytes() == before

            applied = grant_and_call(stage_path.stem, record['after_sha256'], block)
            after = card_path.read_bytes()
            assert after == record['after_card_json'].encode('utf-8'), applied
            assert stage_path.read_bytes() == record_bytes
            assert (original / (view_id + '.json')).read_bytes() == view_bytes
            events = {}
            for path in pub.rglob('*.json'):
                data = path.read_bytes()
                event = json.loads(data)
                if isinstance(event, dict) and event.get('record_id') == stage_path.stem and 'prior_block' in event and path.stem == sha(data):
                    events[path.stem] = event
            assert len(events) == 1, applied
            event_id, event = next(iter(events.items()))
            assert event['block'] == {'start': 0, 'end': len(block), 'text': block}
            assert event['prior_block'] == {'start': len(intro), 'end': len(intro) + len(old_block), 'text': old_block}
            handoff_time = max(int(time.time()), event['recorded_at'])
            handoff = dict(schema='outseop-r4.card-publication-handoff.v1', shop=card['name'], owner='native', event=event_id, card_sha256=sha(after), issued_at=handoff_time, valid_until=handoff_time + 30)
            (host / 'card_publication_handoff.json').write_bytes(encode(handoff))
            guarded = guard['run']({}, kit)
            assert guarded['status'] == 'skipped', guarded
            assert card_path.read_bytes() == after
        finally:
            os.chdir(previous_cwd)
            env['ROOT'] = previous_root
