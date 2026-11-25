'''Use protected host paths under the agent working directory. Keep the pinned tools/stage_representative_card/logic.py and the permanent card_publication/lock inode. Supply a settled head.json, its content-addressed event, current card.json, the event's exact original view in host_inputs/card_offer_original/<view_sha256>.json, and a newly produced host_inputs/card_offer_context.json. Bind the new context to the current card hash and set replace_text to the event's complete rendered block. Its observed_at must be later than the event and its original observation. Keep the selected offer rows unchanged, including per-row deadlines. Context-level freshness can advance. Preserve the exact new context bytes under their own original-view hash for apply. After the stage exists, the producer must read inventory again for the separate apply fresh view. Only the host supplies those facts and any apply authority. The fixture directory is used by the forge test.'''
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
    return head_raw, event


def refresh(root, args, stage):
    require(isinstance(args, dict) and args.keys() == {'view_sha256'} and is_hash(args['view_sha256']), 'invalid_arguments')
    head_raw, event = active_publication(root)
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
    require(old_view.get('schema') == 'outseop-r4.card-offers.v1' and old_view.get('shop') == SHOP and isinstance(old_view.get('offers'), list), 'invalid_original_view')
    if event['op'] == 'apply':
        require(old_view.get('card_sha256') == event['before_sha256'], 'original_view_card_conflict')
    old_observed = old_view.get('observed_at')
    require(type(old_observed) is int and 0 <= old_observed <= event['recorded_at'] < view['observed_at'], 'new_observation_required')
    old_rows = {}
    for row in old_view['offers']:
        require(isinstance(row, dict) and stage['sku_ok'](row.get('sku')) and row['sku'] not in old_rows, 'invalid_original_offer')
        old_rows[row['sku']] = row
    chosen = []
    for sku in skus:
        row = offers.get(sku)
        require(row is not None and row['state'] == 'available' and now < stage['expiry'](row, view), 'selected_sku_not_sellable')
        require(sku in old_rows and row == old_rows[sku], 'selected_offer_changed')
        chosen.append(row)
    before_section = view['replace_text']
    block = event['block']
    description = card['description']
    require(isinstance(block, dict) and block.get('text') == before_section and description.startswith(before_section) and description.count(before_section) == 1, 'active_offer_span_conflict')
    require(block.get('start', 0) == 0 and block.get('end', len(before_section)) == len(before_section), 'active_offer_span_conflict')
    require(stage['render'](chosen, old_observed) == before_section, 'active_offer_render_conflict')
    require(card['name'] == SHOP and isinstance(card['skills'], list) and len(card['skills']) == 3 and all(isinstance(skill, dict) for skill in card['skills']), 'invalid_card_identity_or_skills')
    new_section = stage['render'](chosen, view['observed_at'])
    retained = description[len(before_section):]
    after_description = new_section + ('\n\n' + retained if retained else '')
    require(len(after_description) <= 1000, 'description_too_long')
    after_raw = stage['encode']({**card, 'description': after_description})
    deadline = min(stage['expiry'](row, view) for row in chosen)
    record = {'schema': 'outseop-r4.card-stage.v1', 'shop': SHOP, 'skus': skus, 'observed_at': view['observed_at'], 'valid_until': deadline, 'view_sha256': view_hash, 'before_sha256': digest(card_raw), 'after_sha256': digest(after_raw), 'before_card_json': card_raw.decode('utf-8'), 'after_card_json': after_raw.decode('utf-8')}
    payload = stage['encode'](record)
    record_id = digest(payload)
    require(read(root / 'card_publication/head.json') == head_raw and stage['read_raw'](stage['CARD']) == card_raw and stage['read_raw'](stage['CONTEXT']) == view_raw and read(archive) == old_raw, 'inputs_changed_during_refresh')
    require(int(time.time()) < deadline, 'selection_expired_during_refresh')
    created = stage['record_once'](record_id, payload)
    return {'status': 'staged' if created else 'already_staged', 'record_id': record_id, 'view_sha256': view_hash, 'observed_at': view['observed_at'], 'valid_until': deadline}


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
    except (OSError, OverflowError, UnicodeError, ValueError, RecursionError):
        return {'status': 'rejected', 'error': 'host_input_or_stage_unavailable'}
