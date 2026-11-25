'''Install this maintenance guard only after the first authorized native card apply has committed. At cutover the host fences the legacy writer under the permanent card_publication/lock protocol documented by apply_staged_card. The host alone updates the protected handoff file atomically under the same exclusive lock. Keep the lock inode and all input paths protected from substitution.

host_inputs/card_publication_handoff.json has exactly schema, shop, owner, event, card_sha256, issued_at, valid_until. Schema is outseop-r4.card-publication-handoff.v1, shop is outseop-r4, and owner is native. Bind event to the committed head and card_sha256 to its after SHA256 and the exact current card bytes. Issue it at or after the event's recorded_at, with an exclusive deadline at most 900 seconds after issuance. Renewal does not extend the event's offer_until. An initial-card rollback can carry offer_until=null because the apply tool requires host approval of that restoration. The host replaces the handoff on every committed apply or rollback. Absence, expiry, or conflict leaves the card untouched. This guard performs no publication. The only write permission is for the isolated forge self-test fixtures.'''
import fcntl
import hashlib
import json
import re
import time
from pathlib import Path

ROOT = Path('.')
SHOP = 'outseop-r4'
MAX_BYTES = 24 * 1024 * 1024
HANDOFF_FIELDS = set('schema shop owner event card_sha256 issued_at valid_until'.split())
EVENT_FIELDS = set('schema shop op record_id parent previous_active recorded_at authority_valid_until before_sha256 after_sha256 before_card_json after_card_json skus view_sha256 fresh_view_sha256 offer_until block prior_block'.split())


class Conflict(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise Conflict(reason)


def result(status, reason):
    return {'status': status, 'reason': reason}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def is_hash(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def is_time(value):
    return type(value) is int and value >= 0


def read(path):
    with path.open('rb') as stream:
        data = stream.read(MAX_BYTES + 1)
    require(len(data) <= MAX_BYTES, 'publication_input_too_large')
    return data


def pairs(items):
    value = {}
    for key, item in items:
        require(key not in value, 'duplicate_publication_key')
        value[key] = item
    return value


def invalid_constant(value):
    raise Conflict('invalid_publication_number')


def decode(data, keys, reason):
    value = json.loads(data.decode('utf-8'), object_pairs_hook=pairs, parse_constant=invalid_constant)
    require(isinstance(value, dict) and value.keys() == keys, reason)
    return value


def inspect(pub):
    head = decode(read(pub / 'head.json'), {'event', 'pending'}, 'invalid_publication_head')
    if head['pending'] is not None:
        require(is_hash(head['pending']), 'invalid_pending_event')
        return result('waiting', 'publication_pending')
    event_id = head['event']
    if event_id is None:
        return result('waiting', 'no_committed_publication')
    require(is_hash(event_id), 'invalid_committed_event')
    handoff = decode(read(ROOT / 'host_inputs' / 'card_publication_handoff.json'), HANDOFF_FIELDS, 'invalid_handoff_record')
    require(handoff['schema'] == 'outseop-r4.card-publication-handoff.v1' and handoff['shop'] == SHOP and handoff['owner'] == 'native', 'handoff_owner_conflict')
    require(handoff['event'] == event_id and is_hash(handoff['card_sha256']), 'handoff_head_conflict')
    event_raw = read(pub / (event_id + '.json'))
    require(sha(event_raw) == event_id, 'committed_event_hash_conflict')
    event = decode(event_raw, EVENT_FIELDS, 'invalid_committed_event')
    require(event['schema'] == 'outseop-r4.card-publication-event.v1' and event['shop'] == SHOP and event['op'] in ('apply', 'rollback'), 'invalid_committed_event')
    card_hash = handoff['card_sha256']
    after_text = event['after_card_json']
    require(event['after_sha256'] == card_hash and isinstance(after_text, str) and sha(after_text.encode('utf-8')) == card_hash and sha(read(ROOT / 'card.json')) == card_hash, 'current_card_hash_conflict')
    recorded, issued, deadline = event['recorded_at'], handoff['issued_at'], handoff['valid_until']
    require(all(is_time(value) for value in (recorded, issued, deadline)) and recorded <= issued < deadline <= issued + 900, 'invalid_handoff_time')
    offers_until = event['offer_until']
    if offers_until is None:
        require(event['op'] == 'rollback' and event['previous_active'] is None and event['block'] is None, 'missing_offer_deadline')
    else:
        require(is_time(offers_until) and recorded < offers_until, 'invalid_offer_deadline')
    current = int(time.time())
    if current < issued or current >= deadline:
        return result('waiting', 'handoff_outside_valid_window')
    if offers_until is not None and current >= offers_until:
        return result('waiting', 'published_offers_expired')
    return {'status': 'skipped', 'reason': 'native_publisher_owns_current_card', 'event': event_id, 'card_sha256': card_hash, 'valid_until': min(deadline, offers_until) if offers_until is not None else deadline}


def run(args, kit):
    pub = ROOT / 'card_publication'
    try:
        with (pub / 'lock').open('rb') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                return result('waiting', 'publisher_busy')
            return inspect(pub)
    except FileNotFoundError:
        return result('waiting', 'required_publication_file_missing')
    except Conflict as exc:
        return result('conflict', str(exc))
    except (UnicodeError, ValueError, RecursionError):
        return result('conflict', 'invalid_publication_json')
    except OSError:
        return result('waiting', 'publication_read_error')
