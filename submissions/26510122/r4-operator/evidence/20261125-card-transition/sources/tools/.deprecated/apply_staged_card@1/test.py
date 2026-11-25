import hashlib
import json
import os
import tempfile
import time
from pathlib import Path


def raw(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')


def sha(value):
    return hashlib.sha256(value).hexdigest()


def test(run, kit):
    workspace = Path('card_publication').resolve()
    workspace.mkdir(exist_ok=True)
    globals_ = run.__globals__
    previous_root = globals_['ROOT']
    with tempfile.TemporaryDirectory(dir=workspace) as directory:
        root = Path(directory)
        globals_['ROOT'] = root
        try:
            pub = root / 'card_publication'
            host = root / 'host_inputs'
            original = host / 'card_offer_original'
            fresh = host / 'card_offer_fresh'
            stage_dir = root / 'card_update_stage'
            for path in (pub, original, fresh, stage_dir):
                path.mkdir(parents=True, exist_ok=True)
            (pub / 'lock').touch()
            card_path = root / 'card.json'
            authority_path = host / 'card_publication_authority.json'
            shop = 'outseop-r4'
            policies = {'mileage': '정상 정산·인도 후 1% 마일리지, 7일 이내 다음 거래.', 'wait': '실제 지연 대기권 1%, 120초, 동일 SKU, 마일리지와 병용.', 'refund': '증빙 검토 후 수업 모델이 환불 승인. 송금 연동 개발 중.'}
            old = '기존 예시 상품'
            intro = '안내\n' + policies['mileage'] + '\n'
            outro = '\n' + policies['wait'] + '\n' + policies['refund']
            card = {'name': shop, 'skills': [{'id': 'm'}, {'id': 'w'}, {'id': 'r'}], 'url': 'https://example.invalid/agent', 'description': intro + old + outro}
            before = raw(card)
            card_path.write_bytes(before)
            t = int(time.time())
            rows = [{'sku': 'SKU' + str(i), 'name': '합성 상품', 'category_path': ['합성'], 'state': 'available', 'grade': 'A', 'price_credits': 100, 'standard_fee_credits': 3, 'valid_until': t + 60, 'expires_at': t + 90} for i in range(8)]
            source = {'schema': 'outseop-r4.card-offers.v1', 'shop': shop, 'observed_at': t - 5, 'valid_until': t + 60, 'card_sha256': sha(before), 'replace_text': old, 'offers': rows, 'market': None}
            source_raw = raw(source)
            source_id = sha(source_raw)
            (original / (source_id + '.json')).write_bytes(source_raw)

            def snapshot(offers):
                data = raw(dict(source, observed_at=t, offers=offers))
                view_id = sha(data)
                (fresh / (view_id + '.json')).write_bytes(data)
                return view_id

            good_fresh = snapshot(rows)
            replacement = 'SKU1 · 합성 상품 · A등급 · 100 크레딧\nSKU0 · 합성 상품 · A등급 · 100 크레딧'
            after = raw(dict(card, description=intro + replacement + outro))

            def request_for(candidate, skus):
                data = raw({'schema': 'outseop-r4.card-stage.v1', 'shop': shop, 'skus': skus, 'observed_at': t - 5, 'valid_until': t + 60, 'view_sha256': source_id, 'before_sha256': sha(before), 'after_sha256': sha(candidate), 'before_card_json': before.decode(), 'after_card_json': candidate.decode()})
                record_id = sha(data)
                path = stage_dir / (record_id + '.json')
                path.write_bytes(data)
                os.utime(path, (t - 2, t - 2))
                return {'op': 'apply', 'record_id': record_id}

            def grant(request, candidate, view_id, head=None, current=before):
                details = {'fresh_view_sha256': view_id, 'replacement_sha256': sha(replacement.encode()), 'policies': policies} if request['op'] == 'apply' else {}
                authority_path.write_bytes(raw({'schema': 'outseop-r4.card-publication-authority.v1', 'shop': shop, 'owner': 'native', **request, 'head': head, 'before_sha256': sha(current), 'after_sha256': sha(candidate), 'issued_at': t, 'valid_until': t + 30, 'details': details}))

            request = request_for(after, ['SKU1', 'SKU0'])
            assert run(request, kit)['reason'] == 'required_host_file_missing'
            grant(request, after, good_fresh)
            assert run(dict(request, approved=True), kit)['status'] == 'rejected'
            oversized_description = intro + ('가' * (2007 - len(intro) - len(outro))) + outro
            assert len(oversized_description) == 2007
            oversized = raw(dict(card, description=oversized_description))
            long_request = request_for(oversized, [row['sku'] for row in rows])
            grant(long_request, oversized, good_fresh)
            assert run(long_request, kit)['reason'] == 'description_over_1000'
            grant(request, after, source_id)
            assert run(request, kit)['reason'] == 'independent_fresh_view_required'
            for changes, reason in [({'price_credits': 101}, 'selected_offer_terms_changed'), ({'grade': 'B'}, 'selected_offer_terms_changed'), ({'valid_until': t + 59}, 'selected_offer_terms_changed'), ({'state': 'reserved'}, 'selected_offer_unavailable')]:
                changed = [dict(rows[0], **changes), *rows[1:]]
                grant(request, after, snapshot(changed))
                assert run(request, kit)['reason'] == reason
            policy_before = authority_path.read_bytes()
            grant(request, after, good_fresh)
            approval = json.loads(authority_path.read_bytes())
            approval['details']['policies']['refund'] = old
            authority_path.write_bytes(raw(approval))
            assert run(request, kit)['reason'] == 'protected_policy_overlap_or_change'
            assert card_path.read_bytes() == before
            grant(request, after, good_fresh)
            applied = run(request, kit)
            assert applied['status'] == 'applied', applied
            assert card_path.read_bytes() == after
            event_id = applied['event']
            event_path = pub / (event_id + '.json')
            saved = event_path.read_bytes()
            assert sha(saved) == event_id and json.loads(saved)['skus'] == ['SKU1', 'SKU0']
            assert json.loads(saved)['before_card_json'].encode() == before
            (pub / 'head.json').write_bytes(raw({'event': None, 'pending': event_id}))
            assert run(request, kit)['status'] == 'already_applied'
            assert json.loads((pub / 'head.json').read_bytes()) == {'event': event_id, 'pending': None}
            assert event_path.read_bytes() == saved
            rollback = {'op': 'rollback', 'record_id': event_id}
            grant(rollback, before, good_fresh, head=event_id, current=after)
            card_path.write_bytes(after + b' ')
            assert run(rollback, kit)['reason'] == 'current_card_hash_conflict'
            assert card_path.read_bytes() == after + b' '
            card_path.write_bytes(after)
            assert run(rollback, kit)['status'] == 'rolled_back'
            assert card_path.read_bytes() == before and event_path.read_bytes() == saved
            assert run(rollback, kit)['status'] == 'already_rolled_back'
        finally:
            globals_['ROOT'] = previous_root
