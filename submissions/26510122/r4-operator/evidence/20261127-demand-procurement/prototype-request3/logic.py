import hashlib
import json
import math
import re
import sqlite3
import time
import unicodedata
from pathlib import Path

CATALOG = Path('host_inputs/stock-public-catalog.json')
DATABASE = Path('state/r4-demand/requests.sqlite3')
MAX_BYTES = 2 * 1024 * 1024
MAX_ITEMS = 10000
EVENT_NAMESPACE = b'r4:stock-request:event:v2' + bytes([0])
REQUIRED = {'op', 'text', 'event_ref', 'observed_at', 'source'}
OPTIONAL = {'product_phrase', 'queries', 'explicit_sku'}
SKU = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', re.ASCII)
SKU_CLAIM = re.compile(r'(?<![A-Za-z0-9_-])G[0-9a-f]{8}(?![A-Za-z0-9_-])|\bsku\b', re.I)
DEFER = re.compile(r'(?<=[.?!]) +(?P<clause>결제는 나중에 할게요)\.?\Z')
SENSITIVE = re.compile(
    r'환불|반품|취소|영수증|증빙|구매\s*증명|거래\s*(?:내역|증명|해시|번호)|증명|입금|송금|이체|지불|'
    r'구매|주문|예약|발급|정산|청구|인출|출금|충전|계좌|지갑|잔액|카드\s*번호|'
    r'권한|권리|토큰|서명|개인\s*정보|비밀|비공개|비밀번호|인증|내부|관리자|운영자|'
    r'숨겨|우회|무시|프롬프트|시스템\s*지시|도구\s*호출|실행|탐색|열거|테스트|'
    r'제외|빼고|말고|아닌|아니면|아니에요|않[은는아]|없[는나요을]|불가|싫[어요은]|금지|'
    r'알레르기|알러지|질환|복용|부작용|건강|임산부|의약|호환|연동|적합|지원\s*여부|'
    r'\b(?:refund|proof|receipt|private|payment|pay|purchase|checkout|invoice|token|'
    r'wallet|password|secret|signature|admin|system|prompt|ignore|probe|execute|rights|'
    r'allergy|compatible|compatibility|without|except)\b', re.I
)
FINANCIAL = re.compile(r'결\s*제|(?:0x)?[0-9a-f]{40,}|\b(?:tokrw|maroo|krw|wei|won)\b', re.I)
NOUN = re.compile(r'[가-힣A-Za-z]+(?: [가-힣A-Za-z]+){0,3}\Z')
NOUN_STOP = re.compile(
    r'(?:^| )(?:저|나|내|제|우리|너|당신|본인|고객|사용자|누구|내것|아무거나|모든|전체|'
    r'만|이하|이상|미만|초과|이내|부터|까지|가능|불가능|현재|지금|오늘|내일|무료|'
    r'가장|최저|최고|저렴한|싼|비싼|특정|같은|있는|없는|포함|미포함|무첨가|'
    r'한|두|세|네|다섯|여섯|일곱|여덟|아홉|열|한개|두개|세개|하나|둘|셋|넷|'
    r'재고|가격|이름|등급|유통기한|결제|for|with|only|under|over|free|my|your|'
    r'get|show|tell|list|return|send|one|two|three|four|five|six|seven|eight|nine|ten)(?: |\Z)|'
    r'(?:님|씨|해주세요|하세요|해요|해줘|주세요|드려요|알려|보여|됩니다|되나요|인가요|'
    r'있나요|없나요|합니다|할게요|하고|하며|하고싶은|원하는)(?: |\Z)', re.I
)
FIELD = r'(?:재고(?:\s*(?:여부|상태))?|가격|판매가|상품명|이름|등급|유통기한|소비기한|만료일)'
FIELDS = FIELD + r'(?:\s*(?:와|과|및|랑|하고|,)\s*' + FIELD + r'){0,3}'
READ = (r'(?:알려\s*주(?:세요|실까요|실래요|시겠어요)|보여\s*주(?:세요|실까요|실래요|시겠어요)|'
        r'확인해\s*주(?:세요|실까요|시겠어요)|알려줘(?:요)?|보여줘(?:요)?|'
        r'궁금(?:해요|합니다)|알\s*수\s*있(?:나요|을까요|습니까))')
AVAILABLE = r'(?:있나요|있어요|있습니까|있을까요|남아\s*있나요|남았나요|남아\s*있을까요)'
PRICE = r'(?:얼마(?:예요|에요|인가요|입니까|일까요|죠)?)'
ENDING = (r'(?:' + FIELDS + r'(?:을|를|이|가|은|는)?\s+' + READ +
          r'|재고(?:가|는|도)?\s*' + AVAILABLE +
          r'|(?:(?:가격|판매가)(?:이|가|은|는)?\s*)?' + PRICE +
          r'|' + AVAILABLE + r')')
INQUIRY = re.compile(r'(?:혹시 +)?(?P<target>.{1,120}?) +' + ENDING + r'[?.!]?\Z')
SHORT_INQUIRY = re.compile(r'(?:혹시 +)?(?P<target>.{1,120}?) +' + FIELDS + r'\?\Z')
PARTICLES = ('의', '은', '는', '이', '가')


def result(status, count=0):
    return {'status': status, 'count': count}


def timestamp(value):
    return type(value) in (int, float) and 0 < value <= 253402300799 and math.isfinite(value)


def normalize(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError('duplicate key')
        obj[key] = value
    return obj


def read_catalog(raw, now):
    if raw is None:
        with CATALOG.open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
    if type(raw) is not bytes or len(raw) > MAX_BYTES:
        raise ValueError('invalid catalog size')
    doc = json.loads(raw.decode('utf-8'), object_pairs_hook=unique_object)
    if (type(doc) is not dict or doc.keys() != {'observed_at', 'valid_until', 'round', 'items'}
            or type(doc['round']) is not int or doc['round'] != 4):
        raise ValueError('invalid catalog envelope')
    start, end = doc['observed_at'], doc['valid_until']
    if not timestamp(start) or not timestamp(end) or not (start <= now < end and 0 < end - start <= 150):
        raise ValueError('invalid catalog validity')
    if type(doc['items']) is not list or len(doc['items']) > MAX_ITEMS:
        raise ValueError('invalid item count')
    skus = {}
    names = {}
    public_fields = set()
    for item in doc['items']:
        if type(item) is not dict or item.keys() != {'sku', 'name', 'category'}:
            raise ValueError('invalid item')
        sku, name, category = item['sku'], item['name'], item['category']
        if not all(type(value) is str for value in (sku, name, category)) or not SKU.fullmatch(sku):
            raise ValueError('invalid item fields')
        name_key = normalize(name)
        if not name_key or sku.upper() in skus or any(0xD800 <= ord(ch) <= 0xDFFF for ch in name + category):
            raise ValueError('invalid or duplicate item')
        skus[sku.upper()] = sku
        names[name_key] = None if name_key in names else sku
        public_fields.update((name_key, normalize(category)))
    return skus, names, public_fields


def extract_target(original):
    if (type(original) is not str or not 1 <= len(original) <= 512
            or any(unicodedata.category(ch).startswith('C') for ch in original)):
        return None
    if SENSITIVE.search(normalize(original)):
        return None
    body = original.strip()
    deferred = DEFER.search(body)
    financial = list(FINANCIAL.finditer(body))
    if financial and (deferred is None or len(financial) != 1
                      or financial[0].start() != deferred.start('clause')):
        return None
    if deferred is not None:
        body = body[:deferred.start()]
    if FINANCIAL.search(normalize(body)):
        return None
    match = INQUIRY.fullmatch(body) or SHORT_INQUIRY.fullmatch(body)
    return match['target'] if match else None


def safe_noun(value, limit):
    return (type(value) is str and 1 <= len(value) <= limit and NOUN.fullmatch(value)
            and not NOUN_STOP.search(value) and not SENSITIVE.search(value)
            and not FINANCIAL.search(value))


def target_forms(target):
    if len(target) > 1 and target.endswith(PARTICLES):
        return (target, target[:-1])
    return (target,)


def classify(args, original, target, catalog):
    skus, names, public_fields = catalog
    forms = target_forms(target)
    hint = args.get('explicit_sku')
    if 'explicit_sku' in args and (type(hint) is not str or not SKU.fullmatch(hint)):
        return None
    sku_matches = {skus[form.upper()] for form in forms if SKU.fullmatch(form) and form.upper() in skus}
    if len(sku_matches) == 1:
        sku = next(iter(sku_matches))
        if hint is not None and hint.upper() != sku.upper():
            return None
        return (sku, None, 'exact_sku')
    if sku_matches or hint is not None or SKU_CLAIM.search(normalize(target)):
        return None
    if any(word.upper() in skus for word in re.findall(r'[A-Za-z0-9_-]+', normalize(target))):
        return None
    known_names = {normalize(form) for form in forms if normalize(form) in names}
    if len(known_names) == 1:
        exact_name = names[next(iter(known_names))]
        if exact_name is not None:
            return (exact_name, None, 'exact_name')
    phrase = args.get('product_phrase')
    queries = args.get('queries')
    if not safe_noun(phrase, 40) or phrase not in forms or original.count(phrase) != 1:
        return None
    bounded = r'(?<!\w)' + re.escape(phrase) + r'(?:의|은|는|이|가)?(?!\w)'
    if not re.search(bounded, original) or type(queries) is not list or not 1 <= len(queries) <= 2:
        return None
    if not all(safe_noun(query, 24) for query in queries):
        return None
    verified = set()
    for term in {normalize(query) for query in queries}:
        public_word = re.compile(r'(?<!\w)' + re.escape(term) + r'(?!\w)')
        if any(public_word.search(field) for field in public_fields):
            verified.add(term)
    if len(verified) == 1:
        return (None, next(iter(verified)), 'public_term')
    return None


def persist(db_path, event_hash, observed_at, evidence):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=5, isolation_level=None)
    try:
        connection.execute('BEGIN IMMEDIATE')
        connection.execute('CREATE TABLE IF NOT EXISTS request ('
                           'event_hash TEXT PRIMARY KEY, sku TEXT, term TEXT, '
                           'observed_at REAL NOT NULL, confidence TEXT NOT NULL)')
        if connection.execute('SELECT 1 FROM request WHERE event_hash = ?', (event_hash,)).fetchone():
            connection.commit()
            return result('duplicate')
        sku, term, confidence = evidence
        connection.execute('INSERT INTO request (event_hash, sku, term, observed_at, confidence) '
                           'VALUES (?, ?, ?, ?, ?)', (event_hash, sku, term, observed_at, confidence))
        connection.commit()
        return result('recorded', 1)
    finally:
        connection.close()


def run(args, kit):
    if type(args) is not dict or not REQUIRED <= args.keys():
        return result('rejected')
    allowed = REQUIRED | OPTIONAL
    if kit.testing:
        allowed = allowed | {'stock_request_fixture'}
    if args.keys() - allowed or args['op'] != 'record' or args['source'] != 'external_completed':
        return result('rejected')
    event_ref, observed_at = args['event_ref'], args['observed_at']
    if (type(event_ref) is not str or not 1 <= len(event_ref) <= 1024
            or not event_ref.isascii() or not event_ref.isprintable() or not event_ref.strip()
            or not timestamp(observed_at)):
        return result('rejected')
    original = args['text']
    target = extract_target(original)
    if target is None:
        return result('rejected')
    raw, db_path = None, DATABASE
    if kit.testing:
        fixture = args.get('stock_request_fixture', getattr(kit, 'stock_request_fixture', None))
        if (type(fixture) not in (tuple, list) or len(fixture) != 2 or type(fixture[0]) is not bytes
                or not isinstance(fixture[1], (str, Path))):
            return result('rejected')
        raw, db_path = fixture[0], Path(fixture[1])
    try:
        catalog = read_catalog(raw, time.time())
    except (OSError, ValueError, RecursionError):
        return result('catalog_unavailable')
    evidence = classify(args, original, target, catalog)
    if evidence is None:
        return result('insufficient')
    event_hash = hashlib.sha256(EVENT_NAMESPACE + event_ref.encode('ascii')).hexdigest()
    try:
        return persist(db_path, event_hash, observed_at, evidence)
    except (OSError, sqlite3.Error):
        return result('storage_error')
