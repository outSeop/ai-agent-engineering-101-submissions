import copy
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
    (pub / 'lock').touch()
    card_path = root / 'card.json'
    view_path = host / 'card_offer_context.json'
    old_stamp = int(time.time())
    row_a = {'sku': 'G00000001', 'name': '합성 상품 하나', 'category_path': ['생활'], 'state': 'available', 'grade': 'A', 'price_credits': 1000, 'standard_fee_credits': 10, 'valid_until': old_stamp + 150, 'expires_at': old_stamp + 160}
    row_b = {**row_a, 'sku': 'G00000002', 'name': '합성 상품 둘', 'grade': 'B'}
    choice = [row_b['sku'], row_a['sku']]
    skills = [{'id': 'checkout', 'description': '구매 확인'}, {'id': 'benefits', 'description': '정산 및 인도 후 1% 적립, 다음 구매부터 7일 동안 사용. 같은 SKU의 120초 대기권은 1%이며 함께 사용 가능.'}, {'id': 'refund', 'description': '증빙을 검토하고 승인된 환불은 원송금 주소로 처리합니다.'}]
    initial = {'name': 'outseop-r4', 'description': '소개\n\n이전 판매 예시\n\n구매 안내', 'skills': skills, 'url': 'https://example.test/a2a'}
    initial_raw = encode(initial)
    card_path.write_bytes(initial_raw)
    original = {'schema': 'outseop-r4.card-offers.v1', 'shop': 'outseop-r4', 'observed_at': old_stamp, 'valid_until': old_stamp + 45, 'card_sha256': sha(initial_raw), 'replace_text': '이전 판매 예시', 'offers': [row_a, row_b], 'market': None}
    original_raw = encode(original)
    original_hash = sha(original_raw)
    view_path.write_bytes(original_raw)
    (archive / (original_hash + '.json')).write_bytes(original_raw)
    first = stage['run']({'op': 'stage', 'skus': choice, 'view_sha256': original_hash}, kit)
    assert first['status'] == 'staged', first
    prior_file = output / (first['record_id'] + '.json')
    prior_bytes = prior_file.read_bytes()
    prior = json.loads(prior_bytes)
    active = json.loads(prior['after_card_json'])
    block = stage['render']([row_b, row_a], old_stamp)
    recorded = int(time.time())
    event = {'schema': 'outseop-r4.card-publication-event.v1', 'shop': 'outseop-r4', 'op': 'apply', 'record_id': first['record_id'], 'parent': None, 'previous_active': None, 'recorded_at': recorded, 'authority_valid_until': recorded + 10, 'before_sha256': prior['before_sha256'], 'after_sha256': prior['after_sha256'], 'before_card_json': prior['before_card_json'], 'after_card_json': prior['after_card_json'], 'skus': choice, 'view_sha256': original_hash, 'fresh_view_sha256': original_hash, 'offer_until': original['valid_until'], 'block': {'start': 0, 'end': len(block), 'text': block}, 'prior_block': None}

    def install_event(value):
        raw = encode(value)
        event_id = sha(raw)
        (pub / (event_id + '.json')).write_bytes(raw)
        (pub / 'head.json').write_bytes(encode({'event': event_id, 'pending': None}))
        card_path.write_bytes(value['after_card_json'].encode('utf-8'))

    def call(view):
        raw = encode(view)
        view_path.write_bytes(raw)
        return run({'view_sha256': sha(raw)}, kit)

    install_event(event)
    while int(time.time()) <= recorded:
        time.sleep(0.05)
    observed = int(time.time())
    fresh = {**original, 'observed_at': observed, 'valid_until': observed + 120, 'card_sha256': event['after_sha256'], 'replace_text': block}
    fresh_hash = sha(encode(fresh))
    view_path.write_bytes(encode(fresh))
    unchanged = stage['run']({'op': 'stage', 'skus': choice, 'view_sha256': fresh_hash}, kit)
    assert unchanged['status'] == 'unchanged', unchanged
    result = call(fresh)
    assert result['status'] == 'staged', result
    assert result['valid_until'] == fresh['valid_until']
    saved = output / (result['record_id'] + '.json')
    payload = saved.read_bytes()
    record = json.loads(payload)
    after = json.loads(record['after_card_json'])
    assert sha(payload) == result['record_id'] and payload == encode(record)
    assert record['skus'] == choice and record['observed_at'] == observed and record['view_sha256'] == fresh_hash
    assert record['before_sha256'] == event['after_sha256'] and sha(record['after_card_json'].encode('utf-8')) == record['after_sha256']
    assert after['description'] == stage['render']([row_b, row_a], observed) + '\n\n' + active['description'][len(block):]
    assert {key: value for key, value in after.items() if key != 'description'} == {key: value for key, value in active.items() if key != 'description'}
    again = call(fresh)
    assert again['status'] == 'already_staged' and again['record_id'] == result['record_id'], again
    assert run({'view_sha256': fresh_hash, 'skus': list(reversed(choice))}, kit)['error'] == 'invalid_arguments'
    wrong_hash = run({'view_sha256': original_hash}, kit)
    assert wrong_hash['error'] == 'view_changed', wrong_hash
    for patch in ({'price_credits': 1001}, {'grade': 'C'}, {'expires_at': row_a['expires_at'] + 1}, {'valid_until': row_a['valid_until'] - 1}, {'standard_fee_credits': 11}):
        changed = call({**fresh, 'offers': [{**row_a, **patch}, row_b]})
        assert changed['error'] == 'selected_offer_changed', changed
    for rows in ([{**row_a, 'state': 'reserved'}, row_b], [{**row_a, 'sku': 'G00000003'}, row_b], [{**row_a, 'expires_at': observed}, row_b]):
        rejected = call({**fresh, 'offers': rows})
        assert rejected['status'] == 'rejected', rejected
    assert call({**fresh, 'observed_at': recorded})['error'] == 'new_observation_required'
    assert call({**fresh, 'observed_at': observed - 10, 'valid_until': observed})['status'] == 'rejected'
    assert call({**fresh, 'card_sha256': sha(initial_raw)})['status'] == 'rejected'
    assert call({**fresh, 'replace_text': block + '\n\n'})['status'] == 'rejected'
    bad_card = copy.deepcopy(active)
    bad_card['skills'][2]['description'] = '정책 변조'
    bad_raw = encode(bad_card)
    card_path.write_bytes(bad_raw)
    assert call({**fresh, 'card_sha256': sha(bad_raw)})['error'] == 'active_card_hash_conflict'
    long_raw = encode({**active, 'description': active['description'] + '가' * 1000})
    install_event({**event, 'after_card_json': long_raw.decode('utf-8'), 'after_sha256': sha(long_raw)})
    too_long = call({**fresh, 'card_sha256': sha(long_raw)})
    assert too_long['error'] == 'description_too_long', too_long
    install_event(event)
    moved = root / 'preserved_stage'
    output.rename(moved)
    try:
        failed_write = call(fresh)
        assert failed_write['status'] == 'rejected', failed_write
    finally:
        moved.rename(output)
    assert saved.read_bytes() == payload and prior_file.read_bytes() == prior_bytes
    assert card_path.read_bytes() == event['after_card_json'].encode('utf-8')
    assert (archive / (original_hash + '.json')).read_bytes() == original_raw
    assert sorted(path.name for path in output.iterdir()) == sorted([prior_file.name, saved.name])
