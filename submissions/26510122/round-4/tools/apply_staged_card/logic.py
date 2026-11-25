import hashlib
import re
from pathlib import Path

_HOME = Path.cwd().resolve()
_APPLY_SHA = '14143d58859493f56b3b736dab10fe384211d8c0c8b58a1b3db59a50a9d5500f'
_STAGE_SHA = 'e883b594583e1abf8587a963154d58020a0f0e214451dee1fa3c771d11514fbb'
_POLICIES = {'mileage': 'repeat-benefits', 'wait': 'repeat-benefits', 'refund': 'refund-review'}
_SKILLS = {'a2a-checkout', 'repeat-benefits', 'refund-review'}


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


def _active_offer(before):
    publication = ROOT / 'card_publication'
    head_path = publication / 'head.json'
    if not head_path.exists():
        return None
    head = decode(head_path.read_bytes())
    event_id = head.get('event')
    if event_id is None:
        return None
    check(head.keys() == {'event', 'pending'} and head['pending'] is None and isinstance(event_id, str) and re.fullmatch(r'[0-9a-f]{64}', event_id), 'invalid_active_publication')
    raw = (publication / (event_id + '.json')).read_bytes()
    check(sha(raw) == event_id, 'active_event_hash_conflict')
    event = decode(raw)
    check(event.get('schema') == 'outseop-r4.card-publication-event.v1' and event.get('shop') == 'outseop-r4' and event.get('op') in ('apply', 'rollback'), 'invalid_active_event')
    check(event.get('after_sha256') == sha(before) and event.get('after_card_json') == before.decode('utf-8'), 'active_card_hash_conflict')
    return event if event.get('skus') else None


def _verify_refresh(event, before, previous, rows, skus, staged, producer):
    check(event['block'] == previous and event['skus'] == skus, 'active_block_or_selection_changed')
    prior_id = event.get('view_sha256')
    check(isinstance(prior_id, str) and re.fullmatch(r'[0-9a-f]{64}', prior_id), 'invalid_active_view_hash')
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


def _native(before, after, old, new, prefix, suffix, rows, skus, stage, details):
    original, proposed = decode(before), decode(after)
    skills = original.get('skills')
    native = (isinstance(skills, list) and len(skills) == 3
              and all(isinstance(skill, dict) and isinstance(skill.get('id'), str) for skill in skills)
              and {skill['id'] for skill in skills} == _SKILLS)
    retained = prefix + suffix
    tail = '\n\n' + retained if retained else ''
    if not native and (len(new) <= len(tail) or not new.endswith(tail)):
        return None
    renderer = _load(_pin('stage_representative_card', 'logic.py', _STAGE_SHA))['render']
    observed = stage['observed_at']
    rendered = renderer([rows[sku] for sku in skus], observed)
    start, end = len(prefix), len(old) - len(suffix)
    previous = {'start': start, 'end': end, 'text': old[start:end]}
    event = _active_offer(before) if native else None
    if event is not None:
        view_id = stage['view_sha256']
        producer_raw = (ROOT / 'host_inputs' / 'card_offer_original' / (view_id + '.json')).read_bytes()
        check(sha(producer_raw) == view_id, 'refresh_view_hash_conflict')
        _verify_refresh(event, before, previous, rows, skus, observed, decode(producer_raw))
        check(new == prefix + rendered + suffix, 'unapproved_offer_block')
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
