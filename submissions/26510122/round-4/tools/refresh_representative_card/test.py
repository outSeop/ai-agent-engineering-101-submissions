import fcntl
import json
import tempfile
import time
from pathlib import Path


def test(run, kit):
    env = run.__globals__
    saved_root = env['ROOT']
    fixtures = Path('refresh_card_selftest')
    fixtures.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=fixtures) as tmp:
        root = Path(tmp)
        env['ROOT'] = root
        try:
            exercise(run, kit, env, root)
        finally:
            env['ROOT'] = saved_root


def exercise(run, kit, env, root):
    stage = env['stage_module'](root)
    encode, sha = stage['encode'], env['digest']
    host = root / 'host_inputs'
    archive = host / 'card_offer_original'
    pub = root / 'card_publication'
    output = root / 'card_update_stage'
    for folder in (archive, pub, output):
        folder.mkdir(parents=True)
    lock_path = pub / 'lock'
    lock_path.touch()
    head_path = pub / 'head.json'
    card_path = root / 'card.json'
    view_path = host / 'card_offer_context.json'
    now = int(time.time())
    old_stamp = now - 210
    row_a = {'sku': 'G00000001', 'name': '합성 상품 하나', 'category_path': ['생활'], 'state': 'available', 'grade': 'A', 'price_credits': 1000, 'standard_fee_credits': 10, 'valid_until': old_stamp + 150, 'expires_at': now + 600}
    row_b = {**row_a, 'sku': 'G00000002', 'name': '합성 상품 둘', 'grade': 'B'}
    choice = [row_b['sku'], row_a['sku']]
    skills = [{'id': 'checkout', 'description': '구매 확인'}, {'id': 'benefits', 'description': '정산 및 인도 후 1% 적립, 다음 구매부터 7일 동안 사용. 같은 SKU의 120초 대기권은 1%이며 함께 사용 가능.'}, {'id': 'refund', 'description': '증빙을 검토하고 승인된 환불은 원송금 주소로 처리합니다.'}]
    base = {'name': 'outseop-r4', 'description': '상점 소개\n\n이전 판매 예시\n\n구매 안내', 'skills': skills, 'url': 'https://example.test/a2a'}
    base_raw = encode(base)
    original = {'schema': 'outseop-r4.card-offers.v1', 'shop': 'outseop-r4', 'observed_at': old_stamp, 'valid_until': old_stamp + 150, 'card_sha256': sha(base_raw), 'replace_text': '이전 판매 예시', 'offers': [row_a, row_b], 'market': None}
    retained = '\n\n상점 소개\n\n\n\n구매 안내\r\n  끝'
    preserved = {}

    def archive_view(view):
        raw = encode(view)
        path = archive / (sha(raw) + '.json')
        path.write_bytes(raw)
        preserved[path] = raw
        return sha(raw)

    def install_event(value):
        raw = encode(value)
        event_id = sha(raw)
        path = pub / (event_id + '.json')
        path.write_bytes(raw)
        preserved[path] = raw
        head_path.write_bytes(encode({'event': event_id, 'pending': None}))
        card_path.write_bytes(value['after_card_json'].encode('utf-8'))
        return event_id

    def call(view):
        raw = encode(view)
        view_path.write_bytes(raw)
        return run({'view_sha256': sha(raw)}, kit)

    def fresh_view(stamp, card_hash, previous_block):
        deadline = stamp + 150
        return {**original, 'observed_at': stamp, 'valid_until': deadline, 'card_sha256': card_hash, 'replace_text': previous_block, 'offers': [{**row, 'valid_until': deadline} for row in (row_a, row_b)]}

    block = stage['render']([row_b, row_a], old_stamp)
    active_raw = encode({**base, 'description': block + retained})
    first_view_hash = archive_view(original)
    prior = {'schema': 'outseop-r4.card-stage.v1', 'shop': 'outseop-r4', 'skus': choice, 'observed_at': old_stamp, 'valid_until': original['valid_until'], 'view_sha256': first_view_hash, 'before_sha256': sha(base_raw), 'after_sha256': sha(active_raw), 'before_card_json': base_raw.decode('utf-8'), 'after_card_json': active_raw.decode('utf-8')}
    prior_raw = encode(prior)
    prior_id = sha(prior_raw)
    prior_path = output / (prior_id + '.json')
    prior_path.write_bytes(prior_raw)
    preserved[prior_path] = prior_raw
    event = {'schema': 'outseop-r4.card-publication-event.v1', 'shop': 'outseop-r4', 'op': 'apply', 'record_id': prior_id, 'parent': None, 'previous_active': None, 'recorded_at': old_stamp + 1, 'authority_valid_until': old_stamp + 10, 'before_sha256': sha(base_raw), 'after_sha256': sha(active_raw), 'before_card_json': base_raw.decode('utf-8'), 'after_card_json': active_raw.decode('utf-8'), 'skus': choice, 'view_sha256': first_view_hash, 'fresh_view_sha256': first_view_hash, 'offer_until': original['valid_until'], 'block': {'start': 0, 'end': len(block), 'text': block}, 'prior_block': None}
    event_id = install_event(event)
    fresh = fresh_view(now - 21, event['after_sha256'], block)
    assert original['valid_until'] < now < fresh['valid_until']
    fresh_hash = sha(encode(fresh))
    assert run({'view_sha256': fresh_hash, 'skus': list(reversed(choice))}, kit)['error'] == 'invalid_arguments'
    for patch, error in (({'price_credits': 1001}, 'selected_offer_changed'), ({'grade': 'C'}, 'selected_offer_changed'), ({'expires_at': row_a['expires_at'] + 1}, 'selected_offer_changed'), ({'standard_fee_credits': 11}, 'selected_offer_changed'), ({'valid_until': fresh['valid_until'] - 1}, 'ambiguous_row_deadline'), ({'sku': 'G00000003'}, 'selected_sku_not_sellable')):
        changed = call({**fresh, 'offers': [{**fresh['offers'][0], **patch}, fresh['offers'][1]]})
        assert changed.get('error') == error, changed
    assert call(fresh_view(event['recorded_at'], event['after_sha256'], block))['status'] == 'rejected'
    assert call(fresh_view(now + 60, event['after_sha256'], block))['status'] == 'rejected'
    assert call({**fresh, 'valid_until': fresh['observed_at'] + 181})['status'] == 'rejected'
    assert call({**fresh, 'replace_text': block + '\n\n'})['status'] == 'rejected'
    ambiguous = {**original, 'offers': [{**row_a, 'valid_until': original['valid_until'] - 1}, row_b]}
    install_event({**event, 'view_sha256': archive_view(ambiguous)})
    rejected = call(fresh)
    assert rejected.get('error') == 'ambiguous_row_deadline', rejected
    install_event(event)
    original_path = archive / (first_view_hash + '.json')
    original_path.write_bytes(encode(ambiguous))
    try:
        assert call(fresh).get('error') == 'original_view_hash_conflict'
    finally:
        original_path.write_bytes(preserved[original_path])
    with lock_path.open('rb') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert call(fresh).get('error') == 'publisher_busy'

    live_stage_module = env['stage_module']
    stable_head = head_path.read_bytes()

    def concurrent_module(path):
        module = live_stage_module(path)
        original_render = module['render']

        def render(rows, stamp):
            head_path.write_bytes(encode({'event': event_id, 'pending': event_id}))
            return original_render(rows, stamp)

        module['render'] = render
        return module

    env['stage_module'] = concurrent_module
    try:
        rejected = call(fresh)
        assert rejected.get('error') == 'inputs_changed_during_refresh', rejected
    finally:
        env['stage_module'] = live_stage_module
        head_path.write_bytes(stable_head)
    assert list(output.iterdir()) == [prior_path]

    # Use historical fixture observations already within the live clock window.
    # Publish only fabricated events in this temporary directory.
    for step in range(20):
        observed = now - 21 + step
        fresh = fresh_view(observed, event['after_sha256'], block)
        fresh_hash = archive_view(fresh)
        result = call(fresh)
        assert result['status'] == 'staged', result
        assert result['valid_until'] == fresh['valid_until']
        path = output / (result['record_id'] + '.json')
        payload = path.read_bytes()
        preserved[path] = payload
        record = json.loads(payload)
        after = json.loads(record['after_card_json'])
        assert sha(payload) == result['record_id'] and payload == encode(record)
        assert record['skus'] == choice and record['observed_at'] == observed and record['view_sha256'] == fresh_hash
        assert record['before_sha256'] == event['after_sha256'] and sha(record['after_card_json'].encode('utf-8')) == record['after_sha256']
        assert card_path.read_bytes() == event['after_card_json'].encode('utf-8')
        new_block = stage['render'](list(reversed(fresh['offers'])), observed)
        assert after == {**base, 'description': new_block + retained}
        assert after['description'][len(new_block):].encode('utf-8') == retained.encode('utf-8')
        assert len(after['description']) == len(new_block) + len(retained)
        assert len(new_block) == len(block)
        if step == 0:
            again = call(fresh)
            assert again['status'] == 'already_staged' and again['record_id'] == result['record_id'], again
        event = {**event, 'record_id': result['record_id'], 'parent': event_id, 'previous_active': event_id, 'recorded_at': observed, 'authority_valid_until': observed + 10, 'before_sha256': record['before_sha256'], 'after_sha256': record['after_sha256'], 'before_card_json': record['before_card_json'], 'after_card_json': record['after_card_json'], 'view_sha256': fresh_hash, 'fresh_view_sha256': fresh_hash, 'offer_until': result['valid_until'], 'prior_block': event['block'], 'block': {'start': 0, 'end': len(new_block), 'text': new_block}}
        event_id = install_event(event)
        block = new_block

    long_raw = encode({**base, 'description': block + retained + '가' * 1000})
    install_event({**event, 'after_card_json': long_raw.decode('utf-8'), 'after_sha256': sha(long_raw)})
    too_long = call(fresh_view(now - 1, sha(long_raw), block))
    assert too_long.get('error') == 'description_too_long', too_long
    install_event(event)
    fresh = fresh_view(now - 1, event['after_sha256'], block)
    moved = root / 'preserved_stage'
    output.rename(moved)
    try:
        assert call(fresh)['status'] == 'rejected'
    finally:
        moved.rename(output)
    assert len(list(output.iterdir())) == 21
    assert all(path.read_bytes() == raw for path, raw in preserved.items())
    assert card_path.read_bytes() == event['after_card_json'].encode('utf-8')
