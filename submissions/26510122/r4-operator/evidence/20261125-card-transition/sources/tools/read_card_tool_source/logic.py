import hashlib
from pathlib import Path

NAMES = {'apply_staged_card', 'stage_representative_card', 'publish_shop_info'}
FILES = {'logic.py', 'test.py'}
PAGE_SIZE = 2000
MAX_BYTES = 1024 * 1024


def run(args, kit):
    if not isinstance(args, dict) or args.keys() != {'name', 'file', 'offset'}:
        return {'error': 'invalid_arguments'}
    name, filename, offset = args['name'], args['file'], args['offset']
    if not isinstance(name, str) or name not in NAMES:
        return {'error': 'invalid_tool_name'}
    if not isinstance(filename, str) or filename not in FILES:
        return {'error': 'invalid_source_file'}
    if type(offset) is not int or offset < 0:
        return {'error': 'invalid_offset'}
    try:
        with (Path('tools') / name / filename).open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return {'error': 'source_too_large'}
        source = raw.decode('utf-8')
    except FileNotFoundError:
        return {'error': 'source_missing'}
    except (OSError, UnicodeError):
        return {'error': 'source_unreadable'}
    if offset > len(source):
        return {'error': 'offset_beyond_source'}
    end = min(offset + PAGE_SIZE, len(source))
    return {'sha256': hashlib.sha256(raw).hexdigest(), 'offset': offset,
            'next_offset': end if end < len(source) else None,
            'total_chars': len(source), 'source': source[offset:end]}
