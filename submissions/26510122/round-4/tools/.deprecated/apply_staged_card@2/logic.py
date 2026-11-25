import hashlib
import re
from pathlib import Path

_TOOL_HOME = Path.cwd().resolve()
_APPLY_LOGIC_SHA = '14143d58859493f56b3b736dab10fe384211d8c0c8b58a1b3db59a50a9d5500f'
_STAGE_LOGIC_SHA = 'e883b594583e1abf8587a963154d58020a0f0e214451dee1fa3c771d11514fbb'
_POLICY_SKILL_IDS = {'mileage': 'repeat-benefits', 'wait': 'repeat-benefits', 'refund': 'refund-review'}


def _pinned_source(tool, filename, expected, archived=False):
    paths = [_TOOL_HOME / 'tools' / tool / filename]
    if archived:
        paths.extend([
            _TOOL_HOME / '.deprecated' / (tool + '@1') / filename,
            _TOOL_HOME / 'tools' / '.deprecated' / (tool + '@1') / filename,
        ])
    for path in paths:
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            continue
        if hashlib.sha256(data).hexdigest() == expected:
            return path, data.decode('utf-8')
    raise RuntimeError('required_pinned_source_missing_or_changed:' + tool + '/' + filename)


def _pinned_namespace(source):
    path, text = source
    namespace = {'__file__': str(path), '__name__': '_pinned_card_tool'}
    exec(compile(text, str(path), 'exec'), namespace)
    return namespace


def _native_offer_block(before, after, old_text, new_text, prefix, suffix, old_rows, skus, observed_at, details):
    retained = prefix + suffix
    tail = '\n\n' + retained if retained else ''
    if len(new_text) <= len(tail) or not new_text.endswith(tail):
        return None

    try:
        stage = _pinned_namespace(_pinned_source('stage_representative_card', 'logic.py', _STAGE_LOGIC_SHA))
    except (OSError, RuntimeError):
        check(False, 'required_pinned_stage_source_missing_or_changed')
    rendered = stage['render']([old_rows[sku] for sku in skus], observed_at)
    if new_text != rendered + tail:
        return None

    old_card = decode(before)
    new_card = decode(after)
    skills = old_card['skills']
    check(old_card['name'] == 'outseop-r4' and isinstance(skills, list) and len(skills) == 3 and all(isinstance(skill, dict) for skill in skills), 'card_identity_or_skills_changed')
    old_fields = dict(old_card)
    new_fields = dict(new_card)
    del old_fields['description']
    del new_fields['description']
    check(encode(old_fields) == encode(new_fields), 'card_identity_or_skills_changed')

    policies = details['policies']
    fields(policies, 'mileage wait refund', 'missing_policy_anchors')
    for name, clause in policies.items():
        check(isinstance(clause, str) and bool(clause.strip()), 'protected_policy_overlap_or_change')
        occurrences = old_text.count(clause)
        if occurrences:
            check(prefix.count(clause) + suffix.count(clause) == occurrences, 'protected_policy_overlap_or_change')
        else:
            matches = [skill for skill in skills if skill.get('id') == _POLICY_SKILL_IDS[name]]
            check(len(matches) == 1 and isinstance(matches[0].get('description'), str) and clause in matches[0]['description'], 'protected_policy_overlap_or_change')

    check(new_text.count(rendered) == 1 and sha(rendered.encode('utf-8')) == details['replacement_sha256'], 'unapproved_offer_block')
    return rendered


def _install_pinned_apply():
    path, source = _pinned_source('apply_staged_card', 'logic.py', _APPLY_LOGIC_SHA, archived=True)
    old_block = "'block': {'start': start, 'end': start + len(replacement), 'text': replacement}"
    new_block = "'block': {'start': block_start, 'end': block_start + len(replacement), 'text': replacement}"
    if source.count(old_block) != 1:
        raise RuntimeError('unexpected_v1_block_record')
    source = source.replace(old_block, new_block)
    start = source.index('    check(len(new_text) > len(prefix) + len(suffix)')
    end = source.index('    return after,', start)
    legacy = ''.join('    ' + line if line.strip() else line for line in source[start:end].splitlines(keepends=True))
    source = source[:start] + (
        "    replacement = _native_offer_block(before, after, old_text, new_text, prefix, suffix, old_rows, skus, stage['observed_at'], details)\n"
        '    if replacement is None:\n'
        + legacy +
        '        block_start = start\n'
        '    else:\n'
        '        block_start = 0\n'
    ) + source[end:]
    source, entrypoints = re.subn(r'^def run\(', 'def _run_pinned_apply(', source, flags=re.MULTILINE)
    if entrypoints != 1:
        raise RuntimeError('unexpected_v1_entrypoint')
    exec(compile(source, str(path), 'exec'), globals())


_install_pinned_apply()


def run(args, kit):
    return _run_pinned_apply(args, kit)
