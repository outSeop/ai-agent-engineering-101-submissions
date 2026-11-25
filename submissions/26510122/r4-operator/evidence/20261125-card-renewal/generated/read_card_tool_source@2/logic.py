import hashlib
from pathlib import Path

ROOT = Path.cwd().resolve()
TOOL = 'apply_staged_card'
ACTIVE = frozenset({TOOL, 'stage_representative_card', 'refresh_representative_card', 'publish_shop_info'})
ARCHIVED = {
    'logic.py': '14143d58859493f56b3b736dab10fe384211d8c0c8b58a1b3db59a50a9d5500f',
    'test.py': 'c96e43d06d9d30a2548d35e59a2628d0552b2a36978fba2b8d67d715d5041e55',
}
LIMIT = 256 * 1024
PAGE = 2000


def source(name, filename):
    if name in ACTIVE:
        return load([ROOT / 'tools' / name / filename])
    paths = [
        ROOT / '.deprecated' / (TOOL + '@1') / filename,
        ROOT / 'tools' / '.deprecated' / (TOOL + '@1') / filename,
    ]
    return load(paths, ARCHIVED[filename])


def load(paths, expected=None):
    for path in paths:
        try:
            with path.open('rb') as stream:
                raw = stream.read(LIMIT + 1)
        except FileNotFoundError:
            continue
        if len(raw) > LIMIT:
            continue
        digest = hashlib.sha256(raw).hexdigest()
        if expected is None or digest == expected:
            return digest, raw.decode('utf-8')
    raise ValueError('approved_source_missing_or_changed')


def run(args, kit):
    if not isinstance(args, dict) or args.keys() != {'name', 'file', 'offset'}:
        return {'error': 'invalid_arguments'}
    name, filename, offset = args['name'], args['file'], args['offset']
    if not isinstance(name, str) or (name not in ACTIVE and name != TOOL + '@1'):
        return {'error': 'unapproved_tool'}
    if filename not in ('logic.py', 'test.py') or type(offset) is not int or offset < 0:
        return {'error': 'invalid_arguments'}
    try:
        digest, text = source(name, filename)
    except (OSError, ValueError):
        return {'error': 'approved_source_missing_or_changed'}
    if offset > len(text):
        return {'error': 'invalid_offset'}
    end = min(offset + PAGE, len(text))
    return {'sha256': digest, 'offset': offset, 'next_offset': end if end < len(text) else None, 'total_chars': len(text), 'source': text[offset:end]}
