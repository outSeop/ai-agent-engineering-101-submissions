import fcntl
import hashlib
import json
import tempfile
import time
from pathlib import Path


def raw(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')


def sha(value):
    return hashlib.sha256(value).hexdigest()


def test(run, kit):
    workspace = Path('card_handoff_selftest').resolve()
    workspace.mkdir(exist_ok=True)
    scope = run.__globals__
    previous_root = scope['ROOT']
    with tempfile.TemporaryDirectory(dir=workspace) as directory:
        root = Path(directory)
        scope['ROOT'] = root
        try:
            pub = root / 'card_publication'
            inputs = root / 'host_inputs'
            pub.mkdir()
            inputs.mkdir()
            lock = pub / 'lock'
            lock.touch()
            head = pub / 'head.json'
            handoff = inputs / 'card_publication_handoff.json'
            card_path = root / 'card.json'
            card = {'name': 'outseop-r4', 'description': '기존 상품 안내', 'skills': [{'id': 'm'}, {'id': 'w'}, {'id': 'r'}]}
            before = raw(card)
            after = raw(dict(card, description='합성 대표 상품'))
            card_path.write_bytes(after)
            card_hash = sha(after)
            t = int(time.time())
            entry = {'schema': 'outseop-r4.card-publication-event.v1', 'shop': 'outseop-r4', 'op': 'apply', 'record_id': 'a' * 64, 'parent': None, 'previous_active': None, 'recorded_at': t - 10, 'authority_valid_until': t + 15, 'before_sha256': sha(before), 'after_sha256': card_hash, 'before_card_json': before.decode(), 'after_card_json': after.decode(), 'skus': ['SKU1'], 'view_sha256': 'b' * 64, 'fresh_view_sha256': 'c' * 64, 'offer_until': t + 150, 'block': {'start': 0, 'end': len('합성 대표 상품'), 'text': '합성 대표 상품'}, 'prior_block': {'start': 0, 'end': len('기존 상품 안내'), 'text': '기존 상품 안내'}}
            grant = {'schema': 'outseop-r4.card-publication-handoff.v1', 'shop': 'outseop-r4', 'owner': 'native', 'issued_at': t - 5, 'valid_until': t + 600}

            def install(publication, **changes):
                blob = raw(publication)
                event_id = sha(blob)
                (pub / (event_id + '.json')).write_bytes(blob)
                head.write_bytes(raw({'event': event_id, 'pending': None}))
                record = dict(grant, event=event_id, card_sha256=publication['after_sha256'])
                record.update(changes)
                handoff.write_bytes(raw(record))
                return event_id

            assert run({'approved': True}, kit)['reason'] == 'required_publication_file_missing'
            head.write_bytes(raw({'event': None, 'pending': None}))
            assert run({}, kit)['reason'] == 'no_committed_publication'
            event_id = install(entry)
            snapshot = {path: path.read_bytes() for path in (card_path, lock, head, handoff, pub / (event_id + '.json'))}
            answer = run({}, kit)
            assert answer == {'status': 'skipped', 'reason': 'native_publisher_owns_current_card', 'event': event_id, 'card_sha256': card_hash, 'valid_until': t + 150}, answer
            assert all(path.read_bytes() == data for path, data in snapshot.items())
            handoff.unlink()
            assert run({'owner': 'native', 'event': event_id}, kit)['status'] == 'waiting'
            install(entry, owner='legacy')
            assert run({}, kit)['reason'] == 'handoff_owner_conflict'
            install(entry, event='d' * 64)
            assert run({}, kit)['reason'] == 'handoff_head_conflict'
            install(entry, valid_until=t)
            assert run({}, kit)['reason'] == 'handoff_outside_valid_window'
            install(entry, issued_at=t + 30)
            assert run({}, kit)['reason'] == 'handoff_outside_valid_window'
            install(dict(entry, offer_until=t))
            assert run({}, kit)['reason'] == 'published_offers_expired'
            install(entry)
            head.write_bytes(raw({'event': event_id, 'pending': 'e' * 64}))
            assert run({}, kit)['reason'] == 'publication_pending'
            install(entry)
            (pub / (event_id + '.json')).write_bytes(raw(entry) + b' ')
            assert run({}, kit)['reason'] == 'committed_event_hash_conflict'
            install(entry)
            card_path.write_bytes(after + b' ')
            assert run({}, kit)['reason'] == 'current_card_hash_conflict'
            assert card_path.read_bytes() == after + b' '
            card_path.write_bytes(after)
            with lock.open('rb') as held:
                fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
                assert run({}, kit)['reason'] == 'publisher_busy'
            rollback = dict(entry, op='rollback', record_id=event_id, parent=event_id, before_sha256=card_hash, after_sha256=sha(before), before_card_json=after.decode(), after_card_json=before.decode(), skus=None, view_sha256=None, fresh_view_sha256=None, offer_until=None, block=None, prior_block=entry['block'])
            card_path.write_bytes(before)
            rollback_id = install(rollback)
            assert run({}, kit) == {'status': 'skipped', 'reason': 'native_publisher_owns_current_card', 'event': rollback_id, 'card_sha256': sha(before), 'valid_until': t + 600}
            assert card_path.read_bytes() == before
        finally:
            scope['ROOT'] = previous_root
