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
from decimal import Decimal

MAX_BYTES = 2 * 1024 * 1024
MAX_UNITS = 5000
MAX_CREDITS = 10**12
NAME_LIMIT = 1024
REPLY_LIMIT = 450
PAGE_BUDGET = 5500
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
BRAND_BRACKETS = re.compile(r'\[[^\[\]]+\]')
FINANCIAL_RIGHT = re.compile(r'결제\s*권|(?:환불|정산|출금|송금)\s*권리?|checkout\s+(?:token|right|entitlement)\b', re.I)
PACK_SLASH = re.compile(
    r'(?<![A-Za-z0-9.])\d+(?:\.\d+)?\s*(?:kg|mg|g|ml|cl|l|oz|그램|킬로그램|리터|밀리리터)'
    r' */ *\d+ *(?:팩|개입|개|봉지|봉|병|포|캔|입|세트|packs?|pcs?)(?![\w./-])', re.I)
BRAND_SLASH = re.compile(r'\A\[[가-힣][가-힣A-Za-z0-9 ]{0,23}(?: */ *[가-힣][가-힣A-Za-z0-9 ]{0,23}){1,3}\](?= +[^ /])')
OPTION_SLASH = re.compile(
    r'((?<![A-Za-z0-9.])(?:[x×] *)?\d+(?:\.\d+)? *'
    r'(?:kg|mg|g|ml|cl|l|oz|그램|킬로그램|리터|밀리리터|팩|개입|개|봉지|봉|병|포|캔|입|세트|packs?|pcs?))'
    r' +(?:/ *[가-힣]{1,16}(?: +[가-힣]{1,16}){0,2} *){1,8}\Z', re.I)
MIXED = re.compile(
    r'환불|반품|구매|결제|송금|입금|출금|취소|계약|권리|권한|견적|수락|동의|대기|마일리지|포인트|잔액|계좌|지갑|가스|수수료'
    r'|흥정|협상|네고|할인|깎|최저|저렴|싸게|제외|빼고|빼줘|말고|싫|아닌|대안|대체|대신|비교|다른|보다|중에서|추천|주문|사겠|살게|사줘|살래|살까|사고 싶|보내|진행'
    r'|\b(?:refund|return|buy|purchase|order|payment|pay|transfer|cancel|contract|rights?|accept|quote|balance|wallet|credit|cheaper|cheapest|discount|except|exclude|instead|alternative|compare|versus|vs)\b', re.I)
NON_TARGET = re.compile(
    r'제외|빼고|빼줘|빼\s*주세요|말고|싫|아닌|아니고|대안|대체|대신|비교|차이|다른|보다|중에서|중\s*어느| 또는 | 혹은 '
    r'|\b(?:except|excluding|exclude|instead|alternative[s]?|compare|comparison|versus|vs|without|not|other than|rather than|or)\b', re.I)
FACT = re.compile(r'상품가|가격|등급|유통\s*기한|소비\s*기한|만료|기한|재고|남은\s*시간|상품\s*이름|제품\s*이름|상품명|제품명|포장|규격|수량|판매\s*단위|\b(?:price|grade|expiry|expiration|stock)\b', re.I)
PLAIN = frozenset(('공개 상품 제품 정보 목록 문의 확인 조회 안내 알려줘 알려주세요 알려 주세요 줘 보여줘 보여주세요 '
                   '부탁해 부탁합니다 부탁드립니다 부탁드려요 궁금해 궁금해요 궁금합니다 얼마 얼마야 얼마인가요 언제 언제까지 '
                   '언제인가요 어떤 어떻게 되나요 인가요 인지 있는지 있나요 있습니까 남았나요 남았어요 뭐야 뭐예요 '
                   '은 는 이 가 을 를 의 에 에서 도 와 과 하고 랑 및 또는 그리고 좀 대한 알려주시겠어요 확인해주세요 '
                   '한 몇 개 몇개 몇개인가요 몇 팩 몇팩 몇팩인가요 몇 개인가요 팩인가요 '
                   'price grade expiry expiration stock what is the of for and please show tell me available').split())
CONDITIONS = '상품가 기준, 시장 수수료·가스 별도. 결제 전 재고·조건 재확인.'


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
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode('ascii')
    return hashlib.sha256(encoded).hexdigest()


def safe_label(text, maximum, refs, *, product=False, query=False):
    if not text or len(text) > maximum or text != text.strip():
        return False
    normalized = unicodedata.normalize('NFKC', text)
    if (PRIVATE.search(normalized) or ((product or query) and QUERY_PRIVATE.search(normalized))
            or ((product or query) and FINANCIAL_RIGHT.search(normalized))
            or any(ch in ':<>={}' for ch in normalized)
            or any(unicodedata.category(ch)[0] == 'C' or unicodedata.category(ch) in ('Zl', 'Zp') for ch in text)):
        return False
    if (product or query) and '](' in normalized:
        return False
    bracket_check = BRAND_BRACKETS.sub(' ', normalized) if product or query else normalized
    if '[' in bracket_check or ']' in bracket_check:
        return False
    slash_check = normalized
    if product and '/' in normalized:
        # Recognize slashes only in the leading brand, a quantity-qualified option suffix, or a pack size.
        slash_check = BRAND_SLASH.sub(' ', slash_check, count=1)
        slash_check = OPTION_SLASH.sub(r'\1', slash_check, count=1)
        slash_check = PACK_SLASH.sub(' ', slash_check)
    if '/' in slash_check:
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
        name = unit['name'] if safe_label(unit['name'], NAME_LIMIT, refs, product=True) else None
        path = unit['category_path']
        labels = path if type(path) is list else [path]
        public_labels = [part for part in labels if safe_label(part, 128, refs)]
        root = labels[0] if public_labels and labels[0] == public_labels[0] else None
        searchable = ' '.join([name or '', *public_labels]).casefold()
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
    normalized = unicodedata.normalize('NFKC', ' '.join(text.split()))
    if ((not hints and len(roots) != 1) or len(roots) > 1 or MIXED.search(normalized)
            or NON_TARGET.search(normalized) or PRIVATE.search(normalized) or QUERY_PRIVATE.search(normalized)):
        return False
    remainder = LITERAL_SKU.sub(' ', text)
    for _, pattern in roots:
        remainder = re.sub(pattern, ' ', remainder)
    if not FACT.search(remainder):
        return False
    remainder = FACT.sub(' ', remainder).casefold()
    return all(token in PLAIN for token in re.sub(r'[?,.!·]', ' ', remainder).split())


def render(selected, context, earliest, partial=False):
    output_time = time.time()
    valid_until = context['valid_until']
    if not earliest <= output_time < valid_until:
        return unavailable('stale_snapshot')
    if not selected or any(not current(row, output_time) for row in selected):
        return unavailable('selection_unavailable')
    if any(row[2] is None for row in selected):
        return unavailable('name_unavailable')
    lines = ['현재 조회 목록 일부'] if partial else []
    for (_, grade), unit, name, _, _ in selected:
        expiry = unit['expires_at']
        remaining = ('유통기한 미제공' if expiry is None
                     else f'남은 시간 {max(0, expiry - math.ceil(output_time))}초')
        lines.append(f"{unit['sku']} {grade}등급 · {name} · {unit['price_credits']:,}크레딧 · {remaining}")
    if len(selected) == 1:
        sku = selected[0][1]['sku']
        purchase = f"지금 구매하려면 A2A로 '구매 {sku}'를 보내"
    else:
        purchase = "지금 구매하려면 위 SKU 중 하나를 골라 A2A로 '구매 <원하는 SKU>' 형식으로 보내"
    lines.extend(('각 상품의 시장 판매 단위는 표시된 구성 전체 1개입니다.', CONDITIONS,
                  purchase + ' 결제권과 checkout 조건을 확인하세요.'))
    reply = '\n'.join(lines)
    if len(reply) > REPLY_LIMIT:
        return unavailable('output_budget')
    final_time = time.time()
    if not output_time <= final_time < valid_until:
        return unavailable('stale_snapshot')
    if any(not current(row, final_time) for row in selected):
        return unavailable('selection_unavailable')
    return {'status': 'rendered', 'reply': reply, 'observed_at': context['observed_at'], 'valid_until': valid_until}


# Preparation only uses explicit public qualifiers and a small product vocabulary.
NUTS = frozenset(('아몬드', '호두', '캐슈넛', '피스타치오', '마카다미아', '헤이즐넛', '피칸', '브라질너트', '땅콩'))
TERMS = NUTS | {'견과류', '견과', '백미', '쌀', '현미', '찹쌀', '육류', '고기', '닭가슴살',
                 '닭고기', '돼지고기', '소고기', '쇠고기', '한우', '삼겹살', '두부', '참치', '사과'}
MEATS = frozenset(('닭가슴살', '닭고기', '돼지고기', '소고기', '쇠고기', '한우', '삼겹살'))
TERM_WORDS = '|'.join(sorted(TERMS, key=lambda word: (-len(word), word)))
PARTICLE = r'(?:으로|에서|하고|이랑|만|은|는|이|가|을|를|의|도|과|와|랑|에)?'
TERM_QUERY = re.compile(r'(?<!\w)(?:' + TERM_WORDS + r')(?=' + PARTICLE + r'(?!\w))')
TERM_PUBLIC = re.compile(r'(?<![가-힣A-Za-z])(?:' + TERM_WORDS + r')(?![가-힣A-Za-z])')
RICE_PUBLIC = re.compile(r'(?<![가-힣A-Za-z])(?:햅쌀|국산쌀|쌀명당)(?![가-힣A-Za-z])')
QUANTITY = re.compile(
    r'(?<![0-9.,+\-])(?:[x×]\s*)?([0-9]{1,8}(?:\.[0-9]{1,4})?)\s*'
    r'(밀리리터|킬로그램|그램|리터|개입|봉지|세트|packs?|pcs?|kg|mg|ml|cl|oz|g|l|팩|개|봉|병|포|캔|입)'
    r'(?=' + PARTICLE + r'(?![가-힣A-Za-z0-9.]))', re.I)
UNITS = {'킬로그램': 'kg', '그램': 'g', '밀리리터': 'ml', '리터': 'l', '개입': '개',
         '입': '개', 'pcs': '개', 'pc': '개', '팩': '팩', 'pack': '팩', 'packs': '팩', '봉지': '봉'}
GRADE_REQUEST = re.compile(r'(?<![\w+-])([ABC])\s*등급', re.I)
PRICE_REQUEST = re.compile(r'(?<![0-9.,+\-])([0-9]{1,13}|[0-9]{1,3}(?:,[0-9]{3}){1,4})\s*크레딧\s*(이하|미만|이내|이상|초과|정확히|딱|짜리)?(?![가-힣A-Za-z0-9])')
TIME_REQUEST = re.compile(r'(?<![0-9.,+\-])([0-9]{1,10})\s*(일|시간|분|초)\s*(이상|초과|이하|미만)(?![가-힣A-Za-z0-9])')
TIME_SCALE = {'일': 86400, '시간': 3600, '분': 60, '초': 1}
UNKNOWN_FACT = re.compile(r'사진|이미지|성분|원재료|재료|알레르|알러지|알러젠|함유|무첨가|무염|무가당|무설탕|교차|원산지|산지|국산|유기농|배송|택배|도착|예약|호환|채식|비건|글루텐|보관|냉장|냉동|파손|수수료|가스|\b(?:photo|image|ingredient[s]?|allerg\w*|origin|shipping|delivery|reservation|compatible|vegan)\b', re.I)
NO_ALTERNATIVE = re.compile(r'(?:대안|대체(?:품)?|다른\s*상품)(?:은|는|도|을|를)?\s*(?:없이|없어도|없으면|필요\s*없|말고|제외|싫|금지|원하지\s*않|안\s*돼|보여주지|빼)|\b(?:no|without)\s+(?:alternatives?|substitutes?|substitutions?)\b', re.I)
EXCLUSION = re.compile(r'\s*' + PARTICLE + r'\s*(?:제외(?:하고)?|빼고|빼줘|빼\s*주세요|말고|아닌|아니고|싫어요|싫어)')
UNPARSED_EXCLUSION = re.compile(r'제외|빼고|빼줘|빼\s*주세요|말고|아닌|아니고|싫|\b(?:except|excluding|exclude|without|not|other than|rather than)\b', re.I)
OTHER_REQUEST = re.compile(r'비교|차이| 또는 | 혹은 |\b(?:compare|versus|vs|or)\b', re.I)
PREP_PLAIN = PLAIN | frozenset(('찾아 찾아줘 찾아주세요 추천 추천해 추천해주세요 있으면 있나요 없나요 있으면요 '
                              '보여 주세요 가능한 가능한가요 판매 판매하나요 팝니까 있나 원해요 원합니다 '
                              '있어요 있는 있습니까 부탁 필요해요 싶어요 주세요 제품으로 상품으로 '
                              '대안 대체품 대체 대신 다른 상품만 가능 있어요 무엇 어떤가요 남은 최소 최대 '
                              '정확히 딱 상품만 제품만 만 후보 후보만 것 것만 기간 기한이 남아 '
                              '색상 목록을 보고 체크 알려 한정 가능하면').split())


def quantities(text):
    return {(Decimal(match[1]), UNITS.get(match[2].lower(), match[2].lower()))
            for match in QUANTITY.finditer(text)}


def related_term(term, public_terms):
    if term == '백미':
        return '쌀' in public_terms and not public_terms.intersection({'현미', '찹쌀'})
    if term == '쌀':
        return bool(public_terms.intersection({'백미', '현미', '찹쌀'}))
    if term in {'견과', '견과류'}:
        return bool(public_terms.intersection(NUTS | {'견과', '견과류'}))
    if term in {'육류', '고기'}:
        return bool(public_terms.intersection(MEATS | {'육류', '고기'}))
    return False


def at_limit(value, requested, bound):
    if bound in ('이하', '이내'):
        return value <= requested
    if bound == '미만':
        return value < requested
    if bound == '이상':
        return value >= requested
    if bound == '초과':
        return value > requested
    return value == requested


def prepare_candidates(text, focus, eligible, spellings, refs, as_of):
    normalized = unicodedata.normalize('NFKC', ' '.join(text.split()))
    literal, roots = literal_hints(normalized, eligible)
    specific_only = bool(NO_ALTERNATIVE.search(normalized))
    request = NO_ALTERNATIVE.sub(' ', normalized)
    request = re.sub(r'(?:없으면|없다면)\s*(?:됐어요|괜찮아요|필요\s*없어요|보여주지\s*마세요|추천하지\s*마세요)', ' ', request)
    specific_only |= request != NO_ALTERNATIVE.sub(' ', normalized)
    root_patterns = [pattern for _, pattern in roots]
    negative_skus, negative_terms, negative_packs, negative_roots = set(), set(), set(), set()
    mentions = {match.span(): 'sku' for match in LITERAL_SKU.finditer(request)}
    mentions.update({match.span(): 'term' for match in TERM_QUERY.finditer(request)})
    mentions.update({match.span(): 'pack' for match in QUANTITY.finditer(request)})
    for pattern in root_patterns:
        for match in re.finditer(pattern, request):
            mentions.setdefault(match.span(), 'root')
    for (begin, end), kind in sorted(mentions.items(), reverse=True):
        exclusion = EXCLUSION.match(request, end)
        if exclusion is None:
            continue
        value = request[begin:end]
        if kind == 'sku':
            negative_skus.add(value.upper())
        elif kind == 'pack':
            negative_packs.update(quantities(value))
        elif kind == 'term':
            negative_terms.add(value)
        else:
            negative_roots.add(value)
        request = request[:begin] + ' ' * (exclusion.end() - begin) + request[exclusion.end():]
    explicit = unique_skus(match.group() for match in LITERAL_SKU.finditer(request))
    requested = list(dict.fromkeys(sku.upper() for sku in (explicit or focus) if sku.upper() not in negative_skus))
    available_skus = {row[0][0] for row in eligible}
    missing = any(sku not in available_skus for sku in requested)
    terms = {match.group() for match in TERM_QUERY.finditer(request)}
    root_hits = {root for root, pattern in roots if re.search(pattern, request)}
    packs = quantities(request)
    grades = {match[1].upper() for match in GRADE_REQUEST.finditer(request)}
    prices = [(int(match[1].replace(',', '')), match[2]) for match in PRICE_REQUEST.finditer(request)]
    remaining = [(int(match[1]) * TIME_SCALE[match[2]], match[3]) for match in TIME_REQUEST.finditer(request)]
    has_constraints = bool(packs or grades or prices or remaining)
    unsafe = bool(PRIVATE.search(normalized) or QUERY_PRIVATE.search(normalized) or FINANCIAL_RIGHT.search(normalized)
                  or any(unicodedata.category(ch)[0] == 'C' for ch in normalized)
                  or any(token in refs for token in re.findall(r'[A-Za-z0-9_.:-]+', normalized.casefold())))
    unresolved_exclusion = bool(UNPARSED_EXCLUSION.search(request))
    ambiguous = bool(OTHER_REQUEST.search(request))
    remainder = request
    # Strip only recognized spans so arbitrary words cannot become selectors.
    for pattern in (LITERAL_SKU, PRICE_REQUEST, TIME_REQUEST, GRADE_REQUEST, QUANTITY, TERM_QUERY, *root_patterns):
        remainder = re.sub(pattern, ' ', remainder)
    remainder = re.sub(r'(?:상품|제품|목록|정보|재고|가격|추천|요청|대안|대체품|포장|규격|수량)' + PARTICLE + r'(?!\w)', ' ', remainder)
    remainder = FACT.sub(' ', remainder).casefold()
    tokens = re.findall(r'\w+', remainder)
    unknown = bool(unsafe or unresolved_exclusion or ambiguous or UNKNOWN_FACT.search(normalized)
                   or any(token not in PREP_PLAIN for token in tokens))
    present_target = any(sku in available_skus for sku in requested)
    strict_missing = specific_only or bool(packs and requested and not (terms or root_hits))
    fits = []
    if not unsafe and not unresolved_exclusion and not ambiguous and len(grades) <= 1:
        target_order = {sku: position for position, sku in enumerate(requested)}
        for row in eligible:
            (sku, grade), unit, name, root, searchable = row
            direct = sku in target_order
            if (sku in negative_skus or root in negative_roots or (grades and grade not in grades)
                    or (not direct and (present_target or (requested and strict_missing)))):
                continue
            expiry = unit['expires_at']
            if any(not at_limit(unit['price_credits'], value, bound) for value, bound in prices):
                continue
            if remaining and (expiry is None or any(not at_limit(expiry - as_of, value, bound) for value, bound in remaining)):
                continue
            public_name = unicodedata.normalize('NFKC', name)
            public_text = unicodedata.normalize('NFKC', searchable)
            row_terms = set(TERM_PUBLIC.findall(public_text))
            name_terms = set(TERM_PUBLIC.findall(public_name))
            # Aliases support matching and exclusions without becoming literal evidence.
            aliases = {'쌀'} if RICE_PUBLIC.search(public_text) else set()
            public_terms = row_terms | aliases
            if public_terms & negative_terms or any(related_term(term, public_terms) for term in negative_terms):
                continue
            name_packs = quantities(public_name)
            if packs - name_packs or name_packs & negative_packs:
                continue
            literal_terms = terms & name_terms
            related = (terms & aliases) | {term for term in terms if related_term(term, public_terms)}
            category_hit = root in root_hits or bool(terms & row_terms) or bool(related)
            if terms - (row_terms | related) or (root_hits and root not in root_hits):
                continue
            if direct:
                kind, rank = 'exact_sku', 0
            elif not category_hit:
                continue
            elif requested or terms - row_terms or (terms & aliases) - name_terms:
                kind, rank = 'category_alternative', 3
            elif packs and terms <= name_terms and literal_terms:
                kind, rank = 'named_pack', 1
            else:
                kind, rank = 'related_literal', 2
            extra_nuts = len((name_terms & NUTS) - terms) if terms & NUTS else 0
            rank_key = (rank, target_order.get(sku, len(requested)), not bool(literal_terms), extra_nuts, len(public_name))
            fits.append((rank_key, row, kind))
    fits.sort(key=lambda fit: fit[0])
    hints = {'literal_skus': source_skus(literal[:20], spellings), 'literal_skus_partial': len(literal) > 20,
             'focus_skus': source_skus(focus, spellings), 'root_hint_count': len(roots),
             'usage': '검색 참고값이며 선택이나 구매 의사를 뜻하지 않습니다.',
             'preparation': {'fits': [], 'requested_sku_missing': missing,
                             'constraints_unverified': bool(unknown or len(grades) > 1)}}
    exact_request = len(explicit) == 1 and not terms and not root_hits
    category_request = not explicit and (len(terms) == 1 or (not terms and len(root_hits) == 1))
    safe_fallback = ((exact_request or category_request) and not (missing or unknown or has_constraints or specific_only
                     or negative_skus or negative_terms or negative_packs or negative_roots)
                     and not MIXED.search(normalized) and not NON_TARGET.search(normalized)
                     and bool(FACT.search(normalized)) and bool(fits)
                     and all(kind != 'category_alternative' for _, _, kind in fits))
    return fits, hints, requested, remaining, safe_fallback


def page(context, eligible, found, criteria, cursor, excluded, hints, preparation=None):
    offset, snapshot, as_of, query_id = cursor
    counts = Counter(row[3] for row in eligible if row[3] is not None)
    summaries = list(counts.items())[:12]
    eligible_skus = {row[0][0] for row in eligible}
    requested = criteria['skus'] or (hints['literal_skus'] if hints is not None else [])
    missing = [sku for sku in requested if sku.upper() not in eligible_skus]
    source_count = len(context['units'])
    public_criteria = dict(criteria, q_tokens=len(criteria['q'].split()))
    del public_criteria['q']
    if criteria['category'] and criteria['category'] not in counts:
        public_criteria['category'] = None
    selected = found[offset:offset + criteria['limit']]
    while True:
        rows = []
        for (_, grade), unit, name, root, _ in selected:
            path = [root] if root is not None and type(unit['category_path']) is list else root
            expiry = unit['expires_at']
            rows.append([unit['sku'], grade, name, unit['price_credits'], path, None if expiry is None else expiry - as_of])
        next_offset = offset + len(rows)
        next_args = None
        if preparation is None and next_offset < len(found):
            next_args = dict(criteria, op='search', offset=next_offset, snapshot=snapshot, as_of=as_of, query_id=query_id)
        coverage = (f'공개 검색 일치 {len(found)}행 중 {offset + 1}–{next_offset}행'
                    if rows else '현재 공개 검색 조건에 일치하는 대표행 0개')
        if excluded['invalid_rows'] or excluded['ambiguous_pairs'] or excluded['name_unavailable_rows']:
            coverage += '. 검증 불완전 또는 모호한 행 제외로 공개 범위 불완전'
        catalogue = {'source_count': source_count, 'eligible_count': len(eligible), 'matched_count': len(found),
                     'offset': offset, 'returned_count': len(rows), 'next_args': next_args,
                     'category_counts': [[root, count] for root, count in summaries], 'category_counts_partial': len(summaries) < len(counts),
                     'criteria': public_criteria, 'excluded_counts': dict(excluded, filter_rows=len(eligible) - len(found)),
                     'missing_skus': missing,
                     'display_counts': {'names_omitted': excluded['name_unavailable_rows'],
                                        'categories_omitted': sum(row[3] is None for row in eligible), 'page_names_shortened': 0},
                     'name_preview_limit': NAME_LIMIT,
                     'coverage': '공개 대표행 기준. 검증된 상품명은 전체 원문을 표시합니다. 분류는 최상위 공개 라벨입니다.',
                     'search': '다른 상품이나 더 넓은 범위는 새 search에서 조회하세요. 다음 페이지는 next_args 전체를 사용하세요.'}
        if hints is not None:
            catalogue['hints'] = hints
        if preparation is not None:
            hints['preparation']['fits'] = [{'sku': row[1]['sku'], 'grade': row[0][1], 'kind': preparation[row[0]]}
                                            for row in selected]
            catalogue['search'] = '준비된 후보 페이지입니다. 별도 검색은 search를 사용하세요.'
        result = {'status': 'ready', 'coverage': coverage, 'observed_at': context['observed_at'], 'as_of': as_of,
                  'valid_until': context['valid_until'], 'snapshot': snapshot, 'query_id': query_id,
                  'columns': COLUMNS, 'common': COMMON, 'lookup': {}, 'rows': rows, 'text_limit': NAME_LIMIT, 'catalogue': catalogue}
        size = len(json.dumps(result, ensure_ascii=False))
        if size < PAGE_BUDGET or (preparation is None and size == PAGE_BUDGET):
            return result
        if summaries:
            summaries.pop()
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
        if query and not safe_label(query, 64, (), query=True):
            return unavailable('unsafe_query_cursor')
        if continuing and not (DEFAULTS.keys() | {'offset'}) <= args.keys():
            return unavailable('query_restart_required')
    elif op == 'render':
        requested = selection(args)
        if requested is None:
            return unavailable('invalid_args')
    elif op in ('context', 'fallback', 'prepare', 'prepared_fallback'):
        allowed = {'op', 'text', 'focus_skus'} if op in ('context', 'prepare') else {'op', 'text'}
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
    if criteria['q'] and not safe_label(criteria['q'], 64, refs, query=True):
        return unavailable('unsafe_query_cursor')
    active = [row for row in rows if current(row, as_of)]
    eligible = [row for row in active if row[2] is not None]
    excluded.update(expired_rows=len(rows) - len(active), name_unavailable_rows=len(active) - len(eligible))
    if op in ('prepare', 'prepared_fallback'):
        fits, hints, requested, remaining, safe_fallback = prepare_candidates(args['text'], focus, eligible, spellings, refs, as_of)
        found = [row for _, row, _ in fits]
        if op == 'prepared_fallback':
            incomplete_target = requested and (
                len(found) > 3 or any(sku in requested and count > 1 for (sku, _), count in raw_pairs.items())
                or any(row[0][0] in requested and row[2] is None for row in active))
            if not safe_fallback or incomplete_target:
                return unavailable('fallback_not_applicable')
            if not requested and len({row[0][0] for row in found}) != 1:
                return unavailable('fallback_not_applicable')
            if len(found) > 3:
                return unavailable('fallback_not_applicable')
            return render(found, context, checked)
        kinds = {row[0]: kind for _, row, kind in fits}
        criteria['skus'] = source_skus(requested[:20], spellings)
        cursor = (0, snapshot, as_of, digest(['prepare', snapshot, as_of,
                   criteria['skus'], [(row[0], kinds[row[0]]) for row in found], hints['preparation']]))
        result = page(context, eligible, found, criteria, cursor, excluded, hints, preparation=kinds)
        final_time = time.time()
        if not checked <= final_time < valid_until:
            return unavailable('stale_snapshot')
        if any(not current(row, final_time) for row in found):
            return unavailable('query_restart_required')
        if remaining and any(not at_limit(row[1]['expires_at'] - int(final_time), value, bound)
                             for row in found for value, bound in remaining):
            return unavailable('query_restart_required')
        return result
    if op in ('context', 'fallback'):
        text = args['text']
        literal, roots = literal_hints(text, active)
        literal = source_skus(literal, spellings)
        if op == 'fallback':
            if len(literal) > 20 or not plain_request(text, literal, roots):
                return unavailable('fallback_not_applicable')
            criteria['skus'] = unique_skus(literal, sort=True)
            criteria['category'] = roots[0][0] if roots else ''
            found = matches(active, criteria, as_of)
            targets = {sku.upper() for sku in literal}
            if (not targets <= {row[0][0] for row in found}
                    or any(sku in targets and count > 1 for (sku, _), count in raw_pairs.items())):
                return unavailable('selection_unavailable')
            if targets and len(found) > 3:
                return unavailable('selection_limit')
            return render(found[:3], context, checked, partial=len(found) > 3)
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
    if any(not current(row, final_time) for row in active):
        return unavailable('query_restart_required')
    minimum = criteria['min_remaining_seconds']
    if minimum and any(row[1]['expires_at'] - int(final_time) < minimum for row in found):
        return unavailable('query_restart_required')
    return result
