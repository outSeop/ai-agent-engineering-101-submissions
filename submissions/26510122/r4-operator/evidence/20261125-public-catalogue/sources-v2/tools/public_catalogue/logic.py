import hashlib
import json
import math
import os
import re
import stat
import time
import unicodedata
from collections import Counter
from contextlib import ExitStack

MAX_BYTES = 2 * 1024 * 1024
MAX_UNITS = 5000
MAX_CREDITS = 10**12
FILENAME = 'customer_offer_context.json'
SKU = re.compile(r'G[0-9A-Fa-f]{8}')
LITERAL_SKU = re.compile(r'(?<![A-Za-z0-9_])G[0-9A-Fa-f]{8}(?![A-Za-z0-9_])')
HEX64 = re.compile(r'[0-9a-fA-F]{64}')
UNIT_REF = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}')
GRADES = ('A', 'B', 'C')
CONTEXT_KEYS = {'schema', 'shop', 'observed_at', 'valid_until', 'units'}
UNIT_KEYS = {'unit_ref', 'sku', 'name', 'category_path', 'state', 'grade', 'price_credits', 'standard_fee_credits', 'expires_at'}
COLUMNS = ['sku', 'grade', 'name', 'preferred_price', 'category_path', 'remaining_seconds']
COMMON = {'category': None, 'stock_status': 'available', 'available': True, 'wait_eligible': False, 'state': 'available'}
DEFAULTS = {'q': '', 'skus': [], 'exclude_skus': [], 'category': '', 'grade': '', 'max_price': MAX_CREDITS,
            'min_remaining_seconds': 0, 'sort': 'source', 'limit': 8}
CURSOR = {'snapshot', 'as_of', 'query_id'}
PRIVATE = re.compile(
    r'[@\\]|(?:https?|ftp|file|mailto|www)[:.]|[\w-]+(?:\.[\w-]+)*\.(?:com|net|org|io|ai|kr|dev|co|app|edu|gov)(?!\w)'
    r'|(?:\d{1,3}\.){3}\d{1,3}|0x[0-9a-f]{6,}|\b[0-9a-f]{16,}\b|\b[A-Za-z0-9_-]{32,}\b'
    r'|\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b|\d{2,4}[- ]\d{3,4}[- ]\d{4}'
    r'|(?<![A-Za-z0-9])(?:bearer|password|secret|private|token|mnemonic|address|owner|unit_ref|wallet|api[_ -]?key|sk[-_][\w-]+)(?![A-Za-z0-9])'
    r'|비밀|비밀번호|개인키|계좌번호|지갑주소|시드문구|[가-힣]+(?:로|길)\s*\d+|[가-힣]+(?:동|호)\s*\d+', re.I)
QUERY_PRIVATE = re.compile(
    r'(?<!\w)\.(?:env(?:\.[\w-]+)?|git(?:ignore)?|ssh|npmrc|netrc)(?!\w)'
    r'|[\w-]+\.(?:json|ya?ml|toml|ini|conf|txt|csv|log|pem|key|p12|sqlite|db|py|sh|ps1)(?!\w)'
    r'|\b\d{1,6}\s+(?:[\w-]+\s+){1,5}(?:street|st\.?|avenue|ave\.?|road|rd\.?|lane|ln\.?|drive|dr\.?|boulevard|blvd\.?)\b'
    r'|\b(?:eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|gh[pousr]_[A-Za-z0-9]+|xox[baprs]-[A-Za-z0-9-]+)\b', re.I)
MIXED = re.compile(
    r'환불|반품|구매|결제|송금|입금|출금|취소|계약|권리|권한|견적|수락|동의|대기|마일리지|포인트|잔액|계좌|지갑|가스|수수료'
    r'|흥정|협상|네고|할인|깎|최저|저렴|싸게|제외|빼고|빼줘|말고|싫|아닌|대안|대체|대신|비교|다른|보다|중에서|추천|주문|사겠|살게|사줘|살래|살까|사고 싶|보내|진행'
    r'|\b(?:refund|return|buy|purchase|order|payment|pay|transfer|cancel|contract|rights?|accept|quote|balance|wallet|credit|cheaper|cheapest|discount|except|exclude|instead|alternative|compare|versus|vs)\b', re.I)
NON_TARGET = re.compile(
    r'제외|빼고|빼줘|빼\s*주세요|말고|싫|아닌|아니고|대안|대체|대신|비교|차이|다른|보다|중에서|중\s*어느| 또는 | 혹은 '
    r'|\b(?:except|excluding|exclude|instead|alternative[s]?|compare|comparison|versus|vs|without|not|other than|rather than|or)\b', re.I)
FACT = re.compile(r'가격|상품가|등급|유통\s*기한|소비\s*기한|만료|기한|재고|남은\s*시간|\b(?:price|grade|expiry|expiration|stock)\b', re.I)
PLAIN = frozenset(('공개 상품 제품 정보 목록 문의 확인 조회 안내 알려줘 알려주세요 알려 주세요 줘 보여줘 보여주세요 '
                   '부탁해 부탁합니다 부탁드립니다 부탁드려요 궁금해 궁금해요 궁금합니다 얼마 얼마야 얼마인가요 언제 언제까지 '
                   '언제인가요 어떤 어떻게 되나요 인가요 인지 있는지 있나요 있습니까 남았나요 남았어요 뭐야 뭐예요 '
                   '은 는 이 가 을 를 의 에 에서 도 와 과 하고 랑 및 또는 그리고 좀 대한 알려주시겠어요 확인해주세요 '
                   'price grade expiry expiration stock what is the of for and please show tell me available').split())


def unavailable(reason):
    return {'status': 'unavailable', 'reason': reason}


def valid_sku(value):
    return type(value) is str and SKU.fullmatch(value) is not None


def pair_of(unit):
    if type(unit) is not dict:
        return None
    sku, grade = unit.get('sku'), unit.get('grade')
    if valid_sku(sku) and type(grade) is str and grade in GRADES:
        return sku.upper(), grade
    return None


def selection(args):
    if set(args) != {'op', 'items'}:
        return None
    items = args['items']
    if type(items) is not list or not 1 <= len(items) <= 3:
        return None
    pairs = []
    for item in items:
        if type(item) is not dict or set(item) != {'sku', 'grade'}:
            return None
        pair = pair_of(item)
        if pair is None or pair in pairs:
            return None
        pairs.append(pair)
    return pairs


def check_directory(info, uid):
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or info.st_mode & 0o022:
        raise OSError('unsafe directory')


def check_file(info, uid):
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != uid or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o400 or not 0 < info.st_size <= MAX_BYTES):
        raise OSError('unsafe file')


def identity(info):
    return info.st_dev, info.st_ino


def file_metadata(info):
    return (*identity(info), info.st_mode, info.st_uid, info.st_gid, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def read_snapshot():
    uid = os.geteuid()
    root = os.getcwd()
    base_flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
    directory_flags = base_flags | os.O_DIRECTORY
    with ExitStack() as stack:
        root_fd = os.open(root, directory_flags)
        stack.callback(os.close, root_fd)
        root_info = os.fstat(root_fd)
        check_directory(root_info, uid)
        parent_fd = os.open('host_inputs', directory_flags, dir_fd=root_fd)
        stack.callback(os.close, parent_fd)
        parent_info = os.fstat(parent_fd)
        check_directory(parent_info, uid)
        fd = os.open(FILENAME, base_flags | os.O_NONBLOCK, dir_fd=parent_fd)
        stack.callback(os.close, fd)
        before = os.fstat(fd)
        check_file(before, uid)
        data = bytearray()
        while len(data) <= before.st_size:
            chunk = os.read(fd, min(65536, before.st_size + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        after = os.fstat(fd)
        named_file = os.stat(FILENAME, dir_fd=parent_fd, follow_symlinks=False)
        named_parent = os.stat('host_inputs', dir_fd=root_fd, follow_symlinks=False)
        named_root = os.stat(root, follow_symlinks=False)
        check_file(after, uid)
        check_file(named_file, uid)
        check_directory(named_parent, uid)
        check_directory(named_root, uid)
        if (len(data) != before.st_size or file_metadata(before) != file_metadata(after)
                or file_metadata(after) != file_metadata(named_file)
                or identity(parent_info) != identity(named_parent)
                or identity(root_info) != identity(named_root)):
            raise OSError('source changed')
        return data


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate key')
        result[key] = value
    return result


def reject_number(_):
    raise ValueError('invalid number')


def integer(value, minimum=0, maximum=None):
    return type(value) is int and value >= minimum and (maximum is None or value <= maximum)


def valid_unit(unit, pair):
    if pair is None or set(unit) != UNIT_KEYS:
        return False
    ref, path = unit['unit_ref'], unit['category_path']
    fee, expiry = unit['standard_fee_credits'], unit['expires_at']
    return (type(ref) is str and UNIT_REF.fullmatch(ref) is not None and '..' not in ref
            and type(unit['name']) is str
            and (type(path) is str or (type(path) is list and all(type(part) is str for part in path)))
            and type(unit['state']) is str and bool(unit['state'])
            and integer(unit['price_credits'], 1, MAX_CREDITS)
            and (fee is None or integer(fee)) and (expiry is None or integer(expiry)))


def text_arg(value, limit):
    return type(value) is str and len(value) <= limit and all(unicodedata.category(ch) != 'Cs' for ch in value)


def sku_list(value):
    if type(value) is not list or len(value) > 20 or not all(valid_sku(sku) for sku in value):
        return None
    return unique_skus(value, sort=True)


def unique_skus(values, sort=False):
    spellings = {}
    for sku in values:
        spellings.setdefault(sku.upper(), sku)
    return [spellings[key] for key in sorted(spellings)] if sort else list(spellings.values())


def source_skus(values, spellings):
    return [spellings.get(sku.upper(), sku) for sku in values]


def search_args(args):
    if set(args) - (DEFAULTS.keys() | CURSOR | {'op', 'offset'}):
        return None
    present = CURSOR & args.keys()
    offset = args.get('offset', 0)
    if not integer(offset) or (present and present != CURSOR) or (offset and not present):
        return None
    if present and (any(type(args[key]) is not str or not HEX64.fullmatch(args[key]) for key in ('snapshot', 'query_id'))
                    or not integer(args['as_of'])):
        return None
    criteria = dict(DEFAULTS)
    criteria.update({key: args[key] for key in DEFAULTS if key in args})
    for key in ('skus', 'exclude_skus'):
        criteria[key] = sku_list(criteria[key])
        if criteria[key] is None:
            return None
    if (not text_arg(criteria['q'], 64) or not text_arg(criteria['category'], 128)
            or ('category' in args and not criteria['category'] and not present)
            or type(criteria['grade']) is not str or criteria['grade'] not in ('', *GRADES)
            or ('grade' in args and not criteria['grade'] and not present)
            or type(criteria['sort']) is not str or criteria['sort'] not in ('source', 'price_asc', 'expiry_asc')
            or not integer(criteria['limit'], 1, 8) or not integer(criteria['max_price'], 1, MAX_CREDITS)
            or not integer(criteria['min_remaining_seconds'])):
        return None
    criteria['q'] = ' '.join(criteria['q'].split())
    return criteria, offset, bool(present)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode('ascii')).hexdigest()


def safe_label(text, maximum, refs):
    if not text or len(text) > maximum or text != text.strip():
        return False
    normalized = unicodedata.normalize('NFKC', text)
    if (PRIVATE.search(normalized) or any(ch in '/:<>={}[]' for ch in normalized)
            or any(unicodedata.category(ch)[0] == 'C' or unicodedata.category(ch) in ('Zl', 'Zp') for ch in text)):
        return False
    return not any(part in refs for part in re.findall(r'[A-Za-z0-9_.:-]+', normalized.casefold()))


def index_units(units):
    pairs = [pair_of(unit) for unit in units]
    raw_pairs = Counter(pair for pair in pairs if pair is not None)
    refs = {unit['unit_ref'].casefold() for unit in units if type(unit) is dict and type(unit.get('unit_ref')) is str}
    excluded = dict(invalid_rows=0, ambiguous_pairs=sum(count > 1 for count in raw_pairs.values()),
                    ambiguous_rows=0, unavailable_rows=0)
    rows = []
    spellings = {}
    for unit, pair in zip(units, pairs):
        if not valid_unit(unit, pair):
            excluded['invalid_rows'] += 1
            continue
        if raw_pairs[pair] > 1:
            excluded['ambiguous_rows'] += 1
            continue
        spellings.setdefault(pair[0], unit['sku'])
        if unit['state'] != 'available':
            excluded['unavailable_rows'] += 1
            continue
        name = unit['name'] if safe_label(unit['name'], 1024, refs) else None
        path = unit['category_path']
        labels = path if type(path) is list else [path]
        root = labels[0] if labels and safe_label(labels[0], 128, refs) else None
        searchable = ' '.join([name or '', *(part for part in labels if safe_label(part, 128, refs))]).casefold()
        rows.append((pair, unit, name, root, searchable))
    return raw_pairs, rows, excluded, refs, spellings


def current(row, instant):
    expiry = row[1]['expires_at']
    return expiry is None or expiry > instant


def matches(eligible, criteria, instant):
    terms = criteria['q'].casefold().split()
    included = {sku.upper() for sku in criteria['skus']}
    excluded = {sku.upper() for sku in criteria['exclude_skus']}
    category, grade = criteria['category'], criteria['grade']
    minimum, maximum = criteria['min_remaining_seconds'], criteria['max_price']
    found = []
    for pair, unit, name, root, searchable in eligible:
        sku, level = pair
        expiry = unit['expires_at']
        if ((included and sku not in included) or sku in excluded or (category and category != root)
                or (grade and grade != level) or unit['price_credits'] > maximum
                or (minimum and (expiry is None or expiry - instant < minimum))
                or not all(term in searchable for term in terms)):
            continue
        found.append((pair, unit, name, root, searchable))
    if criteria['sort'] == 'price_asc':
        found.sort(key=lambda row: row[1]['price_credits'])
    if criteria['sort'] == 'expiry_asc':
        found.sort(key=lambda row: (row[1]['expires_at'] is None, row[1]['expires_at'] or 0))
    return found


def literal_hints(text, rows):
    skus = unique_skus(match.group() for match in LITERAL_SKU.finditer(text))
    root_hits = []
    for root in dict.fromkeys(row[3] for row in rows if row[3] is not None):
        pattern = r'(?<!\w)' + re.escape(root) + r'(?=(?:은|는|이|가|을|를|의|도)?(?!\w))'
        if re.search(pattern, text):
            root_hits.append((root, pattern))
    return skus, root_hits


def plain_request(text, hints, roots):
    if (not hints and len(roots) != 1) or len(roots) > 1 or MIXED.search(text) or PRIVATE.search(text):
        return False
    remainder = LITERAL_SKU.sub(' ', text)
    for _, pattern in roots:
        remainder = re.sub(pattern, ' ', remainder)
    if not FACT.search(remainder):
        return False
    remainder = FACT.sub(' ', remainder).casefold()
    return all(token in PLAIN for token in re.sub(r'[?,.!·]', ' ', remainder).split())


def render(selected, context, earliest, fallback=False):
    output_time = time.time()
    valid_until = context['valid_until']
    if not earliest <= output_time < valid_until:
        return unavailable('stale_snapshot')
    if not selected or any(not current(row, output_time) for row in selected):
        return unavailable('selection_unavailable')
    lines = ['현재 조회 목록 일부'] if fallback else []
    for (_, grade), unit, *_ in selected:
        expiry = unit['expires_at']
        remaining = ('유통기한 미제공' if expiry is None
                     else f'남은 시간 {max(0, expiry - math.ceil(output_time))}초')
        lines.append(f"{unit['sku']} {grade}등급 · {unit['price_credits']:,}크레딧 · {remaining}")
    lines.append('상품가 기준, 시장 수수료·가스 별도. 결제 전 재고·조건 재확인')
    reply = '\n'.join(lines)
    if len(reply) > 450:
        return unavailable('output_budget')
    final_time = time.time()
    if not output_time <= final_time < valid_until:
        return unavailable('stale_snapshot')
    if any(not current(row, final_time) for row in selected):
        return unavailable('selection_unavailable')
    return {'status': 'rendered', 'reply': reply, 'observed_at': context['observed_at'], 'valid_until': valid_until}


def page(context, eligible, found, criteria, cursor, excluded, hints):
    offset, snapshot, as_of, query_id = cursor
    counts = Counter(row[3] for row in eligible if row[3] is not None)
    summaries = list(counts.items())[:12]
    eligible_skus = {row[0][0] for row in eligible}
    requested = criteria['skus'] or (hints['literal_skus'] if hints is not None else [])
    missing = [sku for sku in requested if sku.upper() not in eligible_skus]
    source_count = len(context['units'])
    expired = source_count - len(eligible) - sum(excluded[key] for key in ('invalid_rows', 'ambiguous_rows', 'unavailable_rows'))
    excluded_counts = dict(excluded, expired_rows=expired, filter_rows=len(eligible) - len(found))
    public_criteria = dict(criteria, q_tokens=len(criteria['q'].split()))
    del public_criteria['q']
    if criteria['category'] and criteria['category'] not in counts:
        public_criteria['category'] = None
    selected = found[offset:offset + criteria['limit']]
    preview_limit = 24
    omitted_names = sum(row[2] is None for row in eligible)
    omitted_categories = sum(row[3] is None for row in eligible)
    while True:
        rows = []
        for (_, grade), unit, name, root, _ in selected:
            path = [root] if root is not None and type(unit['category_path']) is list else root
            expiry = unit['expires_at']
            rows.append([unit['sku'], grade, name[:preview_limit] if name is not None and preview_limit else None,
                         unit['price_credits'], path, None if expiry is None else expiry - as_of])
        next_offset = offset + len(rows)
        next_args = None
        if next_offset < len(found):
            next_args = dict(criteria, op='search', offset=next_offset, snapshot=snapshot, as_of=as_of, query_id=query_id)
        coverage = (f'공개 검색 일치 {len(found)}행 중 {offset + 1}–{next_offset}행'
                    if rows else '현재 공개 검색 조건에 일치하는 대표행 0개')
        if excluded['invalid_rows'] or excluded['ambiguous_pairs']:
            coverage += '. 검증 불완전 또는 모호한 행 제외로 공개 범위 불완전'
        catalogue = {'source_count': source_count, 'eligible_count': len(eligible), 'matched_count': len(found),
                     'offset': offset, 'returned_count': len(rows), 'next_args': next_args,
                     'category_counts': [[root, count] for root, count in summaries], 'category_counts_partial': len(summaries) < len(counts),
                     'criteria': public_criteria, 'excluded_counts': excluded_counts, 'missing_skus': missing,
                     'display_counts': {'names_omitted': omitted_names, 'categories_omitted': omitted_categories,
                                        'page_names_shortened': sum(row[2] is not None and len(row[2]) > preview_limit for row in selected)},
                     'name_preview_limit': preview_limit,
                     'coverage': '공개 대표행 기준. 이름은 미리보기이며 분류는 공개 최상위 라벨만 표시합니다.',
                     'search': '다른 상품이나 더 넓은 범위는 새 search에서 조회하세요. 다음 페이지는 next_args 전체를 사용하세요.'}
        if hints is not None:
            catalogue['hints'] = hints
        result = {'status': 'ready', 'coverage': coverage, 'observed_at': context['observed_at'], 'as_of': as_of,
                  'valid_until': context['valid_until'], 'snapshot': snapshot, 'query_id': query_id,
                  'columns': COLUMNS, 'common': COMMON, 'lookup': {}, 'rows': rows, 'text_limit': 24, 'catalogue': catalogue}
        if len(json.dumps(result, ensure_ascii=False)) <= 5500:
            return result
        if summaries:
            summaries.pop()
        elif preview_limit:
            preview_limit = 0
        elif len(selected) > 1:
            selected.pop()
        else:
            return unavailable('output_budget')


def run(args, kit):
    if type(args) is not dict or type(args.get('op')) is not str:
        return unavailable('invalid_args')
    op = args['op']
    criteria = dict(DEFAULTS)
    offset, continuing, hints = 0, False, None
    if op == 'search':
        parsed = search_args(args)
        if parsed is None:
            return unavailable('invalid_args')
        criteria, offset, continuing = parsed
        query = criteria['q']
        if query and (not safe_label(query, 64, ()) or QUERY_PRIVATE.search(unicodedata.normalize('NFKC', query))):
            return unavailable('unsafe_query_cursor')
        if continuing and not (DEFAULTS.keys() | {'offset'}) <= args.keys():
            return unavailable('query_restart_required')
    elif op == 'render':
        requested = selection(args)
        if requested is None:
            return unavailable('invalid_args')
    elif op in ('context', 'fallback'):
        allowed = {'op', 'text', 'focus_skus'} if op == 'context' else {'op', 'text'}
        if set(args) - allowed or not text_arg(args.get('text'), 1500):
            return unavailable('invalid_args')
        focus = sku_list(args.get('focus_skus', []))
        if focus is None:
            return unavailable('invalid_args')
    else:
        return unavailable('invalid_args')
    start = time.time()
    try:
        raw = read_snapshot()
    except (OSError, AttributeError, NotImplementedError):
        return unavailable('source_unavailable')
    snapshot = hashlib.sha256(raw).hexdigest()
    if continuing and args['snapshot'].lower() != snapshot:
        return unavailable('query_restart_required')
    try:
        context = json.loads(raw.decode('utf-8'), object_pairs_hook=unique_object,
                             parse_constant=reject_number, parse_float=reject_number)
    except (ValueError, RecursionError):
        return unavailable('invalid_snapshot')
    if (type(context) is not dict or set(context) != CONTEXT_KEYS
            or context['schema'] != 'outseop-r4.customer-offers.v1' or context['shop'] != 'outseop-r4'
            or not integer(context['observed_at']) or not integer(context['valid_until'])
            or type(context['units']) is not list or len(context['units']) > MAX_UNITS):
        return unavailable('invalid_snapshot')
    observed, valid_until = context['observed_at'], context['valid_until']
    checked = time.time()
    stale_reason = 'query_restart_required' if continuing else 'stale_snapshot'
    if not observed <= start <= checked < valid_until <= observed + 150:
        return unavailable(stale_reason)
    as_of = args['as_of'] if continuing else int(checked)
    if continuing and not observed <= as_of <= int(checked):
        return unavailable('query_restart_required')
    raw_pairs, rows, excluded, refs, spellings = index_units(context['units'])
    if op == 'render':
        if any(raw_pairs[pair] > 1 for pair in requested):
            return unavailable('selection_ambiguous')
        by_pair = {row[0]: row for row in rows}
        if any(pair not in by_pair for pair in requested):
            return unavailable('selection_unavailable')
        return render([by_pair[pair] for pair in requested], context, checked)
    if criteria['q'] and not safe_label(criteria['q'], 64, refs):
        return unavailable('unsafe_query_cursor')
    eligible = [row for row in rows if current(row, as_of)]
    if op in ('context', 'fallback'):
        text = args['text']
        literal, roots = literal_hints(text, eligible)
        literal = source_skus(literal, spellings)
        if op == 'fallback':
            if len(literal) > 20 or not plain_request(text, literal, roots):
                return unavailable('fallback_not_applicable')
            criteria['skus'] = unique_skus(literal, sort=True)
            criteria['category'] = roots[0][0] if roots else ''
            found = matches(eligible, criteria, as_of)
            if not {sku.upper() for sku in literal} <= {row[0][0] for row in found}:
                return unavailable('selection_unavailable')
            return render(found[:3], context, checked, fallback=True)
        focus = source_skus(focus, spellings)
        hints = {'literal_skus': literal[:20], 'literal_skus_partial': len(literal) > 20,
                 'focus_skus': focus, 'root_hint_count': len(roots),
                 'usage': '검색 참고값이며 선택이나 구매 의사를 뜻하지 않습니다.'}
        if (literal or focus) and not NON_TARGET.search(' '.join(text.split())):
            if len(literal) > 20:
                return unavailable('invalid_args')
            criteria['skus'] = unique_skus(literal or focus, sort=True)
        elif len(roots) == 1 and not literal and not MIXED.search(text) and not NON_TARGET.search(' '.join(text.split())):
            criteria['category'] = roots[0][0]
    for key in ('skus', 'exclude_skus'):
        criteria[key] = source_skus(criteria[key], spellings)
    canonical = dict(criteria, skus=[sku.upper() for sku in criteria['skus']],
                     exclude_skus=[sku.upper() for sku in criteria['exclude_skus']])
    try:
        query_id = digest([canonical, snapshot, as_of])
    except ValueError:
        return unavailable('invalid_args')
    if continuing and args['query_id'].lower() != query_id:
        return unavailable('query_restart_required')
    found = matches(eligible, criteria, as_of)
    if offset and offset >= len(found):
        return unavailable('query_restart_required')
    try:
        result = page(context, eligible, found, criteria, (offset, snapshot, as_of, query_id), excluded, hints)
    except ValueError:
        return unavailable('output_budget')
    final_time = time.time()
    if not checked <= final_time < valid_until:
        return unavailable(stale_reason)
    if any(not current(row, final_time) for row in eligible):
        return unavailable('query_restart_required')
    minimum = criteria['min_remaining_seconds']
    if minimum and any(row[1]['expires_at'] - int(final_time) < minimum for row in found):
        return unavailable('query_restart_required')
    return result
