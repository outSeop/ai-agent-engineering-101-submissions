'''Stage a refresh from host-protected observations and a settled publication.
The host supplies the permanent publication lock, current card, immutable event
and original view, and a producer observation linked to the current card.
The host retains the new observation under its raw SHA256 for separate apply.
'''
import fcntl
import hashlib
import json
import re
import time
from pathlib import Path

ROOT = Path('.')
SOURCE = Path('tools/stage_representative_card/logic.py')
SOURCE_SHA = 'e883b594583e1abf8587a963154d58020a0f0e214451dee1fa3c771d11514fbb'
SHOP = 'outseop-r4'
MAX_BYTES = 24 * 1024 * 1024
VIEW_SCHEMA = 'outseop-r4.card-offers.v1'
EVENT_KEYS = set('schema shop op record_id parent previous_active recorded_at authority_valid_until before_sha256 after_sha256 before_card_json after_card_json skus view_sha256 fresh_view_sha256 offer_until block prior_block'.split())


class Rejected(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise Rejected(reason)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def is_hash(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def read(path, limit=MAX_BYTES):
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    require(len(raw) <= limit, 'publication_input_too_large')
    return raw


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, 'duplicate_publication_key')
        result[key] = value
    return result


def invalid_constant(value):
    raise Rejected('invalid_publication_number')


def decode(raw):
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=invalid_constant)
    require(isinstance(value, dict), 'invalid_publication_object')
    return value


def stage_module(root):
    source = read(SOURCE, 64 * 1024)
    require(digest(source) == SOURCE_SHA, 'stage_dependency_hash_mismatch')
    module = {'__name__': '_pinned_stage_v1', '__file__': str(SOURCE)}
    exec(compile(source, str(SOURCE), 'exec'), module)
    module.update(ROOT=root, CARD=root / 'card.json', CONTEXT=root / 'host_inputs/card_offer_context.json', STAGE=root / 'card_update_stage')
    return module


def active_publication(root):
    pub = root / 'card_publication'
    head_raw = read(pub / 'head.json')
    head = decode(head_raw)
    require(head.keys() == {'event', 'pending'} and head['pending'] is None and is_hash(head['event']), 'active_publication_required')
    event_path = pub / (head['event'] + '.json')
    event_raw = read(event_path)
    require(digest(event_raw) == head['event'], 'active_event_hash_conflict')
    event = decode(event_raw)
    require(event.keys() == EVENT_KEYS and event['schema'] == 'outseop-r4.card-publication-event.v1' and event['shop'] == SHOP and event['op'] in ('apply', 'rollback'), 'invalid_active_event')
    recorded, deadline = event['recorded_at'], event['offer_until']
    require(type(recorded) is int and type(deadline) is int and 0 <= recorded < deadline, 'active_offer_event_required')
    require(is_hash(event['view_sha256']) and is_hash(event['after_sha256']), 'invalid_active_event_hashes')
    return head_raw, event_path, event_raw, event


def observation_window(view):
    observed = view.get('observed_at')
    deadline = view.get('valid_until')
    require(type(observed) is int and type(deadline) is int and observed >= 0 and 0 < deadline - observed <= 180, 'invalid_observation_window')
    return observed, deadline


def compare_offer(old_row, new_row, old_deadline, new_deadline, encode):
    old_ttl = old_row.get('valid_until')
    new_ttl = new_row.get('valid_until')
    require(type(old_ttl) is int and old_ttl == old_deadline and type(new_ttl) is int and new_ttl == new_deadline, 'ambiguous_row_deadline')
    # Compare canonical bytes so JSON booleans and numbers remain distinct.
    require(encode({**old_row, 'valid_until': new_ttl}) == encode(new_row), 'selected_offer_changed')


def refresh(root, args, stage):
    require(isinstance(args, dict) and args.keys() == {'view_sha256'} and is_hash(args['view_sha256']), 'invalid_arguments')
    head_raw, event_path, event_raw, event = active_publication(root)
    now = int(time.time())
    card_raw, view_raw, card, view, offers = stage['load'](now)
    view_hash = digest(view_raw)
    require(view_hash == args['view_sha256'], 'view_changed')
    after_text = event['after_card_json']
    require(isinstance(after_text, str) and after_text.encode('utf-8') == card_raw and digest(card_raw) == event['after_sha256'], 'active_card_hash_conflict')
    skus = event['skus']
    require(isinstance(skus, list) and 1 <= len(skus) <= 3 and all(stage['sku_ok'](sku) for sku in skus) and len(set(skus)) == len(skus), 'invalid_active_selection')
    archive = root / 'host_inputs/card_offer_original' / (event['view_sha256'] + '.json')
    old_raw = read(archive)
    require(digest(old_raw) == event['view_sha256'], 'original_view_hash_conflict')
    old_view = decode(old_raw)
    require(old_view.get('schema') == VIEW_SCHEMA and old_view.get('shop') == SHOP and isinstance(old_view.get('offers'), list), 'invalid_original_view')
    if event['op'] == 'apply':
        require(old_view.get('card_sha256') == event['before_sha256'], 'original_view_card_conflict')
    old_observed, old_deadline = observation_window(old_view)
    observed, new_deadline = observation_window(view)
    require(old_observed <= event['recorded_at'] < observed <= now < new_deadline, 'new_observation_required')
    require(event['offer_until'] <= old_deadline, 'original_event_deadline_conflict')
    require(new_deadline > old_deadline, 'cache_deadline_not_advanced')
    old_rows = {}
    for row in old_view['offers']:
        require(isinstance(row, dict) and stage['sku_ok'](row.get('sku')) and row['sku'] not in old_rows, 'invalid_original_offer')
        old_rows[row['sku']] = row
    previous = []
    chosen = []
    for sku in skus:
        row = offers.get(sku)
        require(row is not None and row['state'] == 'available' and now < stage['expiry'](row, view), 'selected_sku_not_sellable')
        require(sku in old_rows, 'selected_offer_changed')
        old_row = old_rows[sku]
        compare_offer(old_row, row, old_deadline, new_deadline, stage['encode'])
        previous.append(old_row)
        chosen.append(row)
    before_section = view['replace_text']
    block = event['block']
    description = card['description']
    require(isinstance(block, dict) and isinstance(before_section, str) and before_section and block.get('text') == before_section, 'active_offer_span_conflict')
    start, end = block.get('start'), block.get('end')
    require(type(start) is int and type(end) is int and 0 <= start < end <= len(description) and description[start:end] == before_section and description.count(before_section) == 1, 'active_offer_span_conflict')
    require(stage['render'](previous, old_observed) == before_section, 'active_offer_render_conflict')
    require(card['name'] == SHOP and isinstance(card['skills'], list) and len(card['skills']) == 3 and all(isinstance(skill, dict) for skill in card['skills']), 'invalid_card_identity_or_skills')
    new_section = stage['render'](chosen, observed)
    after_description = description[:start] + new_section + description[end:]
    require(len(after_description) <= 1000, 'description_too_long')
    require(after_description.count(new_section) == 1, 'new_offer_span_ambiguous')
    after_raw = stage['encode']({**card, 'description': after_description})
    deadline = min(new_deadline, *(stage['expiry'](row, view) for row in chosen))
    record = {'schema': 'outseop-r4.card-stage.v1', 'shop': SHOP, 'skus': skus, 'observed_at': observed, 'valid_until': deadline, 'view_sha256': view_hash, 'before_sha256': digest(card_raw), 'after_sha256': digest(after_raw), 'before_card_json': card_raw.decode('utf-8'), 'after_card_json': after_raw.decode('utf-8')}
    payload = stage['encode'](record)
    record_id = digest(payload)
    require(stage['read_raw'](stage['CARD']) == card_raw and stage['read_raw'](stage['CONTEXT']) == view_raw and read(archive) == old_raw and read(event_path) == event_raw and read(root / 'card_publication/head.json') == head_raw, 'inputs_changed_during_refresh')
    require(int(time.time()) < deadline, 'selection_expired_during_refresh')
    created = stage['record_once'](record_id, payload)
    return {'status': 'staged' if created else 'already_staged', 'record_id': record_id, 'view_sha256': view_hash, 'observed_at': observed, 'valid_until': deadline}


def run(args, kit):
    try:
        stage = stage_module(ROOT)
        with (ROOT / 'card_publication/lock').open('rb') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                return {'status': 'rejected', 'error': 'publisher_busy'}
            try:
                return refresh(ROOT, args, stage)
            except stage['Invalid'] as exc:
                return {'status': 'rejected', 'error': str(exc)}
    except Rejected as exc:
        return {'status': 'rejected', 'error': str(exc)}
    except (OSError, KeyError, TypeError, OverflowError, UnicodeError, ValueError, RecursionError):
        return {'status': 'rejected', 'error': 'host_input_or_stage_unavailable'}
