import hashlib
import math
import re
import time
import unicodedata

DEPENDENCY = 'tools/public_catalogue/logic.py'
PIN = '01a4a0dc912e02679091a3f6c98df3f0450ca2581b920d1d650e2fa0fa2a4c89'
PREFIX = '유사어로 찾은 참고 후보입니다. 정확한 상품 일치와 요청 조건 전체의 충족 여부는 확인되지 않았습니다. 표시 가격은 공개 상품가입니다.'
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


def request_selector(text, c, eligible):
    # Remove only the public request's subject. Keep all constraint and exclusion spans.
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
    if (NEGATION.search(positive) or c['UNPARSED_EXCLUSION'].search(positive)
            or c['OTHER_REQUEST'].search(positive) or re.search(r'또는|혹은|그리고|\b(?:and|or)\b', positive, re.I)):
        return None
    remainder = list(positive)
    for key in ('PRICE_REQUEST', 'TIME_REQUEST', 'GRADE_REQUEST', 'QUANTITY'):
        for match in c[key].finditer(positive):
            suffix = c['AFTER_SELECTOR'].match(positive, match.end()) if key in ('QUANTITY', 'GRADE_REQUEST') else None
            end = suffix.end() if suffix else match.end()
            remainder[match.start():end] = ' ' * (end - match.start())
    remainder = ''.join(remainder)
    if UNVERIFIED.search(remainder) or any(match[0].endswith('만') for match in c['PREP_FACT'].finditer(remainder)):
        return None
    remainder = c['PREP_FACT'].sub(lambda match: ' ' * len(match[0]), remainder)
    if re.search(r'[^\w\s.,?!·]|\d|_', remainder):
        return None
    words = list(re.finditer(r'[^\W\d_]+', remainder))
    if any(word[0].casefold() in UNBOUND for word in words):
        return None
    subjects = [word for word in words if word[0].casefold() not in c['PREP_PLAIN']]
    if len(subjects) != 1 or subjects[0][0].endswith(('만', '없이', '없는')):
        return None
    start, end = subjects[0].span()
    constrained = text[:start] + ' ' * (end - start) + text[end:]
    if c['remove_exclusions'](constrained, roots, compounds)[1] != negative:
        return None
    return constrained


def run(args, kit):
    if type(args) is not dict or set(args) != {'op', 'text', 'queries'} or args['op'] != 'semantic_candidates':
        return unavailable('invalid_args')
    text, queries = args['text'], args['queries']
    if (type(text) is not str or not 1 <= len(text) <= 1500 or type(queries) is not list
            or not 1 <= len(queries) <= 2 or any(type(q) is not str or not 1 <= len(q) <= 48 for q in queries)):
        return unavailable('invalid_args')
    c = load_catalogue()
    if c is None:
        return unavailable('dependency_unavailable')
    if any(unicodedata.category(ch).startswith('C') or unicodedata.category(ch) in ('Zl', 'Zp') for ch in text):
        return unavailable('unsupported_request')
    text = normalize(' '.join(text.split()))
    text = c['PACK_SLASH'].sub(lambda match: match[0].replace('/', ' '), text)
    if (not c['safe_label'](text, 1500, (), query=True) or SKU.search(text) or EXACT.search(text)
            or RESTRICTED.search(text) or c['NO_ALTERNATIVE'].search(text) or c['UNKNOWN_FACT'].search(text)
            or not INTENT.search(text)):
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
    if not c['safe_label'](text, 1500, refs, query=True):
        return unavailable('unsupported_request')
    if any(not c['safe_label'](term, 48, refs, query=True) for term in terms):
        return unavailable('unsafe_query')
    eligible = [row for row in rows if row[2] is not None and c['current'](row, checked)]
    constrained = request_selector(text, c, eligible)
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
        line = f'{name} · {grade}등급 · {price:,}크레딧 · {lifetime}'
        if sum(map(len, lines)) + len(lines) + len(line) > c['REPLY_LIMIT']:
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
    return {'status': 'rendered', 'reply': '\n'.join(lines), 'observed_at': observed, 'valid_until': until}
