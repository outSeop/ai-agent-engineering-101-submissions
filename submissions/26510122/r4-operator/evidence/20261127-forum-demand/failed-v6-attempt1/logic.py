from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
import re
import sqlite3
import sys
from time import monotonic
from types import ModuleType
import unicodedata

import httpx


PARENT_SHA = 'c15424eacded61da86e9f27303b16a705287cecf81c5254a2da5360db3ee9b48'
PARENT_MODULE = '_outseop_r4_pinned_forum_v5'
MARKET_URL = 'https://market.ourolabs.ai'
STATE = Path('state/r4-benefits')
POLICY = STATE / 'first-purchase-bonus-policy.json'
WALLET = '0xF37173b89fc9da7AA3f42fCF839E7cd611548f38'
KST = timezone(timedelta(hours=9))


def exact_edit(source, old, new):
    if source.count(old) != 1:
        raise ValueError('pinned publisher edit did not match exactly once')
    return source.replace(old, new, 1)


def load_parent():
    path = Path.cwd() / 'codex-r4' / 'forum.py'
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != PARENT_SHA:
        raise ValueError('forum parent has unexpected SHA-256')
    parent = ModuleType(PARENT_MODULE)
    parent.__file__ = str(path)
    exec(compile(raw, str(path), 'exec'), parent.__dict__)
    source = raw.decode('utf-8')
    start = source.index('def forum_publish(')
    end = source.index('\ndef forum_reconcile(', start)
    publisher = source[start:end]
    publisher = exact_edit(publisher,
        '    rendered=render(offer,thread,market.shop_url,now)',
        '    rendered=render_verified(db,market,offer,thread,now)')
    publisher = exact_edit(publisher,
        '"SELECT id FROM forum_publication WHERE thread=? OR sku=? AND created>?",thread,sku,now-rates[1]',
        '"SELECT id FROM forum_publication WHERE thread=? OR (? IS NULL AND thread IS NULL AND sku=? AND created>?)",thread,thread,sku,now-rates[1]')
    publisher = exact_edit(publisher,
        '(content=? AND created>?)",\n                    fingerprint,rendered,now-DAY',
        '(thread IS ? AND content=? AND created>?)",\n                    fingerprint,thread,rendered,now-DAY')
    parent.available_options = available_options
    parent.render_verified = render_verified
    exec(compile(publisher, str(path), 'exec'), parent.__dict__)
    parent.forum_context = legacy_context
    parent.Market = type('ForumMarket', (parent.Market,), {'window_page': window_page})
    sys.modules[PARENT_MODULE] = parent
    return parent


def window_page(self, since, limit, deadline):
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise ValueError('forum read budget exhausted')
    response = httpx.get(MARKET_URL + '/api/forum', params={'since': since, 'limit': limit},
                         timeout=min(1.25, remaining), trust_env=False)
    response.raise_for_status()
    return response.json()


def checked_page(market, since, limit, deadline):
    if monotonic() >= deadline:
        raise ValueError('forum read budget exhausted')
    rows = market.window_page(since, limit, deadline)
    if not isinstance(rows, list) or len(rows) > limit:
        raise ValueError('invalid forum page')
    previous_id, previous_ts = since, -1.0
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('invalid forum row')
        ident, ts = row.get('id'), row.get('ts')
        if (type(ident) is not int or ident <= previous_id or ident > 2**63 - 1
                or type(ts) not in (int, float) or not isfinite(ts) or ts < previous_ts):
            raise ValueError('invalid forum order')
        previous_id, previous_ts = ident, ts
    return rows


def request_window(market, latest, now, deadline):
    if not latest:
        return []
    cutoff = now - PARENT.THREAD_MAX_AGE
    tip = latest[-1]['id']
    if len(latest) < 100 or latest[0]['ts'] <= cutoff:
        return [row for row in latest if cutoff <= row['ts'] <= now]

    # A witnessed older row supplies the forward cursor. ID holes do not
    # establish a timestamp boundary. since=0 is reserved for the latest view.
    low, high, older = 2, latest[0]['id'] - 1, None
    for _ in range(63):
        if low > high:
            break
        middle = (low + high) // 2
        probe = checked_page(market, middle - 1, 1, deadline)
        if not probe or probe[0]['id'] > tip:
            raise ValueError('forum seek lost its anchor')
        row = probe[0]
        if row['ts'] < cutoff:
            older = row
            low = row['id'] + 1
        else:
            high = middle - 1
    if low <= high or older is None:
        raise ValueError('forum cutoff could not be established')

    cursor, last_ts = older['id'], older['ts']
    result = []
    for _ in range(30):
        page = checked_page(market, cursor, 100, deadline)
        if not page or page[0]['ts'] < last_ts:
            raise ValueError('forum scan lost continuity')
        for row in page:
            if row['id'] > tip:
                raise ValueError('forum scan skipped its anchor')
            if cutoff <= row['ts'] <= now:
                result.append(row)
            if row['id'] == tip:
                if row != latest[-1]:
                    raise ValueError('forum anchor changed')
                return result
        cursor, last_ts = page[-1]['id'], page[-1]['ts']
    raise ValueError('forum scan exceeded its page limit')


SKU = re.compile(r'(?<![A-Za-z0-9])[FG][A-Fa-f0-9]{8}(?![A-Za-z0-9])')
INT = r'(?:[1-9][0-9]{0,2}(?:,[0-9]{3})+|[0-9]+)'
GRADE = re.compile(r'(?<![A-Za-z0-9])([ABC])\s*(?:등급|급)(?:\s*(제외(?:하고|한)?|아닌|말고))?')
CAP = re.compile(r'(?<![0-9.,])(' + INT + r')\s*(?:크레딧|credits?)\s*(?:이하|이내|까지)(?![가-힣A-Za-z])', re.I)
LIFE = re.compile(r'(?:(?:남은\s*유통(?:기한|시간)|유통(?:기한|시간)|소비기한)\s*)?([1-9][0-9]{0,3})\s*(시간|일)\s*(?:이상\s*남은|이상|넘게\s*남은)(?![가-힣])')
PACK = re.compile(r'(?<![0-9.,])([1-9][0-9]{0,5})(?:\s*)(mL|kg|ml|g|L|l|구|개입|개들이|개|팩|봉|병|캔|입|매)(?![A-Za-z가-힣])', re.I)
CERT = re.compile(r'(?:시장\s*)?인증서(?:가)?\s*(?:필수|있는|첨부된|포함)(?![가-힣])')
ASK = re.compile(r'구해\s*주세요|구해요|구합니다|구해\s*봅니다|찾아\s*주세요|찾아요|찾습니다|삽니다|사고\s*싶(?:어요|습니다)|구매\s*(?:희망(?:합니다)?|하고\s*싶(?:어요|습니다))|(?:견적|가격)\s*(?:부탁(?:드립니다)?|주세요)', re.I)
EXCLUDE = re.compile(r'불만|리뷰|후기|평가|환불|반품|취소|영수증|증빙|인증샷|실결제|구매\s*(?:기록|결과)|구매했|샀어요|받았|배송\s*문제|미인도|비공개|개인\s*정보|연락처|주소|쪽지|알레르|알러지|무첨가|무가당|글루텐|비건|유기농|할랄|(?:또는|혹은|아무거나|상관없|아니면)|[/?@]|\b(?:review|refund|bought|purchased)\b', re.I)
GENERIC = set('상품 기타 제품 필요 생활 식품 가구 용품 판매 구매 무료배송 배송 세트 구성 단품 포장 행사 할인 특가 정품 수입 국내 국산 신선 냉장 냉동 상온 가공 일반 추천 소형 대형 혼합 오리지널 기본 옵션 시장 매장 재고 가격 박스 용량 과일 채소 음료 간식 식료품 생활용품 신선식품 유제품 가공식품'.split())
ALIASES = ({'계란', '달걀'}, {'두유', '소이밀크'})
TOKEN = re.compile(r'[가-힣]{2,}|[A-Za-z]{2,}')
PARTICLE = r'(?:으로|에서|에게|을|를|은|는|이|가|도|만|과|와|로)?'
FILLER = re.compile(r'(?<![가-힣A-Za-z])(?:안녕하세요|감사합니다|부탁드립니다|혹시|현재|지금|오늘|상품|제품|조건|기준|한도|예산|제|좀|주세요)(?![가-힣A-Za-z])')


def normalize(text):
    return ' '.join(unicodedata.normalize('NFKC', text).split())


def word_pattern(word):
    return re.compile(r'(?<![가-힣A-Za-z0-9])' + re.escape(word) + PARTICLE +
                      r'(?![가-힣A-Za-z0-9])', re.I)


def product_words(offer):
    name = normalize(offer['name'])
    leaf = normalize(offer['category'].split('>')[-1])
    words = {w.lower() for w in TOKEN.findall(name + ' ' + leaf)} - GENERIC
    words -= {'ml', 'kg', 'sku', 'a급', 'b급', 'c급'}
    for pair in ALIASES:
        if words & pair:
            words.update(pair)
    return sorted(words, key=lambda word: (-len(word), word))


def pack_terms(text):
    return {(int(number), {'개입': '개', '개들이': '개'}.get(unit.lower(), unit.lower()))
            for number, unit in PACK.findall(text)}


def is_match(post, offer, now):
    ts, author, raw = post.get('ts'), post.get('author'), post.get('text')
    if (type(post.get('round')) is not int or post['round'] != 4 or post.get('role') != 'buyer'
            or not isinstance(author, str) or not author.strip()
            or author.strip().casefold() == PARENT.shop.SHOP.casefold()
            or type(ts) not in (int, float) or not 0 <= now - ts <= PARENT.THREAD_MAX_AGE
            or not isinstance(raw, str) or not 1 <= len(raw) <= 2000
            or any(unicodedata.category(c) in ('Cc', 'Cf', 'Cs') and c not in '\r\n\t' for c in raw)):
        return False
    text = normalize(raw)
    if not ASK.search(text) or EXCLUDE.search(text):
        return False
    skus = {value.casefold() for value in SKU.findall(text)}
    if skus and skus != {offer['sku'].casefold()}:
        return False
    grades = GRADE.findall(text)
    positive = {grade for grade, excluded in grades if not excluded}
    negative = {grade for grade, excluded in grades if excluded}
    if (positive and positive != {offer['grade']}) or offer['grade'] in negative:
        return False
    caps = CAP.findall(text)
    if len(caps) > 1 or caps and offer['price'] > int(caps[0].replace(',', '')):
        return False
    remaining = LIFE.findall(text)
    expiry = offer['expiry']
    if remaining and (expiry is None or any(expiry - now < int(count) * (86400 if unit == '일' else 3600)
                                           for count, unit in remaining)):
        return False
    if CERT.search(text) and not offer['certificate']:
        return False
    rest = CERT.sub(' ', LIFE.sub(' ', CAP.sub(' ', GRADE.sub(' ', SKU.sub(' ', ASK.sub(' ', text))))))
    product_seen = False
    for word in product_words(offer):
        rest, hits = word_pattern(word).subn(' ', rest)
        product_seen = product_seen or bool(hits)
    if not skus and not product_seen:
        return False
    if re.search(r'\d\s*[xX×*]|[xX×*]\s*\d', rest):
        return False
    requested_pack = pack_terms(rest)
    if requested_pack:
        label = normalize(offer['name'])
        if re.search(r'\d\s*[xX×*]|[xX×*]\s*\d|\d\s*\+', label):
            return False
        label_pack = pack_terms(label)
        if not requested_pack <= label_pack or len(PACK.findall(rest)) != len(requested_pack):
            return False
        rest = PACK.sub(' ', rest)
    return not re.sub(r'[\s,.:!()\[\]·~]+', '', FILLER.sub(' ', rest))


def spotlight_sku_open(db, sku, now, rates):
    return not PARENT.shop.one(db,
        'SELECT id FROM forum_publication WHERE thread IS NULL AND sku=? AND created>? LIMIT 1',
        sku, now - rates[1])


def spotlight_eligible(db, offer, now, rates):
    return spotlight_sku_open(db, offer['sku'], now, rates) and not PARENT.shop.one(db,
        "SELECT id FROM forum_publication WHERE fingerprint=? AND status!='declined' LIMIT 1",
        PARENT.offer_fingerprint(offer, None))


def available_options(db, market, now, rates):
    deadline = monotonic() + 15
    latest = checked_page(market, 0, 100, deadline)
    if any(p.get('author') == PARENT.shop.SHOP and p.get('role') == 'shop' and p.get('round') == 4
           and now - p['ts'] < PARENT.POST_GAP for p in latest):
        return latest, [], [], False
    prior = PARENT.shop.one(db, 'SELECT max(created) FROM forum_publication WHERE thread IS NULL')[0]
    spotlight = prior is None or now - prior >= rates[0]
    offers = PARENT.stock_offers(db, market, now)
    replies = []
    if not offers:
        return latest, offers, replies, spotlight
    try:
        requests = request_window(market, latest, now, deadline)
    except (httpx.HTTPError, OSError, ValueError, TypeError, OverflowError):
        requests = []
    for row in reversed(requests):
        if row.get('role') != 'buyer' or row.get('round') != 4:
            continue
        matched = [{'sku': item['sku'], 'grade': item['grade']} for item in offers if is_match(row, item, now)]
        if not matched or PARENT.shop.one(db, 'SELECT id FROM forum_publication WHERE thread=? LIMIT 1', row['id']):
            continue
        replies.append({'thread': row['id'], 'request': PARENT.public_text(row['text']), 'eligible': matched[:8]})
        if len(replies) == 8:
            break
    return latest, offers, replies, spotlight


VISIBLE = ('sku', 'name', 'grade', 'price', 'category', 'expiry', 'certificate')


def option_items(db, offers, replies, spotlight, now, rates, include_flag):
    reply_keys = {(item['sku'], item['grade']) for reply in replies for item in reply['eligible']}
    items = []
    for offer in offers:
        eligible = bool(spotlight and spotlight_eligible(db, offer, now, rates))
        if eligible or (offer['sku'], offer['grade']) in reply_keys:
            item = {key: offer[key] for key in VISIBLE}
            if include_flag:
                item['spotlight_eligible'] = eligible
            items.append(item)
    return items


def legacy_context(db, market, now, rates):
    blocked = PARENT.cooldown(db, now, rates)
    if blocked:
        return {'status': blocked}
    _, offers, replies, spotlight = available_options(db, market, now, rates)
    items = option_items(db, offers, replies, spotlight, now, rates, False)
    return {'status': 'options', 'spotlight_allowed': spotlight, 'items': items[:16], 'reply_options': replies}


GRADE_LINE = re.compile(r'^.+ \(([FG][A-Fa-f0-9]{8})\) · ([ABC])등급 · 상품가 [0-9,]+ 크레딧$')


def spotlight_history(db, offers, now):
    categories = {}
    for offer in offers:
        if offer['category']:
            categories.setdefault(offer['sku'], set()).add(offer['category'])
    rows = db.execute("""SELECT post,sku,content,created FROM forum_publication
        WHERE shop=? AND round=4 AND thread IS NULL AND status='posted' AND post>0
        AND created>=0 AND created<=? ORDER BY created DESC,post DESC LIMIT 512""",
                      (PARENT.shop.SHOP, now))
    result = []
    for row in rows:
        if type(row['post']) is not int or not isinstance(row['content'], str):
            continue
        lines = row['content'].splitlines()
        if len(lines) < 3:
            continue
        match = GRADE_LINE.fullmatch(lines[2])
        if not match or match[1] != row['sku']:
            continue
        choices = categories.get(row['sku'], set())
        result.append({'post': row['post'], 'sku': row['sku'], 'grade': match[2],
                       'category': next(iter(choices)) if len(choices) == 1 else None, 'ts': row['created']})
    return result


def slate_context(market, now, rates):
    db_path = Path(PARENT.shop.DB).resolve()
    with sqlite3.connect(db_path.as_uri() + '?mode=ro', uri=True, timeout=1) as db:
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            blocked = PARENT.cooldown(db, now, rates)
            if blocked:
                return {'status': blocked}
            _, offers, replies, spotlight = available_options(db, market, now, rates)
            items = option_items(db, offers, replies, spotlight, now, rates, True)
            history = spotlight_history(db, offers, now)
            return {'status': 'options', 'source': {'schema': 'outseop-r4.forum-candidates.v1',
                    'observed_at': now, 'valid_until': now + 90, 'spotlight_allowed': spotlight,
                    'own_spotlight_history': history, 'items': items, 'reply_options': replies}}
        finally:
            db.close()


def unique_object(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError('duplicate policy key')
    return result


def active_policy(now):
    path = POLICY.absolute()
    if path.resolve(strict=True) != path or not path.is_file():
        return None
    with path.open('rb') as handle:
        raw = handle.read(4097)
    if len(raw) > 4096:
        return None
    policy = json.loads(raw, object_pairs_hook=unique_object)
    if not isinstance(policy, dict) or set(policy) != {'enabled', 'id', 'start', 'end', 'lifetime_budget'}:
        return None
    ident, start, end, budget = (policy[key] for key in ('id', 'start', 'end', 'lifetime_budget'))
    if (policy['enabled'] is not True or not isinstance(ident, str) or not ident.strip() or len(ident) > 120
            or type(start) not in (int, float) or type(end) not in (int, float)
            or not isfinite(start) or not isfinite(end) or not 0 < end - start <= 72 * 3600
            or not start <= now < end or type(budget) is not int or not 1 <= budget <= 50000):
        return None
    return policy


def quote_identifier(value):
    return '"' + value.replace('"', '""') + '"'


def verified_unawarded_sales(db):
    # The bound dispatcher initializes this schema. Only a declared sale-state
    # column with both terminal states in its DDL can establish this fallback.
    tables = db.execute("SELECT name,sql FROM sqlite_schema WHERE type='table' AND name LIKE 'sale%' LIMIT 33").fetchall()
    if len(tables) > 32:
        return False
    verified = False
    for name, ddl in tables:
        if not isinstance(ddl, str) or not all(re.search(r"['\"]" + state + r"['\"]", ddl, re.I)
                                               for state in ('settled', 'refunded')):
            continue
        columns = {row['name'] for row in db.execute('PRAGMA table_info(' + quote_identifier(name) + ')')}
        states = columns & {'status', 'state'}
        if len(states) != 1:
            return False
        state_column = quote_identifier(next(iter(states)))
        verified = True
        row = db.execute('SELECT 1 FROM ' + quote_identifier(name) + ' WHERE lower(' + state_column +
                         ") IN ('settled','refunded') LIMIT 1").fetchone()
        if row:
            return False
    return verified


def welcome_spend(db):
    table = db.execute("SELECT type FROM sqlite_schema WHERE name='welcome_award'").fetchone()
    if table is None:
        return 0 if verified_unawarded_sales(db) else None
    if table[0] != 'table':
        return None
    columns = {row['name']: row for row in db.execute('PRAGMA table_info(welcome_award)')}
    payer_fields = columns.keys() & {'payer', 'payer_wallet', 'payer_address'}
    amount_fields = columns.keys() & {'amount', 'amount_credits', 'credits', 'award_amount', 'original_amount', 'original_credits'}
    if len(payer_fields) != 1 or len(amount_fields) != 1:
        return None
    payer, amount = next(iter(payer_fields)), next(iter(amount_fields))
    if columns[amount]['type'].strip().upper() != 'INTEGER':
        return None
    primary_key = [row['name'] for row in columns.values() if row['pk']]
    unique = primary_key == [payer]
    for index in db.execute('PRAGMA index_list(welcome_award)'):
        if index['unique'] and not index['partial']:
            indexed = [row['name'] for row in db.execute('PRAGMA index_info(' + quote_identifier(index['name']) + ')')]
            unique = unique or indexed == [payer]
    if not unique:
        return None
    payer_sql, amount_sql = quote_identifier(payer), quote_identifier(amount)
    rows = db.execute(f'SELECT {payer_sql},typeof({amount_sql}),{amount_sql} FROM welcome_award LIMIT 50001')
    seen, total = set(), 0
    for address, storage, original in rows:
        if (not isinstance(address, str) or not re.fullmatch(r'0[xX][0-9a-fA-F]{40}', address)
                or address.lower() in seen or storage != 'integer' or type(original) is not int
                or not 1 <= original <= 5000):
            return None
        seen.add(address.lower())
        total += original
        if total >= 50000:
            return total
    return total


def render_verified(db, market, offer, thread, now):
    original = PARENT.render(offer, thread, market.shop_url, now)
    try:
        if (PARENT.shop.SHOP != 'outseop-r4' or market.wallet.lower() != WALLET.lower()
                or market.kit.address('shop').lower() != WALLET.lower()):
            return original
        policy = active_policy(now)
        if policy is None:
            return original
        award = min(5000, offer['price'] * 5 // 100)
        spent = welcome_spend(db)
        if spent is None or award <= 0 or policy['lifetime_budget'] - spent < award:
            return original
        due = datetime.fromtimestamp(policy['end'], KST).strftime('%Y-%m-%d %H:%M:%S KST')
    except (sqlite3.Error, OSError, ValueError, TypeError, OverflowError, AttributeError):
        return original
    return original + (f"\n\n첫 구매 추가 5% 적립. 해당 등급 판매 기준가의 5%를 최대 5,000 크레딧까지 적립합니다. "
                       f"최초 구매의 원결제 지갑 확인과 정산·인도가 완료된 지갑당 1회 적용합니다. "
                       f"전체 한도는 {policy['lifetime_budget']:,} 크레딧이며 종료 시각은 {due}입니다. "
                       "기한 내 정산 순서대로 한도 안에서 지급액 전액을 적립할 수 있는 거래에 적용합니다. "
                       "첫 정산일부터 7일 동안 다음 거래부터 사용할 수 있으며 환불 시 회수됩니다.")


PARENT = None


def run(args, kit):
    global PARENT
    try:
        if PARENT is None:
            PARENT = load_parent()
        if not isinstance(args, dict):
            return {'status': 'invalid_action'}
        if args.get('action') == '_test_parent' and kit.testing:
            return {'status': 'parent_verified', 'sha256': PARENT_SHA}
        if args.get('action') != 'slate_context':
            return PARENT.run(args, kit)
        rates = PARENT.PRESETS.get(args.get('preset', 'aggressive'))
        if rates is None:
            return {'status': 'invalid_preset'}
        market = PARENT.Market(kit)
        return slate_context(market, int(PARENT.time.time()), rates)
    except (OSError, sqlite3.Error, httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError, ImportError, OverflowError):
        return {'status': 'authoritative_check_unavailable'}
    except Exception as error:
        if PARENT is not None and isinstance(error, PARENT.shop.Unavailable):
            return {'status': 'authoritative_check_unavailable'}
        raise
