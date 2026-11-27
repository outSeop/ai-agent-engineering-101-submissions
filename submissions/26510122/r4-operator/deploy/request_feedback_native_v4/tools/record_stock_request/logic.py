import hashlib
import json
import math
import re
import sqlite3
import time
import unicodedata

CATALOG = 'host_inputs/stock-public-catalog.json'
DATABASE = 'state/r4-demand/requests.sqlite3'
MAX_BYTES = 2 * 1024 * 1024
NEUTRAL = '결제는 나중에 할게요.'
SKU = re.compile(r'[a-z0-9][a-z0-9._:-]{0,127}', re.ASCII)
TOKEN = re.compile(r'[^\W\d_]+|\d+')
TERM = re.compile(r'[^\W\d_]+(?: [^\W\d_]+){0,3}')
DENIED = re.compile(
    r'결제|지불|입금|송금|이체|청구|발급|환불|취소|권리|권한|증빙|영수증|증명|계좌|지갑|카드\s*번호|개인정보|'
    r'주민|전화|연락처|이메일|주소|비밀번호|인증|서명|토큰|코인|암호화폐|예약|주문|구매|사고\s*싶|사\s*주세요|살\s*수|'
    r'배송|처방|복용|임신|알레르기|건강|효능|부작용|치료|호환|사용법|방법|지시|\b(?:do\s+not|don[’\']t)\b|'
    r'말고|빼고|필요\s*없|관심\s*없|있지\s*않|없나요|없습니까|아닌|안\s+(?:살|사|궁금)|'
    r'\b(?:pay(?:ment|able|ing)?|paid|refund\w*|receipts?|proof|invoice\w*|issue|rights?|'
    r'permission\w*|private|personal|password|secret|signature|wallets?|bank|accounts?|tokens?|'
    r'crypto\w*|credits?|tokrw|maroo|krw|usd|eur|btc|eth|address|e-?mail|phone|allerg\w*|'
    r'health|medical|pregnan\w*|dosage|cure|compatib\w*|instructions?|buy|purchase|order|'
    r'reserve|checkout|negative|never|not|unavailable|instead|except|avoid|without|or)\b|'
    r'[$€₩£¥@]|\d\s*(?:원|달러|유로|크레딧|퍼센트|%)|'
    r'\b\d{1,4}\s*[-/.]\s*\d{1,2}\s*[-/.]\s*\d{1,4}\b|'
    r'\b\d{4}\s*년|\b\d{1,2}\s*월\s*\d{1,2}\s*일|'
    r'\b\d{1,2}:\d{2}\b|오늘|내일|어제|\b(?:today|tomorrow|yesterday)\b|'
    r'\b0x[0-9a-f]{40,}\b|(?<!\d)\d{3}[- ]\d{3,4}[- ]\d{4}(?!\d)'
)
AMBIGUOUS = re.compile(r'[,;!?+&]|\s+(?:및|또는|혹은|그리고|아니면)\s+|(?:와|과|랑|하고)\s+|\b(?:and|versus|vs\.?)\b')
KO_SHOW = r'(?:보여\s*주(?:세요|실\s*수\s*있나요)|알려\s*주(?:세요|실\s*수\s*있나요)|확인해\s*주(?:세요|실\s*수\s*있나요))'
KO_SUBJECT = r'(?:재고(?:\s*(?:와|랑|및|하고)\s*가격)?|가격(?:\s*(?:과|이랑|및|하고)\s*재고)?|판매\s*가격)'
FRAMES = tuple(re.compile(pattern) for pattern in (
    r'(?P<noun>.+?)(?:\s+|의\s*)' + KO_SUBJECT + r'(?:을|를|이|가|은|는)?(?:\s*(?:' + KO_SHOW + r'|궁금해요|궁금합니다|문의(?:해요|합니다)?|있나요|있어요|있습니까|얼마(?:예요|에요|인가요|입니까)))?',
    r'(?P<noun>.+?)(?:\s*(?:이|가|은|는|도)|\s+)\s*(?:재고가\s*)?(?:있나요|있어요|있습니까|있을까요)',
    r'(?P<noun>.+?)(?:\s*(?:이|가|은|는)|\s+)\s*얼마(?:예요|에요|인가요|입니까)',
    r'(?P<noun>.+?)(?:\s*(?:에|이|가|은|는)|\s+)\s*(?:관심(?:이)?\s*(?:있어요|있습니다|있어|있는데요)|궁금(?:해요|합니다))',
    r'(?:do you (?:have|stock)|is there stock of) (?P<noun>.+?)(?: in stock| available)?',
    r'is (?P<noun>.+?) (?:in stock|available)',
    r'(?:how much is|what is the price of|what[’\']s the price of) (?P<noun>.+)',
    r'(?:please )?(?:show me|tell me|check|can you (?:show me|tell me|check)) (?:the )?(?:price and (?:stock|availability)|(?:stock|availability) and price|price|stock|availability) (?:of|for) (?P<noun>.+)',
    r'(?:price and (?:stock|availability)|(?:stock|availability) and price|price|stock|availability) (?:of|for) (?P<noun>.+)',
    r'(?P<noun>.+?) (?:price(?: and (?:stock|availability))?|stock(?: and price)?|availability(?: and price)?)',
    r'(?:i am|i[’\']m) interested in (?P<noun>.+)',
))


def canonical(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())


def finite_number(value):
    return type(value) is int or (type(value) is float and math.isfinite(value))


def public_label(value):
    return (isinstance(value, str) and bool(value.strip())
            and all(not unicodedata.category(char).startswith('C') for char in value))


def unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON field')
        result[key] = value
    return result


def load_catalog(raw, now):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
        raise ValueError('catalog size')
    catalog = json.loads(raw.decode('utf-8'), object_pairs_hook=unique_fields)
    if not isinstance(catalog, dict) or set(catalog) != {'observed_at', 'valid_until', 'round', 'items'}:
        raise ValueError('catalog shape')
    start, expiry = catalog['observed_at'], catalog['valid_until']
    if (type(catalog['round']) is not int or catalog['round'] != 4
            or not finite_number(start) or not finite_number(expiry)
            or not now - 150 <= start <= now < expiry <= start + 150):
        raise ValueError('catalog time')
    if not isinstance(catalog['items'], list) or len(catalog['items']) > 10000:
        raise ValueError('catalog items')
    skus, names, labels = {}, {}, set()
    for item in catalog['items']:
        if not isinstance(item, dict) or set(item) != {'sku', 'name', 'category'}:
            raise ValueError('catalog item shape')
        if not all(public_label(item[field]) for field in ('sku', 'name', 'category')):
            raise ValueError('catalog item text')
        sku, name, category = (canonical(item[field]) for field in ('sku', 'name', 'category'))
        if not SKU.fullmatch(sku) or sku in skus:
            raise ValueError('invalid or duplicate catalog SKU')
        skus[sku] = item['sku']
        names.setdefault(name, []).append(item['sku'])
        labels.update((name, category))
    return skus, names, labels


def original_nouns(text):
    if not isinstance(text, str) or not 1 <= len(text) <= 500:
        return None, ()
    if any(unicodedata.category(char).startswith('C') for char in text):
        return None, ()
    text = text.strip()
    if text.endswith(' ' + NEUTRAL):
        text = text[:-len(NEUTRAL)].rstrip()
    text = canonical(text)
    if DENIED.search(text):
        return None, ()
    body = text[:-1].rstrip() if text.endswith(('?', '.')) else text
    nouns = tuple(dict.fromkeys(match['noun'].strip() for frame in FRAMES
                                if (match := frame.fullmatch(body))))
    return body, tuple(noun for noun in nouns if noun and not AMBIGUOUS.search(noun))


def public_term(term, labels):
    if not 2 <= len(term) <= 60 or not TERM.fullmatch(term) or DENIED.search(term) or AMBIGUOUS.search(term):
        return False
    # Letters and digits are separate tokens, including in a Korean name ending in a package size.
    parts = term.split(' ')
    width = len(parts)
    for label in labels:
        tokens = list(TOKEN.finditer(label))
        for index in range(len(tokens) - width + 1):
            first, last = tokens[index], tokens[index + width - 1]
            if label[first.start():last.end()] == term:
                return True
    return False


def classify(args, skus, names, labels):
    body, nouns = original_nouns(args.get('text'))
    if not nouns:
        return None
    matches = {skus[noun] for noun in nouns if noun in skus}
    titles = {sku for noun in nouns for sku in names.get(noun, ())}
    if len(matches | titles) > 1:
        return None
    if matches:
        return next(iter(matches)), None, 'exact_sku'
    if titles:
        return next(iter(titles)), None, 'exact_name'
    if len(nouns) != 1:
        return None
    noun = nouns[0]
    if public_term(noun, labels):
        return None, noun, 'public_term'
    phrase, queries = args.get('product_phrase'), args.get('queries')
    if (not isinstance(phrase, str) or len(phrase) > 150 or canonical(phrase) != noun
            or body.count(noun) != 1 or not isinstance(queries, list) or not 1 <= len(queries) <= 2):
        return None
    if not all(isinstance(term, str) and len(term) <= 60 for term in queries):
        return None
    terms = tuple(canonical(term) for term in queries)
    if len(set(terms)) != len(terms) or not all(public_term(term, labels) for term in terms):
        return None
    return None, terms[0], 'public_term'


def result(status, count=0):
    return {'status': status, 'count': count}


def run(args, kit):
    now = time.time()
    if not isinstance(args, dict) or args.get('op') != 'record' or args.get('source') != 'external_completed':
        return result('ignored')
    observed_at, event_ref = args.get('observed_at'), args.get('event_ref')
    if (not finite_number(observed_at) or not now - 86400 <= observed_at <= now
            or not isinstance(event_ref, str) or not re.fullmatch(r'[!-~]{1,512}', event_ref)):
        return result('ignored')
    try:
        fixture = getattr(kit, 'stock_request_fixture', None) if kit.testing else None
        if fixture is None:
            database = DATABASE
            with open(CATALOG, 'rb') as file:
                raw = file.read(MAX_BYTES + 1)
        else:
            raw, database = fixture
        skus, names, labels = load_catalog(raw, now)
    except (OSError, ValueError, TypeError, RecursionError):
        return result('ignored')
    demand = classify(args, skus, names, labels)
    if demand is None:
        return result('ignored')
    event_hash = hashlib.sha256(b'r4:stock-request:event:v2' + bytes([0]) + event_ref.encode('ascii')).hexdigest()
    sku, term, confidence = demand
    connection = None
    try:
        connection = sqlite3.connect(database, timeout=5)
        with connection:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('CREATE TABLE IF NOT EXISTS request (event_hash TEXT PRIMARY KEY, sku TEXT, term TEXT, observed_at REAL NOT NULL, confidence TEXT NOT NULL)')
            inserted = connection.execute('INSERT INTO request (event_hash, sku, term, observed_at, confidence) VALUES (?, ?, ?, ?, ?) ON CONFLICT(event_hash) DO NOTHING',
                                          (event_hash, sku, term, observed_at, confidence)).rowcount
        return result('recorded', 1) if inserted else result('duplicate')
    except (OSError, sqlite3.Error):
        return result('error')
    finally:
        if connection is not None:
            connection.close()
