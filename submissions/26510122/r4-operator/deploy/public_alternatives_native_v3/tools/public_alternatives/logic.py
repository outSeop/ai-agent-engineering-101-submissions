import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
import unicodedata


PIN = '01a4a0dc912e02679091a3f6c98df3f0450ca2581b920d1d650e2fa0fa2a4c89'
CATALOGUE_KEYS = {'schema', 'shop', 'observed_at', 'valid_until', 'units'}
UNIT_KEYS = {'unit_ref', 'sku', 'name', 'category_path', 'state', 'grade', 'price_credits', 'standard_fee_credits', 'expires_at'}
STOCK_KEYS = {'schema', 'snapshot', 'observed_at', 'valid_until', 'rows'}
STOCK_ROW_KEYS = {'sku', 'grade', 'stock_status', 'expires_at', 'preferred_price'}
STOCK_STATES = {'available', 'reserved_pending', 'reconciling'}
STOCK_LIMIT = 2 * 1024 * 1024
SKU = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z', re.ASCII)
GRADE = re.compile(r'[A-Z][A-Z0-9+-]{0,7}\Z', re.ASCII)
CODE = re.compile(r'(?<![A-Za-z0-9_.-])(?=[A-Za-z0-9_.-]*[0-9])[A-Za-z][A-Za-z0-9_.-]{1,63}(?![A-Za-z0-9_.-])', re.ASCII)
EXPLICIT_CODE = re.compile(r'(?i)(?<![A-Za-z0-9])(?:sku|상품\s*코드|품목\s*코드|모델\s*번호|코드)\s*[:#]?\s*([A-Za-z0-9][A-Za-z0-9_.-]{0,63})')
PUBLIC_FIELD = re.compile(r'실\s*재고|재고|가격|정가|판매가|표시\s*가격|등급|유통\s*기한|소비\s*기한|사용\s*기한|만료\s*(?:일|시각|시간)?|잔여\s*기간|남은\s*기간|있나요|있습니까|있어요|있을까요|파나요|판매\s*중|얼마|\b(?:stock|price|grade|expiry|availability)\b', re.I)
PUBLIC_TAIL = re.compile(r'(?:\s|[?!.,~·/()&]|실|재고|가격|정가|판매가|표시|공개|현재|상품|정보|여부|가|이|를|을|에|의|와|과|랑|및|도|은|는|하고|함께|만료|시각|날짜|시간|일자|일|등급|유통|소비|사용|기한|잔여|남은|기간|얼마|인지|언제|까지|인지요|예요|인가요|입니까|이에요|있나요|있습니까|있어요|있을까요|파나요|판매|중|인가|알려|주세요|주실|수|있나요|확인|부탁|드립니다|합니다|궁금|보고|싶어요|요|stock|price|grade|expiry|availability|and|or|please|what|is|how|much|in|available)+\Z', re.I)
SUBJECT = re.compile(r'[가-힣A-Za-z0-9][가-힣A-Za-z0-9 ._+&()·/-]{0,139}\Z')
DENY_COMPACT = re.compile(r'말고|빼고|제외|제한|제약|미만|이상|이하|초과|최소|최대|적어도|적어두|적어도|적어|이내|가급적|되도록|선호|저렴|싼|비싼|긴기한|오래가는|신선한|충분히|넉넉히|정확히|반드시|꼭|필수|같은것|동일|정품|원래것만|해당품만|그것만|그상품만|그제품만|다른건|다른거는|다른상품은|다른제품은|안돼|안되|싫|없으면|없어도|안알려|필요없|원치않|원하지않|추천하지|제안하지|대체하지|제공하지|받지않|보여주지|아니면|아닌|아니고|원본만|에서만|구매|주문|결제|체크아웃|송금|이체|입금|출금|환불|반품|지갑|계좌|주소|서명|증명|증빙|영수증|인증|토큰|비공개|개인정보|권한|관리자|내부|예약|잠금|보류|원본파일|스냅샷|공급처|실물번호|실물참조|단위참조|시리얼|일련번호|재고수량|재고개수|알레르|과민|질환|복용|섭취|성분|무첨가|글루텐|비건|임산부|어린이용|건강|치료|의료|설치|장착|호환|맞는지|사용가능|작동|연결|규격|용량|배송|배달|돈|예산|할인|쿠폰|보장|보증|기준|조건|맞춰|지침|프롬프트|무시|실행')
DENY_WORD = re.compile(r'\b(?:no|not|never|without|except|exclude|excluding|only|exact|must|require|required|minimum|maximum|under|over|below|above|at\s+least|at\s+most|allergy|allergic|health|medical|install\w*|compatib\w*|fit|proof|private|refund|payment|pay|order|checkout|transfer|wallet|sign\w*|token|reserve\w*|quantity|budget|units?|credits?|replace|ignore|execute)\b', re.I)
REQUIREMENT = re.compile(r'(?:[0-9]|한|두|세|네|다섯|여섯|일곱|여덟|아홉|열|하나|둘|셋|몇)\s*(?:개|개입|팩|세트|박스|상자|병|봉|묶음|인분|원|크레딧|일|주|개월|달|년|시간|분|초|kg|mg|ml|g|l)(?![A-Za-z])|[A-Z]\s*(?:급|등급)|[₩$€£%<>＝=]|(?:대체(?:품|상품|안)?|대안|다른\s*(?:상품|제품|물건|것))\s*(?:은|는|도|이|가|를|을)?\s*(?:안|없|불가|금지|사양|빼|제외|말|거절)|(?:[가-힣]{2,}|[A-Za-z0-9-]+)\s*만(?=\s|$|[,.!?]|알려|보여|확인|원해|찾아|주세요)', re.I)


class Unavailable(Exception):
    pass


def require(condition, reason='source_unavailable'):
    if not condition:
        raise Unavailable(reason)


def exact_keys(value, keys):
    return type(value) is dict and value.keys() == keys


def integer_or_null(value):
    return value is None or type(value) is int


def valid_window(document, checked):
    start = document['observed_at']
    end = document['valid_until']
    return type(start) is int and type(end) is int and 0 <= start <= checked < end <= start + 150


def agent_directory():
    filename = globals().get('__file__')
    if filename:
        location = Path(filename).absolute()
        if location.parent.name == 'public_alternatives' and location.parent.parent.name == 'tools':
            return location.parent.parent.parent
    return Path.cwd()


def load_native(base):
    path = base / 'tools' / 'public_catalogue' / 'logic.py'
    with path.open('rb') as stream:
        source = stream.read(1024 * 1024 + 1)
    require(len(source) <= 1024 * 1024 and hashlib.sha256(source).hexdigest() == PIN)
    native = {'__file__': str(path), '__name__': '_pinned_public_catalogue'}
    exec(compile(source, str(path), 'exec', dont_inherit=True), native)
    return native


def load_json(raw, native):
    return json.loads(raw.decode('utf-8'), object_pairs_hook=native['unique_object'], parse_float=native['reject_number'], parse_constant=native['reject_number'])


def read_stock(base):
    uid = os.geteuid()
    directory = os.open(base / 'host_inputs', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parent = os.fstat(directory)
        require(stat.S_ISDIR(parent.st_mode) and parent.st_uid == uid and not parent.st_mode & 0o077)
        descriptor = os.open('stock-state.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(descriptor, 'rb') as stream:
            before = os.fstat(stream.fileno())
            require(stat.S_ISREG(before.st_mode) and before.st_uid == uid and before.st_nlink == 1 and stat.S_IMODE(before.st_mode) == 0o400)
            require(0 < before.st_size <= STOCK_LIMIT)
            raw = stream.read(STOCK_LIMIT + 1)
            after = os.fstat(stream.fileno())
            named = os.stat('stock-state.json', dir_fd=directory, follow_symlinks=False)
            require(before == after and after == named and len(raw) == after.st_size)
            require(before.st_mtime_ns == after.st_mtime_ns == named.st_mtime_ns and before.st_ctime_ns == after.st_ctime_ns == named.st_ctime_ns)
            return raw
    finally:
        os.close(directory)


def pair_of(sku, grade):
    require(type(sku) is str and SKU.fullmatch(sku) is not None and type(grade) is str and GRADE.fullmatch(grade) is not None)
    return sku.upper(), grade


def catalogue_units(document, native, checked):
    require(exact_keys(document, CATALOGUE_KEYS) and set(native['CONTEXT_KEYS']) == CATALOGUE_KEYS)
    require(document['schema'] == 'outseop-r4.customer-offers.v1' and document['shop'] == 'outseop-r4')
    require(valid_window(document, checked) and type(document['units']) is list)
    units = {}
    refs = set()
    for unit in document['units']:
        require(exact_keys(unit, UNIT_KEYS))
        pair = pair_of(unit['sku'], unit['grade'])
        ref = unit['unit_ref']
        require(type(ref) is str and bool(ref) and ref.casefold() not in refs and pair not in units)
        require(type(unit['name']) is str and type(unit['state']) is str)
        path = unit['category_path']
        require(path is None or type(path) is str or (type(path) is list and all(type(label) is str for label in path)))
        require(all(integer_or_null(unit[key]) for key in ('price_credits', 'standard_fee_credits', 'expires_at')))
        refs.add(ref.casefold())
        units[pair] = unit
    return units, refs


def stock_rows(raw, native, document, snapshot):
    stock = load_json(raw, native)
    require(exact_keys(stock, STOCK_KEYS) and stock['schema'] == 'outseop-r4.public-stock-state.v1')
    require(stock['snapshot'] == snapshot and all(type(stock[key]) is int and stock[key] == document[key] for key in ('observed_at', 'valid_until')))
    require(type(stock['rows']) is list and len(stock['rows']) <= 5000)
    indexed = {}
    for row in stock['rows']:
        require(exact_keys(row, STOCK_ROW_KEYS))
        pair = pair_of(row['sku'], row['grade'])
        require(pair not in indexed and type(row['stock_status']) is str and row['stock_status'] in STOCK_STATES)
        require(integer_or_null(row['expires_at']) and integer_or_null(row['preferred_price']))
        indexed[pair] = row
    return indexed


def normalized(text):
    return unicodedata.normalize('NFKC', text).casefold()


def exposes_reference(text, refs):
    folded = normalized(text)
    for ref in refs:
        ref = normalized(ref)
        if len(ref) >= 6 and ref in folded:
            return True
        if len(ref) < 6 and re.search(r'(?<![\w.-])' + re.escape(ref) + r'(?![\w.-])', folded):
            return True
    return False


def inquiry(text, native, refs, raw_refs):
    require(type(text) is str and 1 <= len(text) <= 1500 and all(not unicodedata.category(char).startswith('C') for char in text), 'unsupported_inquiry')
    require(not exposes_reference(text, raw_refs), 'unsupported_inquiry')
    clean = unicodedata.normalize('NFKC', text).strip()
    compact = re.sub(r'[^가-힣a-z0-9]', '', clean.casefold())
    require(not (DENY_COMPACT.search(compact) or DENY_WORD.search(clean) or REQUIREMENT.search(clean)), 'unsupported_inquiry')
    field = PUBLIC_FIELD.search(clean)
    require(field is not None and PUBLIC_TAIL.fullmatch(clean[field.start():]) is not None, 'unsupported_inquiry')
    subject = clean[:field.start()].strip(' ,:?!')
    subject = re.sub(r'\s+(?:상품의|제품의|품목의|에\s*대한|의|은|는|이|가|의\s*현재|현재|공개|표시)$', '', subject).strip()
    require(bool(subject), 'clarification_required')
    explicit_codes = {match.group(1).upper() for match in EXPLICIT_CODE.finditer(subject)}
    remainder = EXPLICIT_CODE.sub(' ', subject)
    codes = explicit_codes | {match.group().upper() for match in CODE.finditer(remainder)}
    remainder = CODE.sub(' ', remainder)
    remainder = re.sub(r'(?:^|\s)(?:제품|상품|품목|종류|카테고리|분류)(?=\s|$)', ' ', remainder)
    remainder = ' '.join(remainder.strip(' ,:;/#-').split())
    if not codes and re.fullmatch(r'[A-Z][A-Z0-9_.-]{1,63}', remainder):
        codes.add(remainder)
        remainder = ''
    require(bool(remainder), 'clarification_required')
    require(SUBJECT.fullmatch(remainder) is not None and native['safe_label'](remainder, 140, refs, query=True), 'unsupported_inquiry')
    require(not re.search(r'\b[0-9]+\b', remainder), 'unsupported_inquiry')
    return subject, remainder, codes


def literal_label(text, label):
    return re.search(r'(?<!\w)' + re.escape(normalized(label)) + r'(?=$|[^\w]|(?:의|은|는|이|가|을|를)(?:$|[^\w]))', normalized(text)) is not None


def native_prepare(native, text, kit):
    result = native['run']({'op': 'prepare', 'text': text}, kit)
    require(type(result) is dict and type(result.get('catalogue')) is dict, 'unsupported_inquiry')
    catalogue = result['catalogue']
    for record in (result, catalogue):
        status = str(record.get('status', '')).casefold()
        require(not any(term in status for term in ('protect', 'ambig', 'reject', 'denied', 'invalid', 'unsupported', 'error', 'unsafe', 'blocked', 'refus', 'private', 'checkout')), 'unsupported_inquiry')
    count = catalogue.get('matched_count')
    require(type(count) is int and count >= 0, 'unsupported_inquiry')
    require(count == 0, 'original_match')


def public_category(unit, root, native, refs, raw_refs):
    path = unit['category_path']
    if root is None:
        require(not path, 'unsafe_label')
        return None
    require(type(root) is str and bool(root) and native['safe_label'](root, 140, refs) and not exposes_reference(root, raw_refs), 'unsafe_label')
    if type(path) is list:
        require(bool(path) and root == path[0], 'unsafe_label')
    else:
        require(type(path) is str and root in [label.strip() for label in re.split(r'\s*(?:>|/|›)\s*', path)[:1]], 'unsafe_label')
    return root


def eligible(row, unit, stock, native, checked):
    pair = row[0]
    confirmation = stock.get(pair)
    price = unit['price_credits']
    return (confirmation is not None and confirmation['stock_status'] == 'available'
            and confirmation['sku'].upper() == pair[0] and confirmation['grade'] == pair[1]
            and type(price) is int and price > 0 and confirmation['preferred_price'] == price
            and confirmation['expires_at'] == unit['expires_at'] and native['current'](row, checked))


def json_size(value):
    return max(len(json.dumps(value, ensure_ascii=False)), len(json.dumps(value, ensure_ascii=True)))


def menu_for(document, snapshot, units, rows, stock, native, checked, subject, target, codes, refs, raw_refs):
    candidates = []
    categories = set()
    seen_pairs = set()
    for row in rows:
        pair, unit, name, root, _searchable = row
        require(pair not in seen_pairs and units.get(pair) == unit)
        seen_pairs.add(pair)
        try:
            category = public_category(unit, root, native, refs, raw_refs)
        except Unavailable:
            continue
        if category and literal_label(target, category):
            categories.add(category)
        if pair[0] in codes or literal_label(subject, pair[0]):
            continue
        if not eligible(row, unit, stock, native, checked):
            continue
        if (type(name) is not str or not name or name != unit['name']
                or (not native['safe_label'](name, 140, refs, product=True))
                or exposes_reference(name, raw_refs) or exposes_reference(pair[0], raw_refs)
                or exposes_reference(pair[1], raw_refs)):
            continue
        if literal_label(subject, name):
            raise Unavailable("original_match")
        item = {'sku': pair[0], 'name': name, 'category': category, 'grade': pair[1], 'preferred_price': unit['price_credits'], 'expires_at': unit['expires_at']}
        candidates.append((item, row))
    for pair, unit in units.items():
        if pair not in seen_pairs and (pair[0] in codes or (unit['name'] and literal_label(subject, unit['name']))):
            raise Unavailable('unsupported_inquiry')
    require(not codes or bool(categories), 'clarification_required')
    candidates.sort(key=lambda entry: (entry[0]['category'] not in categories, entry[0]['category'] or '', entry[0]['sku'], entry[0]['grade']))
    category_slots = {}
    ranked = []
    for item, row in candidates:
        category = item['category']
        slot = category_slots.get(category, 0)
        category_slots[category] = slot + 1
        ranked.append((slot, item, row))
    ranked.sort(key=lambda entry: (entry[0], entry[1]['category'] not in categories, entry[1]['category'] or '', entry[1]['sku'], entry[1]['grade']))
    result = {'status': 'options', 'snapshot': snapshot, 'observed_at': document['observed_at'], 'valid_until': document['valid_until'], 'items': []}
    offered = {}
    for _, item, row in ranked:
        if len(offered) == 12:
            break
        result['items'].append(item)
        if json_size(result) > 5500:
            result['items'].pop()
            continue
        offered[(item['sku'], item['grade'])] = (item, row)
    require(bool(offered), 'no_verified_options')
    return result, offered


def selected_pairs(args):
    items = args['items']
    require(type(items) is list and 1 <= len(items) <= 3, 'invalid_selection')
    selected = []
    for item in items:
        require(exact_keys(item, {'sku', 'grade'}), 'invalid_selection')
        sku, grade = item['sku'], item['grade']
        require(type(sku) is str and SKU.fullmatch(sku) is not None and sku == sku.upper() and type(grade) is str and GRADE.fullmatch(grade) is not None, 'invalid_selection')
        pair = (sku, grade)
        require(pair not in selected, 'invalid_selection')
        selected.append(pair)
    return selected


def render_options(native, document, checked, selections, raw_refs):
    rendered = native['render']([row for _, row in selections], document, checked)
    require(type(rendered) is dict and rendered.get('status') not in (None, 'unavailable', 'rejected', 'error'))
    require(rendered.get('observed_at') == document['observed_at'] and rendered.get('valid_until') == document['valid_until'])
    body = rendered.get('reply')
    require(type(body) is str and bool(body.strip()) and not exposes_reference(body, raw_refs))
    heading = '현재 자료에서 확인한 대안입니다. 원래 요청 조건은 확인되지 않았습니다.'
    notice = '결제 문서(체크아웃 문서)는 발급하지 않았습니다.'
    reply = '\n'.join((heading, body.strip(), notice))
    if len(reply) > 450 or not all(item['sku'] in body and item['name'] in body for item, _ in selections):
        lines = []
        for item, _ in selections:
            line = '{} {} {}등급 {} 크레딧'.format(item['sku'], item['name'], item['grade'], item['preferred_price'])
            if item['category']:
                line += ' / ' + item['category']
            if item['expires_at'] is not None:
                expiry = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(item['expires_at']))
                line += ' / 만료 ' + expiry
            lines.append(line)
        reply = '\n'.join([heading, *lines, notice])
    require(len(reply) <= 450 and not exposes_reference(reply, raw_refs), 'reply_limit')
    return {'status': 'rendered', 'reply': reply, 'observed_at': document['observed_at'], 'valid_until': document['valid_until'], 'public_facts': [{key: item[key] for key in ('sku', 'grade', 'preferred_price')} for item, _ in selections]}


def run(args, kit):
    try:
        require(type(args) is dict, 'invalid_request')
        op = args.get('op')
        require(op in ('context', 'render'), 'invalid_request')
        keys = {'op', 'text'} if op == 'context' else {'op', 'text', 'snapshot', 'items'}
        require(exact_keys(args, keys) and type(args['text']) is str and 1 <= len(args['text']) <= 1500, 'invalid_request')
        pairs = selected_pairs(args) if op == 'render' else []
        base = agent_directory()
        native = load_native(base)
        source_reader = native['read_snapshot']
        raw = source_reader()
        require(isinstance(raw, (bytes, bytearray)))
        raw = bytes(raw)
        snapshot = hashlib.sha256(raw).hexdigest()
        if op == 'render':
            require(type(args['snapshot']) is str and args['snapshot'] == snapshot, 'snapshot_changed')
        document = load_json(raw, native)
        checked = int(time.time())
        units, raw_refs = catalogue_units(document, native, checked)
        stock_bytes = read_stock(base)
        stock = stock_rows(stock_bytes, native, document, snapshot)
        _raw_pairs, rows, _excluded, refs, _spellings = native['index_units'](document['units'])
        if isinstance(rows, dict):
            rows = rows.values()
        subject, target, codes = inquiry(args['text'], native, refs, raw_refs)
        native['read_snapshot'] = lambda: raw
        native_prepare(native, args['text'], kit)
        checked = int(time.time())
        require(valid_window(document, checked))
        options, offered = menu_for(document, snapshot, units, rows, stock, native, checked, subject, target, codes, refs, raw_refs)
        selected = []
        if op == 'render':
            require(all(pair in offered for pair in pairs), 'invalid_selection')
            selected = [offered[pair] for pair in pairs]
            response = render_options(native, document, checked, selected, raw_refs)
        else:
            response = options
        require(source_reader() == raw and read_stock(base) == stock_bytes, 'snapshot_changed')
        finished = int(time.time())
        require(valid_window(document, finished))
        rows_to_check = selected if op == 'render' else offered.values()
        require(all(eligible(row, units[row[0]], stock, native, finished) for _, row in rows_to_check), 'snapshot_changed')
        return response
    except Unavailable as blocked:
        return {'status': 'unavailable', 'reason': blocked.args[0]}
    except Exception:
        return {'status': 'unavailable', 'reason': 'source_unavailable'}
