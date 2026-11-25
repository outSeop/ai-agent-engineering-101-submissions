import json
import os
import tempfile
import time
from pathlib import Path

_APPLY_TEST = 'c96e43d06d9d30a2548d35e59a2628d0552b2a36978fba2b8d67d715d5041e55'
_GUARD = 'cb3c5a6e5c6ca36fb329e4b2279c2b718a304386665707ecaf9a7e21eb887dc2'
_REFRESH = '7199f31b471ac97275b94e167ba5ec2c7c7aa11bcc8c57a92e128426158dcd53'


def test(run, kit):
    env = run.__globals__
    pin, load = env['_pin'], env['_load']
    encode, sha = env['encode'], env['sha']
    stage_source = pin('stage_representative_card', 'logic.py', env['_STAGE_SHA'])
    rollback_example = {}

    def events(pub):
        result = {}
        for path in pub.glob('*.json'):
            raw = path.read_bytes()
            if path.stem == sha(raw):
                event = json.loads(raw)
                if 'prior_block' in event and 'record_id' in event:
                    result[path.stem] = event
        return result

    def observe(args, current_kit):
        if args.get('op') != 'rollback':
            return run(args, current_kit)
        root = env['ROOT']
        card = root / 'card.json'
        before = card.read_bytes()
        authority = json.loads((root / 'host_inputs/card_publication_authority.json').read_bytes())
        prior = events(root / 'card_publication')
        result = run(args, current_kit)
        if card.read_bytes() != before:
            rollback_example.update(authority=authority, request=dict(args), events=prior)
        return result

    regression = load(pin('apply_staged_card', 'test.py', _APPLY_TEST, archived=True))['test']
    env['_v3_observe'] = observe
    exec('def _v3_regression(args, kit):\n    return _v3_observe(args, kit)\n', env)
    try:
        regression(env['_v3_regression'], kit)
    finally:
        del env['_v3_regression'], env['_v3_observe']
    assert rollback_example
    template = rollback_example['authority']
    matches = [(key, event) for key, event in rollback_example['events'].items() if event['after_sha256'] == template['before_sha256']]
    assert len(matches) == 1, matches
    example_id, example_event = matches[0]

    def substitute(value, replacements):
        if isinstance(value, dict):
            return {key: substitute(item, replacements) for key, item in value.items()}
        if isinstance(value, list):
            return [substitute(item, replacements) for item in value]
        return replacements.get(value, value) if isinstance(value, str) else value

    def head_for(event_id, event):
        return substitute(template['head'], {example_id: event_id, example_event['record_id']: event['record_id'], template['before_sha256']: event['after_sha256']})

    workspace = Path('card_publication').resolve()
    workspace.mkdir(exist_ok=True)
    original_root = env['ROOT']
    with tempfile.TemporaryDirectory(dir=workspace) as directory:
        root = Path(directory)
        try:
            env['ROOT'] = root
            stage = load(stage_source)
            refresh = load(pin('refresh_representative_card', 'logic.py', _REFRESH))
            guard = load(pin('publish_shop_info', 'logic.py', _GUARD))
            pub, host, stage_dir = root / 'card_publication', root / 'host_inputs', root / 'card_update_stage'
            original, fresh = host / 'card_offer_original', host / 'card_offer_fresh'
            for path in (pub, original, fresh, stage_dir):
                path.mkdir(mode=0o700, parents=True)
            (pub / 'lock').touch(mode=0o600)
            card_path = root / 'card.json'
            context = host / 'card_offer_context.json'
            authority_path = host / 'card_publication_authority.json'
            stage.update(ROOT=root, CARD=card_path, CONTEXT=context, STAGE=stage_dir)
            refresh.update(ROOT=root, SOURCE=stage_source[0])
            guard['ROOT'] = root
            intro = 'outseop-r4에 처음 연락할 때 상품명이나 SKU를 알려 주세요.\n\n'
            legacy = '2026-11-25 10:00 KST 확인 재고\n합성상품 (G00000001) · A등급 · 1,000 크레딧'
            suffix = '\n\n구매 전 재고·등급·가격과 별도 시장 수수료를 확인해 주세요.'
            policies = dict(mileage='정상 정산·인도 후 상품 기준가의 1%를 적립합니다. 마일리지는 7일 동안 다음 구매부터 사용됩니다.', wait='실제 앞선 결제로 발급된 대기권은 120초 안에 같은 상품을 다시 문의해 구매할 때 기준가의 1%를 할인합니다.', refund='원결제 증빙이 필요하며 승인 후 원송금 주소로 처리합니다.')
            card = dict(name='outseop-r4', url='https://example.invalid/agent', description=intro + legacy + suffix, skills=[
                dict(id='a2a-checkout', name='상품·등급 확인과 구매', description='원하는 상품명 또는 SKU를 A2A에 보내세요.', tags=['inventory'], examples=['현재 가격을 알려주세요.']),
                dict(id='repeat-benefits', name='대기할인 및 마일리지', description=policies['mileage'] + ' ' + policies['wait'], tags=['mileage'], examples=['마일리지를 확인해 주세요.']),
                dict(id='refund-review', name='증빙 기반 환불 검토', description=policies['refund'], tags=['refund'], examples=['환불 검토를 요청합니다.']),
            ])
            card_path.write_bytes(encode(card))
            initial = int(time.time())
            product_expiry = initial + 120
            row = dict(sku='G00000002', name='합성상품', category_path=['합성'], state='available', grade='B', price_credits=1250, standard_fee_credits=30, expires_at=product_expiry)
            skus = [row['sku']]
            retained = '\n\n' + intro + suffix
            event = event_id = prior_view = None
            block = legacy
            expected_length = None
            for iteration in range(5):
                before = card_path.read_bytes()
                if iteration == 0:
                    observed, until = initial - 2, initial + 6
                else:
                    observed = max(event['recorded_at'] + 1, prior_view['observed_at'] + 1)
                    if iteration == 1:
                        observed = max(observed, prior_view['valid_until'])
                    time.sleep(max(0, observed - time.time()))
                    until = observed + 45
                view = dict(schema='outseop-r4.card-offers.v1', shop=card['name'], observed_at=observed, valid_until=until, card_sha256=sha(before), replace_text=block, offers=[dict(row, valid_until=until)], market=None)
                raw_view = encode(view)
                view_id = sha(raw_view)
                context.write_bytes(raw_view)
                (original / (view_id + '.json')).write_bytes(raw_view)
                old_files = set(stage_dir.glob('*.json'))
                if iteration == 0:
                    staged = stage['run'](dict(op='stage', skus=skus, view_sha256=view_id), kit)
                else:
                    staged = refresh['run'](dict(view_sha256=view_id), kit)
                additions = set(stage_dir.glob('*.json')) - old_files
                assert len(additions) == 1, (iteration, staged)
                path = additions.pop()
                raw = path.read_bytes()
                record = json.loads(raw)
                assert path.stem == sha(raw)
                new_block = stage['render'](view['offers'], observed)
                candidate = json.loads(record['after_card_json'])
                description = new_block + retained
                assert candidate == dict(card, description=description)
                if expected_length is None:
                    expected_length = len(description)
                assert len(description) == expected_length <= 1000
                mtime = path.stat().st_mtime_ns
                fresh_at = max(observed + 1, (mtime + 999_999_999) // 1_000_000_000)
                time.sleep(max(0, fresh_at - time.time()))
                fresh_raw = encode(dict(view, observed_at=fresh_at))
                fresh_id = sha(fresh_raw)
                (fresh / (fresh_id + '.json')).write_bytes(fresh_raw)
                head = None if event is None else head_for(event_id, event)

                def apply(record_id, after_hash, replacement, expired=False, fresh_hash=None):
                    now = int(time.time())
                    request = dict(op='apply', record_id=record_id)
                    authority = dict(schema='outseop-r4.card-publication-authority.v1', shop=card['name'], owner='native', head=head, before_sha256=sha(before), after_sha256=after_hash, issued_at=now - 25 if expired else now, valid_until=now if expired else now + 25, details=dict(fresh_view_sha256=fresh_id if fresh_hash is None else fresh_hash, replacement_sha256=sha(replacement.encode('utf-8')), policies=policies), **request)
                    authority_path.write_bytes(encode(authority))
                    return run(request, kit)

                if iteration < 2:
                    altered_skills = [dict(skill) for skill in card['skills']]
                    altered_skills[-1]['description'] = '변조된 환불 정책'
                    false_block = new_block + '\n환불 자동 완료'
                    for altered, replacement in (
                        (dict(candidate, skills=altered_skills), new_block),
                        (dict(candidate, description=new_block + '\n\n' + suffix), new_block),
                        (dict(candidate, description=false_block + retained), false_block),
                        (dict(candidate, description=new_block + '\n\n' + retained), new_block),
                    ):
                        bad_card = encode(altered)
                        bad_hash = sha(bad_card)
                        bad_raw = encode(dict(record, after_card_json=bad_card.decode('utf-8'), after_sha256=bad_hash))
                        bad_path = stage_dir / (sha(bad_raw) + '.json')
                        bad_path.write_bytes(bad_raw)
                        os.utime(bad_path, ns=(mtime, mtime))
                        result = apply(bad_path.stem, bad_hash, replacement)
                        assert card_path.read_bytes() == before, result
                    for changes in (dict(expires_at=product_expiry + 1), dict(price_credits=1251), dict(grade='A'), dict(state='reserved'), dict(valid_until=until + 1)):
                        changed = dict(view['offers'][0], **changes)
                        bad_fresh = encode(dict(view, observed_at=fresh_at, offers=[changed]))
                        bad_id = sha(bad_fresh)
                        (fresh / (bad_id + '.json')).write_bytes(bad_fresh)
                        result = apply(path.stem, record['after_sha256'], new_block, fresh_hash=bad_id)
                        assert card_path.read_bytes() == before, result
                    result = apply(path.stem, record['after_sha256'], new_block, expired=True)
                    assert card_path.read_bytes() == before, result

                prior_ids = set(events(pub))
                result = apply(path.stem, record['after_sha256'], new_block)
                after = card_path.read_bytes()
                assert after == record['after_card_json'].encode('utf-8'), (iteration, result)
                assert path.read_bytes() == raw
                committed = events(pub)
                new_ids = set(committed) - prior_ids
                assert len(new_ids) == 1, result
                event_id = new_ids.pop()
                event = committed[event_id]
                prior_start = len(intro) if iteration == 0 else 0
                assert event['block'] == dict(start=0, end=len(new_block), text=new_block)
                assert event['prior_block'] == dict(start=prior_start, end=prior_start + len(block), text=block)
                assert event['view_sha256'] == view_id
                issued = max(int(time.time()), event['recorded_at'])
                handoff = dict(schema='outseop-r4.card-publication-handoff.v1', shop=card['name'], owner='native', event=event_id, card_sha256=sha(after), issued_at=issued, valid_until=issued + 30)
                (host / 'card_publication_handoff.json').write_bytes(encode(handoff))
                guarded = guard['run']({}, kit)
                assert guarded.get('status') == 'skipped', guarded
                run(dict(op='apply', record_id=path.stem), kit)
                assert card_path.read_bytes() == after and events(pub) == committed
                prior_view, block = view, new_block

            replacements = {example_id: event_id, example_event['record_id']: event['record_id'], template['before_sha256']: sha(after), template['after_sha256']: sha(before)}
            rollback = substitute(rollback_example['request'], replacements)
            authority = substitute(template, replacements)
            now = int(time.time())
            authority.update(issued_at=now, valid_until=now + 25, head=head_for(event_id, event), before_sha256=sha(after), after_sha256=sha(before), **rollback)
            authority_path.write_bytes(encode(authority))
            result = run(rollback, kit)
            assert card_path.read_bytes() == before, result
            committed = events(pub)
            run(rollback, kit)
            assert card_path.read_bytes() == before and events(pub) == committed
        finally:
            env['ROOT'] = original_root
