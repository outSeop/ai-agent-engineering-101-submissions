'''Host contract. Protect card.json, host_inputs and their parents, the stage directory, and the publication directory from caller writes, symlinks and substitution. Provision card_publication/lock as a permanent regular file. Use POSIX flock on that same inode for every card writer and the maintenance guard. At cutover the host must fence any legacy writer that does not take the lock before granting authority, and keep it fenced while the native publisher owns the card. card_publication and card.json must support same-filesystem atomic replace and directory fsync. The host independently verifies this integration before installing authority.

Archive the original v1 bytes at host_inputs/card_offer_original/<view_sha256>.json before staging. After the stage file exists, the reviewed producer independently rereads the authenticated stock and catalog and supplies v1 bytes at host_inputs/card_offer_fresh/<fresh_view_sha256>.json. Its observed_at is the completed read in whole Unix seconds, after the original observation and at or after the stage file's mtime. The host preserves that mtime. Both snapshots bind to the same original card bytes and replace_text. Selected rows must match in every v1 field, including the quoted validity deadline. A producer that recomputes a different deadline must request restaging or supply the same still-valid quote deadline based on its fresh source read. Prices come from the existing externally authored legacy pricing library through the host producer.

Install host_inputs/card_publication_authority.json atomically under the same lock. Its exact fields are schema (outseop-r4.card-publication-authority.v1), shop (outseop-r4), owner (native), op, record_id, head (the prior committed event hash or null), before_sha256, after_sha256, issued_at, valid_until, details. Times are Unix seconds, with at most a 30-second lifetime. Apply details are fresh_view_sha256, replacement_sha256 (SHA256 of the exact new description substring, UTF-8), and policies (exact keys mileage, wait, refund). Each policy value is the verbatim complete clause in the original description. The host checks that the initial replace_text consists solely of replaceable sales copy, that no obsolete offers are left elsewhere, and that the approved new substring makes only the producer-backed offers and approved policy statements. It reviews both cards for public-only content and verifies existing mileage, wait-credit and refund wording, including the status of refund integration. On refresh the replacement must exactly match the prior active event's block and range. Rollback uses details={} and requires the host's review of the restored public card, including any offers. No caller flag supplies authority.

Under the lock, card_publication/head.json is {event,pending}, each a SHA256 or null. Immutable card_publication/<event>.json journals contain the exact backup and proposed card. Existing or absent head is reconciled against the actual card bytes. Treat a pending event, an incomplete or conflicting hash, or an expired offer_until as a wait/conflict for maintenance. The handoff reader uses the committed event and exact current card hash. Apply succeeds for the local card file. The host verifies that its existing serving path exposes those bytes.'''
import fcntl
import hashlib
import json
import os
import re
import stat
import tempfile
import time
from pathlib import Path

ROOT = Path('.')
SHOP = 'outseop-r4'
VIEW_KEYS = 'schema shop observed_at valid_until card_sha256 replace_text offers market'
ROW_KEYS = 'sku name category_path state grade price_credits standard_fee_credits valid_until expires_at'
STAGE_KEYS = 'schema shop skus observed_at valid_until view_sha256 before_sha256 after_sha256 before_card_json after_card_json'
AUTH_KEYS = 'schema shop owner op record_id head before_sha256 after_sha256 issued_at valid_until details'
EVENT_SCHEMA = 'outseop-r4.card-publication-event.v1'
MAX_BYTES = 24 * 1024 * 1024


class Refuse(ValueError):
    pass


def check(condition, code):
    if not condition:
        raise Refuse(code)


def fields(obj, keys, code):
    check(isinstance(obj, dict) and obj.keys() == set(keys.split()), code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def is_hash(value):
    return isinstance(value, str) and re.fullmatch(r'[a-f0-9]{64}', value) is not None


def is_int(value, minimum=0):
    return type(value) is int and value >= minimum


def now():
    return int(time.time())


def encode(obj):
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('utf-8')


def pairs(items):
    obj = {}
    for key, value in items:
        check(key not in obj, 'duplicate_json_key')
        obj[key] = value
    return obj


def invalid_constant(value):
    raise Refuse('invalid_json_number')


def decode(raw):
    return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=invalid_constant)


def read(path):
    with path.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    check(len(raw) <= MAX_BYTES, 'input_too_large')
    return raw


def hashed(path, expected):
    raw = read(path)
    check(sha(raw) == expected, 'artifact_hash_mismatch')
    return raw


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic(path, data, pub, mode=0o600):
    fd, temporary = tempfile.mkstemp(dir=pub)
    try:
        with os.fdopen(fd, 'wb') as out:
            os.fchmod(out.fileno(), mode)
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
        sync_dir(path.parent)
        if path.parent != pub:
            sync_dir(pub)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def event(pub, event_id):
    check(is_hash(event_id), 'invalid_event_id')
    value = decode(hashed(pub / (event_id + '.json'), event_id))
    check(value['schema'] == EVENT_SCHEMA and value['shop'] == SHOP, 'invalid_publication_event')
    return value


def store_head(pub, current, pending=None):
    atomic(pub / 'head.json', encode({'event': current, 'pending': pending}), pub)


def recover(pub, card_path, current_hash):
    try:
        head = decode(read(pub / 'head.json'))
    except FileNotFoundError:
        return None, None
    fields(head, 'event pending', 'invalid_publication_head')
    current = head['event']
    committed = event(pub, current) if current is not None else None
    pending = head['pending']
    if pending is not None:
        prepared = event(pub, pending)
        check(prepared['parent'] == current and (committed is None or prepared['before_sha256'] == committed['after_sha256']), 'publication_history_conflict')
        check(current_hash in (prepared['before_sha256'], prepared['after_sha256']), 'card_changed_during_publication')
        if current_hash == prepared['after_sha256']:
            sync_dir(card_path.parent)
            current, committed = pending, prepared
        store_head(pub, current)
    if committed is not None:
        check(current_hash == committed['after_sha256'], 'current_card_hash_conflict')
    return current, committed


def view(path, view_id, before_hash, t):
    value = decode(hashed(path / (view_id + '.json'), view_id))
    fields(value, VIEW_KEYS, 'invalid_view_fields')
    check(value['schema'] == 'outseop-r4.card-offers.v1' and value['shop'] == SHOP and value['card_sha256'] == before_hash, 'view_identity_or_baseline_mismatch')
    observed, until = value['observed_at'], value['valid_until']
    check(is_int(observed) and is_int(until) and observed <= t < until <= observed + 180, 'stale_or_future_view')
    check(isinstance(value['offers'], list), 'invalid_offer_list')
    rows = {}
    for row in value['offers']:
        fields(row, ROW_KEYS, 'invalid_offer_fields')
        sku = row['sku']
        check(isinstance(sku, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', sku) and sku not in rows, 'invalid_or_duplicate_offer_sku')
        rows[sku] = row
    return value, rows


def selected(rows, skus, until, t):
    for sku in skus:
        row = rows.get(sku)
        check(row is not None and row['state'] == 'available', 'selected_offer_unavailable')
        check(row['grade'] in ('A', 'B', 'C') and is_int(row['price_credits'], 1), 'invalid_grade_or_price')
        fee, quote_until, expires = row['standard_fee_credits'], row['valid_until'], row['expires_at']
        check((fee is None or is_int(fee)) and is_int(quote_until, 1) and (expires is None or is_int(expires, 1)), 'invalid_selected_terms')
        until = min(until, quote_until, expires if expires is not None else quote_until)
    check(t < until, 'selected_offer_expired')
    return until


def validate_cards(before, after):
    first, second = decode(before), decode(after)
    for card in (first, second):
        check(isinstance(card, dict) and card.get('name') == SHOP and isinstance(card.get('description'), str) and isinstance(card.get('skills'), list) and len(card['skills']) == 3 and all(isinstance(skill, dict) for skill in card['skills']), 'invalid_card_identity_or_skills')
    check(len(second['description']) <= 1000, 'description_over_1000')
    check(encode({k: v for k, v in first.items() if k != 'description'}) == encode({k: v for k, v in second.items() if k != 'description'}), 'non_description_card_field_changed')
    return first['description'], second['description']


def prepare_apply(record_id, baseline, authority, active, t):
    stage_path = ROOT / 'card_update_stage' / (record_id + '.json')
    stage_raw = hashed(stage_path, record_id)
    stage = decode(stage_raw)
    fields(stage, STAGE_KEYS, 'invalid_stage_fields')
    check(encode(stage) == stage_raw and stage['schema'] == 'outseop-r4.card-stage.v1' and stage['shop'] == SHOP, 'invalid_stage_encoding_or_identity')
    check(all(isinstance(stage[k], str) for k in ('before_card_json', 'after_card_json')), 'invalid_staged_card')
    before, after = (stage[k].encode('utf-8') for k in ('before_card_json', 'after_card_json'))
    check(before == baseline and sha(before) == stage['before_sha256'] and sha(after) == stage['after_sha256'] and before != after, 'stage_card_hash_conflict')
    old_text, new_text = validate_cards(before, after)
    skus = stage['skus']
    check(isinstance(skus, list) and 1 <= len(skus) <= 3 and all(isinstance(sku, str) for sku in skus) and len(set(skus)) == len(skus), 'select_one_to_three_unique_skus')
    details = authority['details']
    fields(details, 'fresh_view_sha256 replacement_sha256 policies', 'invalid_apply_authority_details')
    source_id, fresh_id = stage['view_sha256'], details['fresh_view_sha256']
    check(is_hash(source_id) and is_hash(fresh_id) and source_id != fresh_id, 'independent_fresh_view_required')
    inputs = ROOT / 'host_inputs'
    old_view, old_rows = view(inputs / 'card_offer_original', source_id, sha(before), t)
    fresh, fresh_rows = view(inputs / 'card_offer_fresh', fresh_id, sha(before), t)
    check(is_int(stage['observed_at']) and stage['observed_at'] == old_view['observed_at'] < fresh['observed_at'] <= authority['issued_at'] and fresh['observed_at'] * 1_000_000_000 >= stage_path.stat().st_mtime_ns, 'fresh_view_must_follow_stage')
    original_until = selected(old_rows, skus, old_view['valid_until'], t)
    fresh_until = selected(fresh_rows, skus, fresh['valid_until'], t)
    check(is_int(stage['valid_until']) and stage['valid_until'] == original_until, 'staged_deadline_mismatch')
    check(all(encode(old_rows[sku]) == encode(fresh_rows[sku]) for sku in skus), 'selected_offer_terms_changed')
    old_block = old_view['replace_text']
    check(isinstance(old_block, str) and bool(old_block.strip()) and old_text.count(old_block) == 1 and fresh['replace_text'] == old_block, 'replacement_region_conflict')
    start = old_text.index(old_block)
    end = start + len(old_block)
    if active is not None:
        check(active['block'] == {'start': start, 'end': end, 'text': old_block}, 'previous_product_block_conflict')
    prefix, suffix = old_text[:start], old_text[end:]
    check(len(new_text) > len(prefix) + len(suffix) and new_text.startswith(prefix) and new_text.endswith(suffix), 'text_outside_offer_block_changed')
    replacement = new_text[start:len(new_text) - len(suffix)]
    check(replacement.strip() and new_text.count(replacement) == 1 and sha(replacement.encode('utf-8')) == details['replacement_sha256'], 'unapproved_offer_block')
    policies = details['policies']
    fields(policies, 'mileage wait refund', 'missing_policy_anchors')
    for clause in policies.values():
        check(isinstance(clause, str) and bool(clause.strip()) and old_text.count(clause) == new_text.count(clause) == 1 and (clause in prefix or clause in suffix), 'protected_policy_overlap_or_change')
    return after, {'skus': skus, 'view_sha256': source_id, 'fresh_view_sha256': fresh_id, 'offer_until': min(original_until, fresh_until), 'block': {'start': start, 'end': start + len(replacement), 'text': replacement}, 'prior_block': {'start': start, 'end': end, 'text': old_block}}


def locked(args, pub, card_path):
    op, record_id = args['op'], args['record_id']
    before = read(card_path)
    before_hash = sha(before)
    head, last = recover(pub, card_path, before_hash)
    if last is not None and last['op'] == op and last['record_id'] == record_id:
        return {'status': 'already_applied' if op == 'apply' else 'already_rolled_back', 'event': head, 'card_sha256': before_hash}
    authority = decode(read(ROOT / 'host_inputs' / 'card_publication_authority.json'))
    fields(authority, AUTH_KEYS, 'invalid_authority_fields')
    check(authority['schema'] == 'outseop-r4.card-publication-authority.v1' and authority['shop'] == SHOP and authority['owner'] == 'native' and authority['op'] == op and authority['record_id'] == record_id and authority['head'] == head and authority['before_sha256'] == before_hash and is_hash(authority['after_sha256']), 'publication_authority_conflict')
    t = now()
    issued, until = authority['issued_at'], authority['valid_until']
    check(is_int(issued) and is_int(until) and issued <= t < until <= issued + 30, 'stale_or_future_authority')
    active_id = None if last is None else head if last['op'] == 'apply' else last['previous_active']
    active = event(pub, active_id) if active_id is not None else None
    if active is not None:
        check(active['op'] == 'apply' and active['after_sha256'] == before_hash, 'active_card_hash_conflict')
    if op == 'apply':
        after, change = prepare_apply(record_id, before, authority, active, t)
        previous_active = active_id
        deadline = min(until, change['offer_until'])
    else:
        check(authority['details'] == {} and active_id == record_id and active is not None, 'rollback_target_not_current')
        after = active['before_card_json'].encode('utf-8')
        check(sha(after) == active['before_sha256'], 'rollback_backup_hash_mismatch')
        validate_cards(before, after)
        previous_active = active['previous_active']
        restored = event(pub, previous_active) if previous_active is not None else None
        if restored is not None:
            check(restored['op'] == 'apply' and restored['after_sha256'] == sha(after) and t < restored['offer_until'], 'rollback_would_restore_stale_offers')
        change = {k: restored[k] if restored is not None else None for k in ('skus', 'view_sha256', 'fresh_view_sha256', 'offer_until', 'block')}
        change['prior_block'] = active['block']
        deadline = min(until, change['offer_until']) if change['offer_until'] is not None else until
    after_hash = sha(after)
    check(after_hash == authority['after_sha256'], 'unapproved_after_card')
    entry = {'schema': EVENT_SCHEMA, 'shop': SHOP, 'op': op, 'record_id': record_id, 'parent': head, 'previous_active': previous_active, 'recorded_at': t, 'authority_valid_until': until, 'before_sha256': before_hash, 'after_sha256': after_hash, 'before_card_json': before.decode('utf-8'), 'after_card_json': after.decode('utf-8'), **change}
    blob = encode(entry)
    check(len(blob) <= MAX_BYTES, 'publication_event_too_large')
    event_id = sha(blob)
    entry_path = pub / (event_id + '.json')
    if entry_path.exists():
        check(read(entry_path) == blob, 'publication_record_conflict')
    else:
        atomic(entry_path, blob, pub)
    store_head(pub, head, event_id)
    check(read(card_path) == before, 'card_changed_before_replace')
    check(now() < deadline, 'publication_expired_before_replace')
    atomic(card_path, after, pub, stat.S_IMODE(card_path.stat().st_mode))
    store_head(pub, event_id)
    return {'status': 'applied' if op == 'apply' else 'rolled_back', 'event': event_id, 'card_sha256': after_hash}


def run(args, kit):
    try:
        fields(args, 'op record_id', 'invalid_request_fields')
        check(args['op'] in ('apply', 'rollback') and is_hash(args['record_id']), 'invalid_request')
        pub = ROOT / 'card_publication'
        with (pub / 'lock').open('rb') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return {'status': 'waiting', 'reason': 'publisher_busy'}
            return locked(args, pub, ROOT / 'card.json')
    except Refuse as exc:
        return {'status': 'rejected', 'reason': str(exc)}
    except FileNotFoundError:
        return {'status': 'waiting', 'reason': 'required_host_file_missing'}
    except (UnicodeError, ValueError, KeyError, TypeError, RecursionError):
        return {'status': 'rejected', 'reason': 'invalid_publication_input'}
    except OSError:
        return {'status': 'retry', 'reason': 'publication_io_error_check_journal'}
