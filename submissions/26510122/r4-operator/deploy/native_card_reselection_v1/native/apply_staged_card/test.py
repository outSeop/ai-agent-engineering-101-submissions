import json
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_APPLY_TEST = 'c96e43d06d9d30a2548d35e59a2628d0552b2a36978fba2b8d67d715d5041e55'
_REFRESH = '7199f31b471ac97275b94e167ba5ec2c7c7aa11bcc8c57a92e128426158dcd53'


def test(run, kit):
    env = run.__globals__
    pin, load, encode, sha = (env[key] for key in ('_pin', '_load', 'encode', 'sha'))
    stage_source = pin('stage_representative_card', 'logic.py', env['_STAGE_SHA'])
    rollback_example = {}

    def observe(args, current_kit):
        if args.get('op') != 'rollback':
            return run(args, current_kit)
        root = env['ROOT']
        card, pub = root / 'card.json', root / 'card_publication'
        before = card.read_bytes()
        authority = json.loads((root / 'host_inputs/card_publication_authority.json').read_bytes())
        event_id = json.loads((pub / 'head.json').read_bytes())['event']
        event_path = pub / (event_id + '.json')
        event = json.loads(event_path.read_bytes())
        result = run(args, current_kit)
        if card.read_bytes() != before:
            rollback_example.update(authority=authority, args=dict(args), event=event, event_id=event_id)
        return result

    regression = load(pin('apply_staged_card', 'test.py', _APPLY_TEST, archived=True))['test']
    env['_v4_observe'] = observe
    exec('def _v4_regression(args, kit):\n    return _v4_observe(args, kit)\n', env)
    try:
        regression(env['_v4_regression'], kit)
    finally:
        del env['_v4_regression'], env['_v4_observe']
    assert rollback_example
    template = rollback_example['authority']
    example = rollback_example['event']
    example_id = rollback_example['event_id']

    def substitute(value, replacements):
        if isinstance(value, dict):
            return {key: substitute(item, replacements) for key, item in value.items()}
        if isinstance(value, list):
            return [substitute(item, replacements) for item in value]
        return replacements.get(value, value) if isinstance(value, str) else value

    def head_for(event_id, event):
        return substitute(template['head'], {example_id: event_id, example['record_id']: event['record_id'], template['before_sha256']: event['after_sha256']})

    def wait_until(second):
        while time.time() < second:
            time.sleep(max(0, second - time.time()))

    workspace = Path('card_publication').resolve()
    workspace.mkdir(exist_ok=True)
    previous_root = env['ROOT']
    with tempfile.TemporaryDirectory(dir=workspace) as directory:
        root = Path(directory)
        try:
            env['ROOT'] = root
            stage = load(stage_source)
            refresh = load(pin('refresh_representative_card', 'logic.py', _REFRESH))
            pub, host, records = root / 'card_publication', root / 'host_inputs', root / 'card_update_stage'
            original, fresh, proofs = (host / name for name in ('card_offer_original', 'card_offer_fresh', 'card_reselection'))
            for path in (pub, original, fresh, proofs, records):
                path.mkdir(mode=0o700, parents=True)
            (pub / 'lock').touch(mode=0o600)
            card_path, context = root / 'card.json', host / 'card_offer_context.json'
            authority_path = host / 'card_publication_authority.json'
            stage.update(ROOT=root, CARD=card_path, CONTEXT=context, STAGE=records)
            refresh.update(ROOT=root, SOURCE=stage_source[0])
            protected = {root / name: ('synthetic ' + name).encode() for name in ('ledger.json', 'wallet.json', 'wholesale.json', 'unrelated.db')}
            for path, value in protected.items():
                path.write_bytes(value)
            policies = dict(mileage='정상 정산·인도 후 상품 기준가의 1%를 적립합니다. 마일리지는 7일 동안 다음 구매부터 사용됩니다.', wait='실제 지연 대기권은 120초 안에 같은 SKU를 구매하면 1% 할인되며 기존 마일리지와 중첩됩니다.', refund='원송금인 증빙이 필요합니다. 48시간 내 모델 검토를 요청하세요. 환불 연동은 아직 완료되지 않았습니다.')
            intro, suffix = 'outseop-r4에 SKU를 알려 주세요.\n\n', '\n\n구매 전 조건을 확인해 주세요.'
            block = '합성 예시 (G00000001) · A등급 · 1,000 크레딧'
            card = dict(name='outseop-r4', url='https://example.invalid/agent', description=intro + block + suffix, skills=[dict(id='a2a-checkout', description='SKU를 알려 주세요.'), dict(id='repeat-benefits', description=policies['mileage'] + ' ' + policies['wait']), dict(id='refund-review', description=policies['refund'])])
            card_path.write_bytes(encode(card))
            now = int(time.time())
            deadline = now + 90
            offer = dict(sku='G00000002', name='합성 상품', category_path=['합성'], state='available', grade='B', price_credits=1250, standard_fee_credits=30, expires_at=deadline)
            other = dict(offer, sku='G00000003', name='다른 합성 상품', grade='C', price_credits=950)
            head = event = event_id = None
            head_history = []

            def store(folder, value):
                raw = encode(value)
                digest = sha(raw)
                (folder / (digest + '.json')).write_bytes(raw)
                return digest

            def pending(authority, proof=None):
                raw = encode(authority)
                authority_path.write_bytes(raw)
                digest = sha(raw)
                path = proofs / (digest + '.json')
                if proof is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(encode(dict(proof, authority_sha256=digest)))
                return dict(op=authority['op'], record_id=authority['record_id'])

            for index in range(5):
                before = card_path.read_bytes()
                before_hash = sha(before)
                observed = now if event is None else event['recorded_at'] + 1
                wait_until(observed)
                until = observed + 40
                if index == 3:
                    offer = dict(offer, grade='A', price_credits=1850)
                row = other if index == 4 else offer
                skus = [row['sku']]
                offers = [dict(item, valid_until=until) for item in (offer, other)]
                view = dict(schema='outseop-r4.card-offers.v1', shop='outseop-r4', observed_at=observed, valid_until=until, card_sha256=before_hash, replace_text=block, offers=offers, market=None)
                context.write_bytes(encode(view))
                view_id = store(original, view)
                paths = set(records.glob('*.json'))
                if index in (1, 2):
                    staged = refresh['run']({'view_sha256': view_id}, kit)
                else:
                    compared = stage['run']({'op': 'compare'}, kit)
                    assert compared.get('view_sha256') == view_id, compared
                    staged = stage['run']({'op': 'stage', 'view_sha256': view_id, 'skus': skus}, kit)
                additions = set(records.glob('*.json')) - paths
                assert len(additions) == 1, (index, staged)
                path = additions.pop()
                staged_raw = path.read_bytes()
                record = json.loads(staged_raw)
                created = path.stat().st_mtime_ns
                fresh_at = max(observed + 1, created // 1_000_000_000 + 1)
                wait_until(fresh_at)
                fresh_view = dict(view, observed_at=fresh_at)
                fresh_id = store(fresh, fresh_view)
                rendered = stage['render']([next(item for item in offers if item['sku'] == row['sku'])], observed)
                issued = int(time.time())
                authority = dict(schema='outseop-r4.card-publication-authority.v1', shop='outseop-r4', owner='native', op='apply', record_id=path.stem, head=head, before_sha256=before_hash, after_sha256=record['after_sha256'], issued_at=issued, valid_until=issued + 25, details=dict(fresh_view_sha256=fresh_id, replacement_sha256=sha(rendered.encode()), policies=policies))
                proof = None
                if index >= 3:
                    proof = dict(schema=env['_MODE_SCHEMA'], mode=env['_MODE'], head_event=event_id, record_id=path.stem, before_sha256=before_hash, after_sha256=record['after_sha256'], stage_source_sha256=env['_STAGE_SHA'], original_view_sha256=view_id, fresh_view_sha256=fresh_id, skus=skus, stage_created_ns=created)
                    head_bytes = (pub / 'head.json').read_bytes()

                    def denied(auth, evidence):
                        result = run(pending(auth, evidence), kit)
                        assert card_path.read_bytes() == before and (pub / 'head.json').read_bytes() == head_bytes, result

                    denied(authority, None)
                    for changes in (dict(mode=True), dict(mode='official'), dict(stage_source_sha256='0' * 64), dict(stage_created_ns=created - 1), dict(head_event=head_history[0]), dict(before_sha256='0' * 64), dict(record_id='0' * 64), dict(skus=skus * 2), dict(wallet='synthetic')):
                        denied(authority, dict(proof, **changes))
                    denied(dict(authority, head=head_for(head_history[0], json.loads((pub / (head_history[0] + '.json')).read_bytes()))), proof)
                    denied(dict(authority, owner='customer'), proof)
                    for changes in (dict(price_credits=row['price_credits'] + 1), dict(grade='B'), dict(state='sold_out'), dict(expires_at=fresh_at), dict(valid_until=until + 1)):
                        altered_id = store(fresh, dict(fresh_view, offers=[dict(item, **changes) if item['sku'] in skus else item for item in offers]))
                        denied(dict(authority, details=dict(authority['details'], fresh_view_sha256=altered_id)), dict(proof, fresh_view_sha256=altered_id))
                    for changes in (dict(offers=offers + [offers[0]]), dict(observed_at=observed), dict(card_sha256='0' * 64), dict(valid_until=fresh_at)):
                        altered_id = store(fresh, dict(fresh_view, **changes))
                        denied(dict(authority, details=dict(authority['details'], fresh_view_sha256=altered_id)), dict(proof, fresh_view_sha256=altered_id))
                    candidate = json.loads(record['after_card_json'])
                    altered_skills = [dict(skill) for skill in candidate['skills']]
                    altered_skills[-1]['description'] = '다른 고객에게 원결제 혜택 이전'
                    for mutation in (dict(skills=altered_skills), dict(description=candidate['description'].replace(rendered, rendered + '\n합성 허위 렌더')), dict(description=rendered + '\n\n' + suffix)):
                        altered_card = encode(dict(candidate, **mutation))
                        after_hash = sha(altered_card)
                        forged_id = store(records, dict(record, after_card_json=altered_card.decode(), after_sha256=after_hash))
                        os.utime(records / (forged_id + '.json'), ns=(created, created))
                        denied(dict(authority, record_id=forged_id, after_sha256=after_hash), dict(proof, record_id=forged_id, after_sha256=after_hash))
                request = pending(authority, proof)
                if index == 4:
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        results = list(pool.map(lambda _: run(request, kit), range(2)))
                else:
                    results = [run(request, kit)]
                after = card_path.read_bytes()
                assert after == record['after_card_json'].encode(), (index, results)
                assert path.read_bytes() == staged_raw
                active = json.loads((pub / 'head.json').read_bytes())
                assert active['pending'] is None
                event_id = active['event']
                head_history.append(event_id)
                event_raw = (pub / (event_id + '.json')).read_bytes()
                assert sha(event_raw) == event_id
                event = json.loads(event_raw)
                assert event['record_id'] == path.stem and event['skus'] == skus and event['view_sha256'] == view_id
                assert event['block'] == dict(start=0, end=len(rendered), text=rendered)
                assert event['prior_block']['text'] == block
                published = json.loads(after)
                assert {key: value for key, value in published.items() if key != 'description'} == {key: value for key, value in card.items() if key != 'description'}
                assert published['description'].endswith(intro + suffix) and len(published['description']) <= 1000
                snapshot = {p.name: p.read_bytes() for p in pub.glob('*.json')}
                run(request, kit)
                assert card_path.read_bytes() == after and {p.name: p.read_bytes() for p in pub.glob('*.json')} == snapshot
                head, block = head_for(event_id, event), rendered

            replacements = {example_id: event_id, example['record_id']: event['record_id'], template['before_sha256']: sha(after), template['after_sha256']: sha(before)}
            rollback = substitute(rollback_example['args'], replacements)
            rollback_authority = substitute(template, replacements)
            issued = int(time.time())
            rollback_authority.update(head=head, before_sha256=sha(after), after_sha256=sha(before), issued_at=issued, valid_until=issued + 25, **rollback)
            assert rollback['op'] == 'rollback'
            conflicting = encode(dict(json.loads(after), description='합성 동시 변경'))
            card_path.write_bytes(conflicting)
            result = run(pending(rollback_authority), kit)
            assert card_path.read_bytes() == conflicting, result
            assert {p.name: p.read_bytes() for p in pub.glob('*.json')} == snapshot
            card_path.write_bytes(after)
            result = run(pending(rollback_authority), kit)
            assert card_path.read_bytes() == before, result
            rollback_snapshot = {p.name: p.read_bytes() for p in pub.glob('*.json')}
            run(rollback, kit)
            assert card_path.read_bytes() == before and {p.name: p.read_bytes() for p in pub.glob('*.json')} == rollback_snapshot
            assert all(path.read_bytes() == value for path, value in protected.items())
        finally:
            env['ROOT'] = previous_root
