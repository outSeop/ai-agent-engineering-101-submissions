import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import time
import unicodedata


CATALOG = Path('host_inputs/stock-public-catalog.json')
DATABASE = Path('state/r4-demand/requests.sqlite3')
MAX_CATALOG_BYTES = 2 * 1024 * 1024
CATALOG_WINDOW = 150
REQUEST_WINDOW = 86400
REQUIRED = {'op', 'text', 'event_ref', 'observed_at', 'source'}
OPTIONAL = {'product_phrase', 'queries', 'explicit_sku'}
EVENT_REF = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,191}', re.ASCII)
SKU = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/+-]{0,127}', re.ASCII)
NOUN = re.compile(r'[^\W\d_]+', re.UNICODE)
GENERIC = frozenset('a an the some any please buy purchase order stock available availability product products item items goods pack box set fresh organic premium small large and or reserve edition 재고 상품 제품 물건 구매 구입 주문 판매 신선 프리미엄 세트 박스 종류'.split())
BLOCK = re.compile(
    r'\b(?:refund\w*|return\w*|chargeback\w*|cancel\w*|reimburse\w*|'
    r'transaction\w*|receipt\w*|payment\w*|paid|pay|invoice\w*|wallet\w*|transfer\w*|'
    r'tracking|proof\w*|signature\w*|password\w*|private|secret\w*|credential\w*|'
    r'(?:street|shipping|home|email) address|identity|e-?mail|phone|passport|'
    r'medical|medicin\w*|health\w*|diagnos\w*|allerg\w*|dosage\w*|pregnan\w*|'
    r'no|not|never|without|except|avoid\w*|rather|instead|or|nor|either|'
    r'don[’\']?t|doesn[’\']?t|isn[’\']?t|aren[’\']?t|can[’\']?t|won[’\']?t|cannot|'
    r'maybe|possibly|hypothetic\w*|test\w*|probe\w*|spoof\w*|pretend\w*|simulat\w*|'
    r'synthetic|ignore|instruction\w*|prompt\w*|event_ref|external_completed|explicit_sku)\b|'
    r'환불|반품|취소|거래|결제|입금|송금|이체|영수증|증빙|주문\s*(?:번호|내역|조회|상태)|'
    r'배송\s*(?:조회|주소|내역|상태)|계좌|지갑|비밀번호|개인\s*정보|주민\s*번호|전화\s*번호|연락처|'
    r'건강|의료|진단|질병|치료|복용|약품|약물|알레르기|임신|'
    r'(?<![가-힣])안\s+(?:사|살|구매|구입|주문|필요|할|해)|아니|싫|못\s*(?:사|살|구매|구입)|'
    r'없|말고|제외|대신|또는|혹은|거나|테스트|프로브|시뮬레이션|가상|예시|프롬프트|지시문|무시하',
    re.IGNORECASE)
SENSITIVE = re.compile(r'@|https?://|www\.|0x[0-9a-f]{12,}|\b\d{3}[- .]\d{3,4}[- .]\d{4}\b|\b\d{6}[- ]\d{7}\b', re.IGNORECASE)
GREETING = re.compile(r'^(?:(?:hi|hello|hey|안녕하세요|안녕)[,.! ]+)?(?:(?:please|혹시)[, ]+)?', re.IGNORECASE)
ENGLISH = tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
    r'(?:i (?:want|would like) to|i[’\']d like to|(?:can|could|may) i) (?:buy|purchase|order) (?P<target>.+)',
    r'(?:do you (?:have|stock|sell|carry)|have you got|(?:can|could) you sell me) (?P<target>.+)',
    r'(?:is|are) (?P<target>.+?) (?:available(?: for (?:sale|purchase))?|in stock)',
    r'(?P<target>.+?) (?:available|in stock)',
))
KOREAN = re.compile(
    r'(?:저는\s+)?(?P<target>.+?)\s+(?:'
    r'재고(?:가|는)?\s*(?:있나요|있을까요|있습니까|있어요)|'
    r'(?:구매|구입|주문|판매)(?:를|가|는)?\s*(?:가능한가요|가능할까요|가능합니까|가능해요|가능하나요|'
    r'가능할지\s*궁금합니다|하고\s*싶어요|하고\s*싶습니다|하려고\s*합니다|할\s*수\s*있나요|할\s*수\s*있을까요)|'
    r'살\s*수\s*있(?:나요|을까요|습니까)|사고\s*싶(?:어요|습니다)|'
    r'판매(?:하나요|하시나요|합니까)|있(?:나요|을까요|습니까|어요)|파(?:나요|시나요))')
ARTICLE = re.compile(r'^(?:the|a|an|some|any) ', re.IGNORECASE)
PARTICLE = re.compile(r'(?<=[가-힣A-Za-z0-9])(?:으로|을|를|은|는|이|가|도|만)$')


def result(status, count=0):
    return {'status': status, 'count': count}


def finite_number(value):
    return type(value) in (int, float) and -1e12 < value < 1e12 and math.isfinite(value)


def clean_string(value, max_chars):
    return (type(value) is str and 0 < len(value) <= max_chars and value == value.strip()
            and all(not unicodedata.category(char).startswith('C')
                    and (not char.isspace() or char == ' ') for char in value))


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError('duplicate JSON key')
        obj[key] = value
    return obj


def load_catalog(raw, now):
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_CATALOG_BYTES:
        raise ValueError('catalog size')
    catalog = json.loads(raw.decode('utf-8'), object_pairs_hook=unique_object)
    if type(catalog) is not dict or set(catalog) != {'observed_at', 'valid_until', 'round', 'items'}:
        raise ValueError('catalog fields')
    start, end = catalog['observed_at'], catalog['valid_until']
    if not (finite_number(start) and finite_number(end) and start <= now < end
            and 0 < end - start <= CATALOG_WINDOW):
        raise ValueError('catalog window')
    if type(catalog['round']) is not int or catalog['round'] != 4:
        raise ValueError('catalog round')
    items = catalog['items']
    if type(items) is not list or len(items) > 10000:
        raise ValueError('catalog items')
    skus = set()
    for item in items:
        if type(item) is not dict or set(item) != {'sku', 'name', 'category'}:
            raise ValueError('item fields')
        sku, name, category = item['sku'], item['name'], item['category']
        if not (type(sku) is str and SKU.fullmatch(sku)
                and clean_string(name, 512) and clean_string(category, 512)):
            raise ValueError('item values')
        key = sku.casefold()
        if key in skus:
            raise ValueError('duplicate canonical SKU')
        skus.add(key)
    return items


def valid_args(args, now):
    if type(args) is not dict or not REQUIRED <= args.keys() <= REQUIRED | OPTIONAL:
        return False
    if args['op'] != 'record' or args['source'] != 'external_completed':
        return False
    ref, observed = args['event_ref'], args['observed_at']
    if type(ref) is not str or not EVENT_REF.fullmatch(ref):
        return False
    if not finite_number(observed) or not now - REQUEST_WINDOW <= observed <= now:
        return False
    if not clean_string(args['text'], 500):
        return False
    for field, limit in (('product_phrase', 200), ('explicit_sku', 128)):
        if field in args and not clean_string(args[field], limit):
            return False
    if 'queries' in args:
        queries = args['queries']
        if type(queries) is not list or len(queries) > 16:
            return False
        if any(not clean_string(query, 200) for query in queries):
            return False
    return True


def extract_targets(text):
    body = GREETING.sub('', text).strip()
    if BLOCK.search(body) or SENSITIVE.search(body):
        return set()
    core = body.rstrip('?.!').rstrip()
    if (not core or any(mark in core for mark in ('?', '!', ';', '"', '“', '”', '`', '[', ']', '{', '}'))
            or re.search(r'[.]\s', core)):
        return set()
    targets = set()
    for pattern in ENGLISH:
        match = pattern.fullmatch(core)
        if match:
            target = match['target'].strip()
            targets.update((target.casefold(), ARTICLE.sub('', target).casefold()))
    match = KOREAN.fullmatch(core)
    if match:
        target = match['target'].strip()
        targets.update((target.casefold(), PARTICLE.sub('', target).casefold()))
    return targets - {''}


def find_evidence(targets, items):
    exact = {}
    for item in items:
        sku, name = item['sku'], item['name']
        if sku.casefold() in targets:
            exact[sku] = (sku, None, 'exact_sku')
        elif name.casefold() in targets:
            exact[sku] = (sku, None, 'exact_name')
    if exact:
        return next(iter(exact.values())) if len(exact) == 1 else None
    noun_targets = {target for target in targets
                    if len(target) >= 2 and target not in GENERIC and NOUN.fullmatch(target)}
    if not noun_targets:
        return None
    matches = {}
    for item in items:
        for word in NOUN.findall(item['name']):
            if word.casefold() in noun_targets:
                matches.setdefault((item['sku'], word.casefold()), word)
    if len(matches) != 1:
        return None
    (sku, _), term = next(iter(matches.items()))
    return sku, term, 'public_term'


def save(database, event_hash, evidence, observed, now):
    sku, term, confidence = evidence
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database, timeout=10, isolation_level=None)
    try:
        connection.execute('BEGIN IMMEDIATE')
        connection.execute('CREATE TABLE IF NOT EXISTS request ('
                           'event_hash TEXT PRIMARY KEY, sku TEXT, term TEXT, '
                           'observed_at REAL NOT NULL, confidence TEXT NOT NULL)')
        inserted = connection.execute(
            'INSERT INTO request (event_hash, sku, term, observed_at, confidence) '
            'VALUES (?, ?, ?, ?, ?) ON CONFLICT(event_hash) DO NOTHING',
            (event_hash, sku, term, observed, confidence)).rowcount == 1
        count = connection.execute(
            'SELECT COUNT(*) FROM request WHERE observed_at >= ? AND observed_at <= ?',
            (now - REQUEST_WINDOW, now)).fetchone()[0]
        connection.commit()
        return result('recorded' if inserted else 'duplicate', count)
    finally:
        connection.close()


def run(args, kit):
    now = time.time()
    if not valid_args(args, now):
        return result('invalid_request')
    targets = extract_targets(args['text'])
    if not targets:
        return result('insufficient_evidence')
    try:
        if kit.testing:
            raw, database_path = kit.stock_request_fixture
            database = Path(database_path)
        else:
            database = DATABASE
            with CATALOG.open('rb') as catalog_file:
                raw = catalog_file.read(MAX_CATALOG_BYTES + 1)
        items = load_catalog(raw, now)
    except (AttributeError, OSError, TypeError, ValueError, RecursionError):
        return result('catalog_unavailable')
    evidence = find_evidence(targets, items)
    if evidence is None:
        return result('insufficient_evidence')
    event_hash = hashlib.sha256(b'r4:stock-request:event:v2\x00' + args['event_ref'].encode('ascii')).hexdigest()
    try:
        return save(database, event_hash, evidence, args['observed_at'], now)
    except (OSError, sqlite3.Error):
        return result('storage_unavailable')
