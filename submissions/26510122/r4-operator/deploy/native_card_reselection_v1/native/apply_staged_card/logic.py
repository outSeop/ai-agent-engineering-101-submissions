import hashlib
import re
import time
from pathlib import Path

_HOME = Path.cwd().resolve()
_APPLY_SHA = '14143d58859493f56b3b736dab10fe384211d8c0c8b58a1b3db59a50a9d5500f'
_STAGE_SHA = 'e883b594583e1abf8587a963154d58020a0f0e214451dee1fa3c771d11514fbb'
_POLICIES = {'mileage': 'repeat-benefits', 'wait': 'repeat-benefits', 'refund': 'refund-review'}
_SKILLS = {'a2a-checkout', 'repeat-benefits', 'refund-review'}
_MODE_SCHEMA = 'outseop-r4.card-reselection.v1'
_MODE = 'official_mind_reselection'


def _pin(tool, filename, expected, archived=False):
    locations = [_HOME / 'tools' / tool / filename]
    if archived:
        locations.extend(base / '.deprecated' / (tool + '@1') / filename for base in (_HOME, _HOME / 'tools'))
    for path in locations:
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            continue
        if hashlib.sha256(raw).hexdigest() == expected:
            return path, raw.decode('utf-8')
    raise RuntimeError('pinned_source_unavailable:' + tool + '/' + filename)


def _load(source):
    path, text = source
    namespace = {'__file__': str(path), '__name__': '_pinned_card_tool'}
    exec(compile(text, str(path), 'exec'), namespace)
    return namespace


def _hash(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def _active_offer(before):
    publication = ROOT / 'card_publication'
    head_path = publication / 'head.json'
    if not head_path.exists():
        return None, None
    head = decode(head_path.read_bytes())
    event_id = head.get('event')
    if event_id is None:
        return None, None
    check(head.keys() == {'event', 'pending'} and head['pending'] is None and _hash(event_id), 'invalid_active_publication')
    raw = (publication / (event_id + '.json')).read_bytes()
    check(sha(raw) == event_id, 'active_event_hash_conflict')
    event = decode(raw)
    check(event.get('schema') == 'outseop-r4.card-publication-event.v1' and event.get('shop') == 'outseop-r4' and event.get('op') in ('apply', 'rollback'), 'invalid_active_event')
    check(event.get('after_sha256') == sha(before) and event.get('after_card_json') == before.decode('utf-8'), 'active_card_hash_conflict')
    return event_id, event if event.get('skus') else None


def _verify_refresh(event, before, previous, rows, skus, staged, producer):
    check(event['block'] == previous and event['skus'] == skus, 'active_block_or_selection_changed')
    prior_id = event.get('view_sha256')
    check(_hash(prior_id), 'invalid_active_view_hash')
    raw = (ROOT / 'host_inputs' / 'card_offer_original' / (prior_id + '.json')).read_bytes()
    check(sha(raw) == prior_id, 'active_view_hash_conflict')
    prior = decode(raw)
    check(prior.get('schema') == 'outseop-r4.card-offers.v1' and prior.get('shop') == 'outseop-r4', 'invalid_active_view')
    if event['op'] == 'apply':
        check(prior.get('card_sha256') == event['before_sha256'], 'active_view_card_conflict')
    observed, deadline = prior.get('observed_at'), prior.get('valid_until')
    current_deadline = producer.get('valid_until')
    check(type(observed) is int and type(deadline) is int and 0 < deadline - observed <= 180 and type(current_deadline) is int, 'invalid_active_observation_window')
    check(event['recorded_at'] < staged and observed < staged and producer.get('card_sha256') == sha(before), 'refresh_observation_not_new')
    offered = prior.get('offers')
    check(isinstance(offered, list) and all(isinstance(row, dict) and isinstance(row.get('sku'), str) for row in offered), 'invalid_active_offers')
    previous_rows = {row['sku']: row for row in offered}
    check(len(previous_rows) == len(offered), 'duplicate_active_sku')
    for sku in skus:
        old, new = previous_rows.get(sku), rows[sku]
        check(old is not None and type(old.get('valid_until')) is int and old['valid_until'] == deadline and type(new.get('valid_until')) is int and new['valid_until'] == current_deadline, 'ambiguous_row_deadline')
        check(encode(dict(old, valid_until=current_deadline)) == encode(new), 'selected_offer_changed')


def _reselection():
    host = ROOT / 'host_inputs'
    raw = (host / 'card_publication_authority.json').read_bytes()
    digest = sha(raw)
    try:
        proof = (host / 'card_reselection' / (digest + '.json')).read_bytes()
    except FileNotFoundError:
        return None
    return digest, decode(raw), decode(proof)


def _reselect(binding, head_id, event, before, after, previous, rows, skus, stage, details, producer, producer_module):
    authority_hash, authority, proof = binding
    record_id = authority.get('record_id')
    view_id, fresh_id = stage.get('view_sha256'), details.get('fresh_view_sha256')
    check(all(_hash(value) for value in (record_id, view_id, fresh_id, head_id)) and fresh_id != view_id, 'invalid_reselection_hashes')
    check(event is not None and event['block'] == previous and previous['start'] == 0, 'reselection_active_block_conflict')
    check(authority.get('op') == 'apply' and authority.get('before_sha256') == sha(before) and authority.get('after_sha256') == sha(after) and encode(authority.get('details')) == encode(details), 'reselection_authority_conflict')
    stage_path = ROOT / 'card_update_stage' / (record_id + '.json')
    with stage_path.open('rb') as stream:
        from os import fstat
        created = fstat(stream.fileno()).st_mtime_ns
        raw_stage = stream.read(8 * 1024 * 1024 + 1)
    check(len(raw_stage) <= 8 * 1024 * 1024 and sha(raw_stage) == record_id and encode(decode(raw_stage)) == encode(stage), 'reselection_stage_conflict')
    expected = dict(schema=_MODE_SCHEMA, mode=_MODE, authority_sha256=authority_hash, head_event=head_id, record_id=record_id, before_sha256=sha(before), after_sha256=sha(after), stage_source_sha256=_STAGE_SHA, original_view_sha256=view_id, fresh_view_sha256=fresh_id, skus=skus, stage_created_ns=created)
    check(encode(proof) == encode(expected), 'reselection_proof_conflict')
    valid_sku = producer_module['sku_ok']
    check(isinstance(skus, list) and 1 <= len(skus) <= 3 and all(valid_sku(sku) for sku in skus) and len(set(skus)) == len(skus), 'invalid_reselection_selection')
    fresh_path = ROOT / 'host_inputs' / 'card_offer_fresh' / (fresh_id + '.json')
    fresh_raw = producer_module['read_raw'](fresh_path)
    check(sha(fresh_raw) == fresh_id, 'reselection_fresh_hash_conflict')
    fresh = producer_module['decode'](fresh_raw)
    now = int(time.time())
    observed = stage['observed_at']
    check(type(observed) is int and type(event.get('recorded_at')) is int and type(authority.get('issued_at')) is int and type(authority.get('valid_until')) is int, 'invalid_reselection_timing')
    check(0 < authority['valid_until'] - authority['issued_at'] <= 30 and authority['issued_at'] <= now < authority['valid_until'], 'invalid_reselection_authority_window')
    selected_rows = []
    for view in (producer, fresh):
        producer_module['fields'](view, producer_module['CONTEXT_FIELDS'], 'invalid_reselection_view_fields')
        seen, deadline = view['observed_at'], view['valid_until']
        check(view['schema'] == 'outseop-r4.card-offers.v1' and view['shop'] == 'outseop-r4' and view['card_sha256'] == sha(before) and view['replace_text'] == previous['text'], 'reselection_view_conflict')
        check(type(seen) is int and type(deadline) is int and 0 <= seen <= now < deadline <= seen + 150, 'invalid_reselection_view_window')
        producer_module['verify_market'](view['market'], seen)
        check(isinstance(view['offers'], list), 'invalid_reselection_offers')
        indexed = {}
        for row in view['offers']:
            producer_module['verify_offer'](row)
            check(row['sku'] not in indexed, 'duplicate_reselection_sku')
            indexed[row['sku']] = row
        check(all(sku in indexed and indexed[sku]['state'] == 'available' and now < producer_module['expiry'](indexed[sku], view) for sku in skus), 'reselection_offer_unavailable')
        selected_rows.append([indexed[sku] for sku in skus])
    check(event['recorded_at'] < observed == producer['observed_at'] < fresh['observed_at'] <= authority['issued_at'] and observed * 1_000_000_000 <= created < fresh['observed_at'] * 1_000_000_000, 'reselection_observation_order_conflict')
    check(encode(selected_rows[0]) == encode(selected_rows[1]) == encode([rows[sku] for sku in skus]), 'reselection_selected_offer_changed')


def _native(before, after, old, new, prefix, suffix, rows, skus, stage, details):
    original, proposed = decode(before), decode(after)
    skills = original.get('skills')
    native = (isinstance(skills, list) and len(skills) == 3
              and all(isinstance(skill, dict) and isinstance(skill.get('id'), str) for skill in skills)
              and {skill['id'] for skill in skills} == _SKILLS)
    binding = _reselection()
    check(binding is None or native, 'reselection_native_card_required')
    retained = prefix + suffix
    tail = '\n\n' + retained if retained else ''
    if not native and (len(new) <= len(tail) or not new.endswith(tail)):
        return None
    producer_module = _load(_pin('stage_representative_card', 'logic.py', _STAGE_SHA))
    observed = stage['observed_at']
    rendered = producer_module['render']([rows[sku] for sku in skus], observed)
    start, end = len(prefix), len(old) - len(suffix)
    previous = {'start': start, 'end': end, 'text': old[start:end]}
    head_id, event = _active_offer(before) if native else (None, None)
    if event is not None or binding is not None:
        view_id = stage['view_sha256']
        producer_raw = (ROOT / 'host_inputs' / 'card_offer_original' / (view_id + '.json')).read_bytes()
        check(sha(producer_raw) == view_id, 'refresh_view_hash_conflict')
        producer = decode(producer_raw)
        if binding is None:
            _verify_refresh(event, before, previous, rows, skus, observed, producer)
            check(new == prefix + rendered + suffix, 'unapproved_offer_block')
        else:
            _reselect(binding, head_id, event, before, after, previous, rows, skus, stage, details, producer, producer_module)
            title = producer_module['TITLE']
            check([match.start() for match in title.finditer(old)] == [start] and [match.start() for match in title.finditer(new)] == [start] and new == rendered + tail, 'unapproved_reselection_renderer')
        block_start = start
    elif new == rendered + tail:
        block_start = 0
    else:
        check(not native, 'unapproved_offer_block')
        return None
    check(original['name'] == 'outseop-r4' and isinstance(skills, list) and len(skills) == 3 and all(isinstance(skill, dict) for skill in skills), 'card_identity_or_skills_changed')
    check(encode({key: value for key, value in original.items() if key != 'description'}) == encode({key: value for key, value in proposed.items() if key != 'description'}), 'card_identity_or_skills_changed')
    policies = details['policies']
    fields(policies, 'mileage wait refund', 'missing_policy_anchors')
    for name, clause in policies.items():
        check(isinstance(clause, str) and bool(clause.strip()), 'protected_policy_overlap_or_change')
        count = old.count(clause)
        if count:
            check(prefix.count(clause) + suffix.count(clause) == count, 'protected_policy_overlap_or_change')
        else:
            matches = [skill for skill in skills if skill.get('id') == _POLICIES[name]]
            check(len(matches) == 1 and isinstance(matches[0].get('description'), str) and clause in matches[0]['description'], 'protected_policy_overlap_or_change')
    check(len(new) <= 1000 and new.count(rendered) == 1 and sha(rendered.encode('utf-8')) == details['replacement_sha256'], 'unapproved_offer_block')
    return rendered, block_start


def _install():
    path, source = _pin('apply_staged_card', 'logic.py', _APPLY_SHA, archived=True)
    old_block = "'block': {'start': start, 'end': start + len(replacement), 'text': replacement}"
    new_block = "'block': {'start': block_start, 'end': block_start + len(replacement), 'text': replacement}"
    if source.count(old_block) != 1:
        raise RuntimeError('unexpected_v1_block_record')
    source = source.replace(old_block, new_block)
    start = source.index('    check(len(new_text) > len(prefix) + len(suffix)')
    end = source.index('    return after,', start)
    legacy = ''.join('    ' + line if line.strip() else line for line in source[start:end].splitlines(keepends=True))
    source = source[:start] + (
        '    native = _native(before, after, old_text, new_text, prefix, suffix, old_rows, skus, stage, details)\n'
        '    if native is None:\n' + legacy + '        block_start = start\n'
        '    else:\n        replacement, block_start = native\n'
    ) + source[end:]
    source, count = re.subn(r'^def run\(', 'def _run_pinned_apply(', source, flags=re.MULTILINE)
    if count != 1:
        raise RuntimeError('unexpected_v1_entrypoint')
    exec(compile(source, str(path), 'exec'), globals())


_install()


def run(args, kit):
    return _run_pinned_apply(args, kit)
