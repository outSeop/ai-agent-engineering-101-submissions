import hashlib
import math
import re
import time
import unicodedata

DEPENDENCY = 'tools/public_catalogue/logic.py'
PIN = '01a4a0dc912e02679091a3f6c98df3f0450ca2581b920d1d650e2fa0fa2a4c89'
PREFIX = '유사어로 찾은 참고 후보입니다. 정확한 상품 일치와 요청 조건 전체의 충족 여부는 확인되지 않았습니다. 표시 가격은 공개 상품가입니다.'
ADVICE = '원하는 SKU로 구매 조건을 다시 문의해 주세요.'
SKU = re.compile(r'G[0-9a-f]{8}', re.I)
RESTRICTED = re.compile(
    r'결제|송금|입금|출금|환불|반품|정산|인출|지갑|계좌|거래|주문|구매|계약|권리|권한|견적|청구|서명|인증|잔액|할인|흥정|예약|본인|개인정보|이메일|연락처|전화번호|고객\s*(?:번호|정보)|내부|비공개|이벤트|로그|'
    r'\b(?:pay\w*|check\s*out|buy\w*|order\w*|purchas\w*|refund\w*|return\w*|transfer\w*|balance|rights?|entitlement\w*|quote\w*|sign\w*|contract\w*|event\w*|customer\s+id|internal)\b', re.I)
UNVERIFIED = re.compile(
    r'건강|안전|효능|효과|치료|예방|질환|당뇨|혈당|임산부|유아|복용|락토프리|무유당|유당|저지방|저당|저염|무독성|무항생제|무농약|유기농|무가당|무첨가|무설탕|무염|프리\b|제로\b|'
    r'호환|맞는|맞아|배송|택배|도착|오늘\s*받|내일\s*받|무료|공짜|보장|정품|품질|인증|필수|반드시|무조건|최저|최고|이내|'
    r'\b(?:health\w*|safe\w*|treat\w*|cure\w*|diabet\w*|lactose\w*|sugar[- ]free|gluten\w*|free|guarante\w*|certif\w*|compatib\w*|must|only|always|never|authentic|ingredient\w*|warranty)\b', re.I)
NEGATION = re.compile(r'제외|말고|대신|아니|않|없이|없는|없으면|없다면|불가|금지|하지\s*마|보여주지|필요\s*없|빼|싫|\b(?:no|not|without|except|exclude|instead|or)\b', re.I)
EXACT = re.compile(r'정확히|똑같|동일|같은\s*제품|바로\s*그|딱|오직|그\s*제품만|대체\s*불가|\b(?:exact\w*|identical|same\s+product)\b', re.I)
INTENT = re.compile(r'찾아|추천|재고|가격|상품명|제품명|유통\s*기한|소비\s*기한|있나요|있어요|있을까요|보여|알려|조회|문의|판매|\b(?:find|show|stock|price|available)\b', re.I)
TERM = re.compile(r'[^\W_]+(?:[ -][^\W_]+)*')
UNBOUND = {'최소', '최대', '이상', '이하', '초과', '미만', '이내', '짜리', '남은', '기한', '만', '상품만', '제품만', 'between', 'under', 'over', 'atleast', 'atmost'}
CONSTRAINTS = ('PRICE_REQUEST', 'TIME_REQUEST', 'GRADE_REQUEST', 'QUANTITY')
NEUTRAL_SENTENCE = re.compile(
    r'(?:^|(?<=[.!?])) *(?P<sentence>결제 절차도 알려 ?주세요\.|아직 결제하지 않을게요\.|지금 결제하지 않겠습니다\.)(?= |$)')
PROOF_OR_AUTHORITY = re.compile(
    r'영수증|증빙|증명서|승인|수취인|입출금|환급|계좌번호|보내\s*(?:줘|주|세요|라)|전송|체크\s*아웃|'
    r'\b(?:receipt\w*|proof|txid|tx\s*hash|send|account|wallet|checkout|authorization|payout)\b', re.I)
OTHER_HARD_ATTRIBUTE = re.compile(
    r'알레르|알러지|과민|교차\s*오염|성분|포함|함유|제조국|원산지|재질|규격|색상|당일|유통기한|소비기한|'
    r'비건|할랄|코셔|디카페인|무카페인|저칼로리|방수|내열|어린이용|전용|적합|가능한|조건|'
    r'\b(?:allerg\w*|intoleran\w*|cross[- ]contamin\w*|vegan|halal|kosher|decaf\w*|waterproof|organic)\b', re.I)
PRODUCT_MODIFIER = re.compile(
    r'등급|가격|금액|크레딧|원짜리|만원|포장|용량|묶음|세트|팩|수량|상품만|제품만|저렴|싼|비싼|신선|'
    r'빨간|파란|검정|흰색|초록|큰|작은|이상|이하|초과|미만|기한|'
    r'\b(?:grade|price|credits?|won|krw|pack|quantity|cheap\w*|fresh|red|blue|large|small)\b', re.I)
NON_NOUN_WORD = re.compile(
    r'^(?:그|이|저|해당|어떤|아무|다른|모든|각각|둘|둘다|상품|제품|물건|것|저것|이것|그것|'
    r'가능|불가능|(?:the|this|that|any|something|product|item))$|'
    r'(?:하다|한다|합니다|해요|했다|하세요|되다|됩니다|된다|됐|있다|있습니다|없다|없습니다|주세요|줘요|싶다|싶어요|하는|되는|있는|없는|만)$', re.I)
# These catalogue-independent nouns cover the existing semantic lookup examples.
PUBLIC_ALIASES = {'밀크', '컴퓨터체어', '컴퓨터 체어'}


def unavailable(reason):
    return {'status': 'unavailable', 'reason': reason}


def normalize(text):
    return unicodedata.normalize('NFKC', text)


def load_catalogue():
    try:
        with open(DEPENDENCY, 'rb') as source:
            raw = source.read(128 * 1024 + 1)
    except OSError:
        return None
    if len(raw) > 128 * 1024 or hashlib.sha256(raw).hexdigest() != PIN:
        return None
    namespace = {'__name__': '_pinned_public_catalogue'}
    exec(compile(raw, DEPENDENCY, 'exec', dont_inherit=True), namespace)
    return namespace


def mask(text, spans):
    result = list(text)
    for start, end in spans:
        result[start:end] = ' ' * (end - start)
    return ''.join(result)


def overlaps(left, right):
    return left[0] < right[1] and right[0] < left[1]


def constraint_signature(text, c):
    signature = []
    for key in CONSTRAINTS:
        for match in c[key].finditer(text):
            suffix = c['AFTER_SELECTOR'].match(text, match.end()) if key in ('QUANTITY', 'GRADE_REQUEST') else None
            end = suffix.end() if suffix else match.end()
            signature.append((key, (match.start(), end), text[match.start():end], match.groups()))
    return signature


def product_span(text, phrase, c):
    if (not 1 <= len(phrase) <= 48 or not TERM.fullmatch(phrase)
            or any(not (ch.isalpha() or ch in ' -') for ch in phrase)
            or any(pattern.search(phrase) for pattern in (
                SKU, RESTRICTED, UNVERIFIED, NEGATION, EXACT, INTENT, PROOF_OR_AUTHORITY,
                OTHER_HARD_ATTRIBUTE, PRODUCT_MODIFIER, c['UNKNOWN_FACT'], c['OTHER_REQUEST'],
                c['UNPARSED_EXCLUSION'], c['NO_ALTERNATIVE'], c['NON_TARGET'], c['PREP_FACT']))
            or any(word.casefold() in UNBOUND or word.casefold() in c['PREP_PLAIN'] or NON_NOUN_WORD.search(word)
                   for word in re.split(r'[ -]', phrase))):
        return None
    pattern = re.compile(r'(?<![\w-])(?P<noun>' + re.escape(phrase) + r')(?P<particle>은|는|이|가|을|를)?(?![\w-])', re.I)
    matches = list(pattern.finditer(text))
    if len(matches) != 1 or matches[0]['noun'] != phrase:
        return None
    return matches[0].span()


def public_noun(phrase, c, eligible, refs):
    target = phrase.casefold()
    if target in PUBLIC_ALIASES:
        return True
    for _, unit, name, _, _ in eligible:
        path = unit['category_path']
        labels = path if type(path) is list else [path]
        if any(c['safe_label'](label, 128, refs) and normalize(label).casefold() == target for label in labels):
            return True
        clean_name = normalize(name)
        if RESTRICTED.search(clean_name):
            continue
        if clean_name.casefold() == target:
            return True
        # A verified listing may append a pack size to the public noun.
        pack = c['QUANTITY'].search(clean_name)
        if pack and pack.end() == len(clean_name) and clean_name[:pack.start()].rstrip().casefold() == target:
            return True
    return False


def request_selector(text, subject, c, eligible):
    roots = []
    for root in {row[3] for row in eligible if row[3] is not None}:
        pattern = re.compile(r'(?<!\w)' + re.escape(normalize(root)) + r'(?=' + c['PARTICLE'] + r'(?!\w))')
        if pattern.search(text):
            roots.append((root, pattern))
    compounds = set()
    if any(alias in text for alias in c['NUT_SPELLINGS']):
        for row in eligible:
            compounds.update(c['nut_compounds'](normalize(row[2])))
    positive, negative = c['remove_exclusions'](text, roots, compounds)
    if (len(positive) != len(text) or positive[subject[0]:subject[1]] != text[subject[0]:subject[1]]
            or NEGATION.search(positive) or c['UNPARSED_EXCLUSION'].search(positive)
            or c['OTHER_REQUEST'].search(positive) or re.search(r'또는|혹은|그리고|\b(?:and|or)\b', positive, re.I)):
        return None
    raw_signature = constraint_signature(text, c)
    positive_signature = constraint_signature(positive, c)
    if any(overlaps(subject, span) for _, span, _, _ in raw_signature + positive_signature):
        return None
    remainder = mask(positive, [span for _, span, _, _ in positive_signature])
    if UNVERIFIED.search(remainder) or any(match[0].endswith('만') for match in c['PREP_FACT'].finditer(remainder)):
        return None
    facts = list(c['PREP_FACT'].finditer(remainder))
    if any(overlaps(subject, match.span()) for match in facts):
        return None
    remainder = mask(remainder, [subject, *(match.span() for match in facts)])
    if OTHER_HARD_ATTRIBUTE.search(remainder) or re.search(r'[^\w\s.,?!·]|\d|_', remainder):
        return None
    words = re.findall(r'[^\W\d_]+', remainder)
    if any(word.casefold() in UNBOUND or word.casefold() not in c['PREP_PLAIN'] for word in words):
        return None
    constrained = mask(text, [subject])
    after_positive, after_negative = c['remove_exclusions'](constrained, roots, compounds)
    if (not INTENT.search(after_positive) or after_negative != negative
            or after_positive != mask(positive, [subject])
            or constraint_signature(constrained, c) != raw_signature
            or constraint_signature(after_positive, c) != positive_signature):
        return None
    return constrained


def run(args, kit):
    if type(args) is not dict or set(args) != {'op', 'text', 'product_phrase', 'queries'} or args['op'] != 'semantic_candidates':
        return unavailable('invalid_args')
    text, phrase, queries = args['text'], args['product_phrase'], args['queries']
    if (type(text) is not str or not 1 <= len(text) <= 1500 or type(phrase) is not str or not 1 <= len(phrase) <= 48
            or type(queries) is not list or not 1 <= len(queries) <= 2
            or any(type(q) is not str or not 1 <= len(q) <= 48 for q in queries)):
        return unavailable('invalid_args')
    c = load_catalogue()
    if c is None:
        return unavailable('dependency_unavailable')
    if any(unicodedata.category(ch).startswith('C') or unicodedata.category(ch) in ('Zl', 'Zp') for ch in text + phrase):
        return unavailable('unsupported_request')
    text, phrase = normalize(text), normalize(phrase)
    pack_text = c['PACK_SLASH'].sub(lambda match: match[0].replace('/', ' '), text)
    if (not c['safe_label'](pack_text, 1500, (), query=True) or SKU.search(text) or EXACT.search(text)
            or PROOF_OR_AUTHORITY.search(text) or c['NO_ALTERNATIVE'].search(text) or c['UNKNOWN_FACT'].search(text)):
        return unavailable('unsupported_request')
    subject = product_span(text, phrase, c)
    if subject is None:
        return unavailable('unsupported_request')
    neutral = [match.span('sentence') for match in NEUTRAL_SENTENCE.finditer(text)]
    if any(overlaps(subject, span) for span in neutral):
        return unavailable('unsupported_request')
    lookup_text = mask(pack_text, neutral)
    if (RESTRICTED.search(lookup_text) or not INTENT.search(lookup_text)
            or constraint_signature(pack_text, c) != constraint_signature(lookup_text, c)):
        return unavailable('unsupported_request')
    terms = [normalize(q).casefold() for q in queries]
    if len(set(terms)) != len(terms):
        return unavailable('invalid_args')
    for original, term in zip(queries, terms):
        if (not TERM.fullmatch(term) or len(term) > 48 or not any(ch.isalpha() for ch in term)
                or not c['safe_label'](original, 48, (), query=True) or SKU.search(term)
                or any(pattern.search(term) for pattern in (RESTRICTED, UNVERIFIED, NEGATION, EXACT, c['UNKNOWN_FACT'], c['NON_TARGET']))
                or term in c['PREP_PLAIN'] or term in UNBOUND or c['FACT'].fullmatch(term)):
            return unavailable('unsafe_query')
    start = time.time()
    try:
        raw = c['read_snapshot']()
    except (OSError, AttributeError, NotImplementedError):
        return unavailable('source_unavailable')
    try:
        snapshot = c['json'].loads(raw.decode('utf-8'), object_pairs_hook=c['unique_object'],
                                   parse_constant=c['reject_number'], parse_float=c['reject_number'])
    except (ValueError, RecursionError):
        return unavailable('invalid_snapshot')
    if (type(snapshot) is not dict or set(snapshot) != c['CONTEXT_KEYS']
            or snapshot['schema'] != 'outseop-r4.customer-offers.v1' or snapshot['shop'] != 'outseop-r4'
            or not c['integer'](snapshot['observed_at']) or not c['integer'](snapshot['valid_until'])
            or type(snapshot['units']) is not list or len(snapshot['units']) > c['MAX_UNITS']):
        return unavailable('invalid_snapshot')
    observed, until = snapshot['observed_at'], snapshot['valid_until']
    checked = time.time()
    if not observed <= start <= checked < until <= observed + 150:
        return unavailable('stale_snapshot')
    _, rows, _, refs, spellings = c['index_units'](snapshot['units'])
    if not c['safe_label'](pack_text, 1500, refs, query=True) or not c['safe_label'](phrase, 48, refs, query=True):
        return unavailable('unsupported_request')
    if any(not c['safe_label'](term, 48, refs, query=True) for term in terms):
        return unavailable('unsafe_query')
    eligible = [row for row in rows if row[2] is not None and c['current'](row, checked)]
    if not public_noun(phrase, c, eligible, refs):
        return unavailable('unsupported_request')
    constrained = request_selector(lookup_text, subject, c, eligible)
    if constrained is None:
        return unavailable('unsupported_request')
    buckets = [[] for _ in terms]
    matched = set()
    for row in eligible:
        pair, unit, name, _, _ = row
        if RESTRICTED.search(normalize(name)):
            continue
        path = unit['category_path']
        labels = path if type(path) is list else [path]
        fields = [name, *(label for label in labels if c['safe_label'](label, 128, refs))]
        public = [normalize(field).casefold() for field in fields]
        for term, bucket in zip(terms, buckets):
            if any(term in field for field in public):
                bucket.append(((term not in public[0],), row, None))
                matched.add(pair)
    if not matched:
        return unavailable('no_match')
    focus = sorted({pair[0] for pair in matched})
    fits, hints, _, remaining, _ = c['prepare_candidates'](constrained, focus, eligible, spellings, refs, int(checked))
    if hints['preparation']['constraints_unverified']:
        return unavailable('unsupported_request')
    allowed = {row[0] for _, row, _ in fits} & matched
    ranked = c['balanced_fits']([[fit for fit in bucket if fit[1][0] in allowed] for bucket in buckets])
    if not ranked:
        return unavailable('no_match')
    display = time.time()
    if not checked <= display < until:
        return unavailable('stale_snapshot')
    lines, selected, seen = [PREFIX], [], set()
    for _, row, _ in ranked:
        _, unit, name, _, _ = row
        grade, price, expiry = unit['grade'], unit['price_credits'], unit['expires_at']
        visible = (name, grade, price)
        if visible in seen or not c['current'](row, display):
            continue
        lifetime = '유통기한 미제공' if expiry is None else f'남은 시간 {max(0, expiry - math.ceil(display))}초'
        line = f"{name} · SKU {unit['sku']} · {grade}등급 · {price:,}크레딧 · {lifetime}"
        if len('\n'.join([*lines, line, ADVICE])) > c['REPLY_LIMIT']:
            continue
        lines.append(line)
        selected.append(row)
        seen.add(visible)
        if len(selected) == 3:
            break
    if not selected:
        return unavailable('output_budget' if any(c['current'](row, display) for _, row, _ in ranked) else 'selection_unavailable')
    final = time.time()
    if not display <= final < until:
        return unavailable('stale_snapshot')
    if any(not c['current'](row, final) for row in selected):
        return unavailable('selection_unavailable')
    if any(not c['at_limit'](row[1]['expires_at'] - final, value, bound)
           for row in selected for value, bound in remaining):
        return unavailable('selection_unavailable')
    return {'status': 'rendered', 'reply': '\n'.join([*lines, ADVICE]), 'observed_at': observed, 'valid_until': until}
