import ast
from contextlib import ExitStack, closing
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from math import isfinite
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
from time import monotonic
from types import ModuleType
import unicodedata

import httpx

SHA = 'c15424eacded61da86e9f27303b16a705287cecf81c5254a2da5360db3ee9b48'
MODULE = '_outseop_r4_pinned_forum_v5'
POLICY = Path('state/r4-benefits/first-purchase-bonus-policy.json')
KST = timezone(timedelta(hours=9))
PARENT = None
VISIBLE = ('sku','name','grade','price','category','expiry','certificate')


def edit(source, old, new):
    if source.count(old) != 1:
        raise ValueError('pinned publisher edit must match once')
    return source.replace(old, new, 1)


def add_grade_base(tree):
    function, = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'stock_offers']
    candidates = []
    for node in ast.walk(function):
        if isinstance(node, ast.Dict):
            fields = {key.value for key in node.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)}
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'dict':
            fields = {keyword.arg for keyword in node.keywords}
        else:
            continue
        if {'sku','grade','price'} <= fields:
            candidates.append(node)
    offer, = candidates
    base = ast.Name(id='base', ctx=ast.Load())
    if isinstance(offer, ast.Dict):
        offer.keys.append(ast.Constant(value='_base'))
        offer.values.append(base)
    else:
        offer.keywords.append(ast.keyword(arg='_base', value=base))


def load_parent():
    path = Path.cwd() / 'codex-r4' / 'forum.py'
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != SHA:
        raise ValueError('forum parent SHA-256 mismatch')
    source = raw.decode('utf-8')
    tree = ast.parse(source, str(path))
    add_grade_base(tree)
    parent = ModuleType(MODULE)
    parent.__file__ = str(path)
    exec(compile(ast.fix_missing_locations(tree), str(path), 'exec'), parent.__dict__)
    start = source.index('def forum_publish(')
    publisher = source[start:source.index('\ndef forum_reconcile(', start)]
    publisher = edit(publisher,
        '    rendered=render(offer,thread,market.shop_url,now)',
        '    if action=="spotlight" and not spotlight_eligible(db,offer,now,rates):\n        return {"status":"already_attempted"}\n    if action=="reply" and not fresh_match(market,thread,offer,int(time.time())):\n        return {"status":"no_fresh_matching_request"}\n    rendered=render_verified(db,market,offer,thread,now)')
    publisher = edit(publisher,
        '"SELECT id FROM forum_publication WHERE thread=? OR sku=? AND created>?",thread,sku,now-rates[1]',
        '"SELECT id FROM forum_publication WHERE thread=? OR (? IS NULL AND thread IS NULL AND sku=? AND created>?)",thread,thread,sku,now-rates[1]')
    publisher = edit(publisher,
        '(content=? AND created>?)",\n                    fingerprint,rendered,now-DAY',
        '(thread IS ? AND content=? AND created>?)",\n                    fingerprint,thread,rendered,now-DAY')
    fingerprint = parent.offer_fingerprint
    parent.offer_fingerprint = lambda offer, thread: fingerprint(public_offer(offer), thread)
    parent.available_options = available_options
    parent.spotlight_eligible = spotlight_eligible
    parent.render_verified = render_verified
    parent.fresh_match = fresh_match
    parent.forum_context = legacy_context
    parent.Market = type('ForumMarket', (parent.Market,), {'window_page': window_page})
    exec(compile(publisher, str(path), 'exec'), parent.__dict__)
    sys.modules[MODULE] = parent
    return parent


def public_offer(offer):
    return {key: value for key, value in offer.items() if key != '_base'}


def window_page(self, since, limit, deadline):
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise ValueError('forum read budget exhausted')
    response = httpx.get('https://market.ourolabs.ai/api/forum', params={'since': since, 'limit': limit},
                         timeout=min(1.25, remaining), trust_env=False)
    response.raise_for_status()
    return response.json()


def checked_page(market, since, limit, deadline):
    if monotonic() >= deadline:
        raise ValueError('forum read budget exhausted')
    rows = market.window_page(since, limit, deadline)
    if monotonic() >= deadline or not isinstance(rows, list) or len(rows) > limit:
        raise ValueError('invalid forum page')
    previous_id, previous_ts = since, -1
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('invalid forum row')
        ident, ts = row.get('id'), row.get('ts')
        if (type(ident) is not int or not previous_id < ident <= 2**63 - 1
                or type(ts) not in (int, float) or not isfinite(ts) or ts < previous_ts):
            raise ValueError('invalid forum order')
        previous_id, previous_ts = ident, ts
    return rows


REQUEST_FIELDS = ('id','ts','round','role','author','text')
READ_ERRORS = (httpx.HTTPError,OSError,ValueError,TypeError,OverflowError)


def request_facts(row):
    return tuple(row.get(key) for key in REQUEST_FIELDS)


def public_root(row):
    return (row.get('thread') is None and all(key not in row or row[key] is False
            for key in ('hidden','deleted','private','is_hidden','is_deleted','is_private'))
            and ('visibility' not in row or row['visibility'] == 'public')
            and ('public' not in row or row['public'] is True)
            and ('is_public' not in row or row['is_public'] is True)
            and row.get('status') not in ('hidden','deleted','private','removed','redacted')
            and row.get('deleted_at') is None and row.get('hidden_at') is None)


def same_observation(left, right):
    return request_facts(left) == request_facts(right) and public_root(left) == public_root(right)


def request_window(market, latest, now, deadline):
    cutoff = now - PARENT.THREAD_MAX_AGE
    if not latest:
        return []
    tip = latest[-1]['id']
    if len(latest) < 100 or latest[0]['ts'] < cutoff or latest[0]['id'] == 1:
        return [row for row in latest if cutoff <= row['ts'] <= now]
    low, high, cursor = 1, latest[0]['id'] - 1, None
    probes = {}
    for _ in range(63):
        if low > high:
            break
        middle = (low + high) // 2
        probe = checked_page(market, middle, 1, deadline)
        if not probe or probe[0]['id'] > tip:
            raise ValueError('forum seek lost its anchor')
        row = probe[0]
        previous = probes.setdefault(row['id'], row)
        if not same_observation(previous, row):
            raise ValueError('forum seek returned contradictory rows')
        if row['ts'] < cutoff:
            low = row['id']
        else:
            cursor = middle
            high = middle - 1
    if low <= high or cursor is None or cursor == 1:
        raise ValueError('forum cutoff could not be established')
    result = []
    last_ts = cutoff
    overlap = iter(latest)
    next_latest = next(overlap, None)
    for _ in range(30):
        page = checked_page(market, cursor, 100, deadline)
        if not page or page[0]['ts'] < last_ts:
            raise ValueError('forum scan lost continuity')
        for row in page:
            ident = row['id']
            if ident > tip or (ident in probes and not same_observation(row, probes[ident])):
                raise ValueError('forum scan returned contradictory rows')
            if next_latest is not None and ident >= next_latest['id']:
                if ident != next_latest['id'] or not same_observation(row, next_latest):
                    raise ValueError('forum scan disagrees with latest page')
                next_latest = next(overlap, None)
            if row['ts'] <= now:
                result.append(row)
            if ident == tip and next_latest is None:
                return result
        cursor, last_ts = page[-1]['id'], page[-1]['ts']
    raise ValueError('forum scan exceeded its page limit')


SKU = re.compile(r'(?<![A-Za-z0-9])[FG][A-Fa-f0-9]{8}(?![A-Za-z0-9])', re.I)
GRADE = re.compile(r'(?<![A-Za-z0-9])([ABC])\s*(?:등급|급)(?:\s*(제외(?:하고|한)?|아닌|말고))?', re.I)
CAP = re.compile(r'(?<![0-9.,])([1-9][0-9]{0,2}(?:,[0-9]{3})+|[0-9]+)\s*(?:크레딧|credits?)\s*(?:이하|이내|까지)(?![가-힣A-Za-z])', re.I)
LIFE = re.compile(r'(?:(?:남은\s*유통(?:기한|시간)|유통(?:기한|시간)|소비기한)\s*)?([1-9][0-9]{0,3})\s*(시간|일)\s*(?:이상\s*남은|이상|넘게\s*남은)(?![가-힣])')
PACK = re.compile(r'(?<![0-9.,])([1-9][0-9]{0,5})\s*(ml|kg|g|l|구|개입|개들이|개|팩|봉|병|캔|입|매)(?![A-Za-z가-힣])', re.I)
CERT = re.compile(r'(?:시장\s*)?인증서(?:가)?\s*(?:필수|있는|첨부된|포함)(?![가-힣])')
ASK = re.compile(r'구해\s*주세요|구해요|구합니다|구해\s*봅니다|찾아\s*주세요|찾아요|찾습니다|삽니다|사고\s*싶(?:어요|습니다)|구매\s*(?:희망(?:합니다)?|하고\s*싶(?:어요|습니다))|(?:견적|가격)\s*(?:부탁(?:드립니다)?|주세요)|looking (?:for|to buy)|want to buy', re.I)
EXCLUDE = re.compile(r'불만|리뷰|후기|평가|환불|반품|취소|영수증|증빙|인증샷|실결제|구매\s*(?:기록|결과)|구매했|샀어요|받았|배송\s*문제|미인도|비공개|개인\s*정보|연락처|주소|쪽지|알레르|알러지|무첨가|무가당|글루텐|비건|유기농|할랄|건강|저당|저염|제로|무설탕|총액|총\s*비용|총\s*가격|실구매가|배송비|수수료|세금|포함가|제외\s*가격|또는|혹은|아무거나|상관없|아니면|[/?@]|\b(?:review|refund|bought|purchased|all[ -]?in)\b', re.I)
GENERIC = set('상품 기타 제품 필요 생활 식품 가구 용품 판매 구매 무료배송 배송 세트 구성 단품 포장 행사 할인 특가 정품 수입 국내 국산 신선 냉장 냉동 상온 가공 일반 추천 소형 대형 혼합 오리지널 기본 옵션 시장 매장 재고 가격 박스 용량 과일 채소 음료 간식 식료품 생활용품 신선식품 유제품 가공식품 ml kg sku'.split())
ALIASES = ({'계란','달걀'}, {'두유','소이밀크'})
FOOD = re.compile(r'^(?:식품|신선식품|가공식품|식료품|농축산물|축산물|유제품|음료|음료수|food|groceries|beverages)$', re.I)
APPLIANCE = re.compile(r'메이커|제조기|조리기|분쇄기|블렌더|믹서|가전|주방\s*(?:용품|기기)|부품|보관함|트레이|커버|\b(?:maker|machine|appliance|blender|accessory)\b', re.I)
FILLER = re.compile(r'(?<![가-힣A-Za-z])(?:안녕하세요|감사합니다|부탁드립니다|혹시|현재|지금|오늘|상품|제품|조건|기준|한도|예산|제|좀|주세요)(?![가-힣A-Za-z])')
MULTIPACK = re.compile(r'\d\s*[xX×*+]|[xX×*+]\s*\d')


def normalize(text):
    return ' '.join(unicodedata.normalize('NFKC', text).split())


def product_words(offer):
    label = normalize(offer['name'])
    name = PACK.sub(' ', label)
    categories = [normalize(part) for part in offer['category'].split('>')]
    title = set(re.findall(r'[가-힣]{2,}|[a-z]{2,}', name.lower())) - GENERIC
    leaf = set(re.findall(r'[가-힣]{2,}|[a-z]{2,}', categories[-1].lower())) - GENERIC
    words = title | leaf
    for pair in ALIASES:
        if not words & pair:
            continue
        if not APPLIANCE.search(' '.join([label, *categories])) and (
                any(FOOD.fullmatch(part) for part in categories) or title and title <= pair):
            words.update(pair)
        else:
            words.difference_update(pair)
    return sorted(words, key=lambda word: (-len(word), word))


def pack_terms(text):
    return {(int(number), {'개입':'개','개들이':'개'}.get(unit.lower(), unit.lower()))
            for number, unit in PACK.findall(text)}


def is_match(post, offer, now):
    ts, author, raw = post.get('ts'), post.get('author'), post.get('text')
    if (not public_root(post) or type(post.get('round')) is not int or post['round'] != 4
            or post.get('role') != 'buyer' or not isinstance(author, str) or not author.strip()
            or author.strip().casefold() == PARENT.shop.SHOP.casefold()
            or type(ts) not in (int, float) or not 0 <= now-ts <= PARENT.THREAD_MAX_AGE
            or not isinstance(raw, str) or not 1 <= len(raw) <= 2000
            or any(unicodedata.category(c) in ('Cc','Cf','Cs') and c not in '\r\n\t' for c in raw)):
        return False
    text = normalize(raw)
    if len(ASK.findall(text)) != 1 or EXCLUDE.search(text):
        return False
    skus = {value.casefold() for value in SKU.findall(text)}
    if skus and skus != {offer['sku'].casefold()}:
        return False
    grades = GRADE.findall(text)
    positive = {grade.upper() for grade, excluded in grades if not excluded}
    negative = {grade.upper() for grade, excluded in grades if excluded}
    if (positive and positive != {offer['grade']}) or offer['grade'] in negative:
        return False
    caps = CAP.findall(text)
    if len(caps) > 1 or caps and offer['price'] > int(caps[0].replace(',', '')):
        return False
    expiry = offer['expiry']
    for count, unit in LIFE.findall(text):
        if expiry is None or expiry-now < int(count)*(86400 if unit == '일' else 3600):
            return False
    if CERT.search(text) and not offer['certificate']:
        return False
    rest = CERT.sub(' ', LIFE.sub(' ', CAP.sub(' ', GRADE.sub(' ', SKU.sub(' ', ASK.sub(' ', text))))))
    product_seen = False
    for word in product_words(offer):
        pattern = r'(?<![가-힣A-Za-z0-9])' + re.escape(word) + r'(?:으로|에서|에게|을|를|은|는|이|가|도|만|과|와|로)?(?![가-힣A-Za-z])'
        rest, hits = re.subn(pattern, ' ', rest, flags=re.I)
        product_seen = product_seen or bool(hits)
    if (not skus and not product_seen) or MULTIPACK.search(rest):
        return False
    requested = pack_terms(rest)
    if requested:
        label = normalize(offer['name'])
        label_terms = pack_terms(label)
        if MULTIPACK.search(label) or not requested <= label_terms or len(PACK.findall(rest)) != len(requested):
            return False
        if any(sum(other_unit == unit for _, other_unit in label_terms) != 1 for _, unit in requested):
            return False
        rest = PACK.sub(' ', rest)
    return not re.sub(r'[\s,.:!()\[\]·~]+', '', FILLER.sub(' ', rest))


def fresh_match(market, thread, offer, now):
    evidence = getattr(market, '_reply_evidence', {}).get(thread)
    if evidence is None:
        return False
    deadline = monotonic()+2
    try:
        if thread == 1:
            rows = checked_page(market, 0, 100, deadline)
            fresh = next((row for row in rows if row['id'] == 1), None)
        else:
            rows = checked_page(market, thread-1, 1, deadline)
            fresh = rows[0] if rows else None
        return (fresh is not None and same_observation(evidence, fresh)
                and is_match(fresh, offer, now))
    except READ_ERRORS:
        return False


def spotlight_eligible(db, offer, now, rates):
    return not PARENT.shop.one(db,
        "SELECT id FROM forum_publication WHERE (thread IS NULL AND sku=? AND created>?) OR (fingerprint=? AND status!='declined') LIMIT 1",
        offer['sku'], now-rates[1], PARENT.offer_fingerprint(offer, None))


def available_options(db, market, now, rates):
    deadline = monotonic()+15
    market._reply_evidence = {}
    market._request_coverage = {'complete':False,'since':now-PARENT.THREAD_MAX_AGE}
    latest = checked_page(market, 0, 100, deadline)
    if any(p.get('author') == PARENT.shop.SHOP and p.get('role') == 'shop' and p.get('round') == 4
           and now-p['ts'] < PARENT.POST_GAP for p in latest):
        return latest, [], [], False
    prior = PARENT.shop.one(db, 'SELECT max(created) FROM forum_publication WHERE thread IS NULL')[0]
    spotlight = prior is None or now-prior >= max(3600,rates[0])
    offers = PARENT.stock_offers(db, market, now)
    replies = []
    if not offers:
        return latest, offers, replies, spotlight
    try:
        requests = request_window(market, latest, now, deadline)
        market._request_coverage['complete'] = True
    except READ_ERRORS:
        requests = latest
        if latest:
            market._request_coverage['since'] = min(now,max(now-PARENT.THREAD_MAX_AGE,int(latest[0]['ts'])))
    for row in reversed(requests):
        if row.get('role') != 'buyer' or row.get('round') != 4:
            continue
        matched = [{'sku': offer['sku'], 'grade': offer['grade']} for offer in offers if is_match(row, offer, now)]
        if not matched or PARENT.shop.one(db, 'SELECT id FROM forum_publication WHERE thread=? LIMIT 1', row['id']):
            continue
        market._reply_evidence[row['id']] = row.copy()
        replies.append({'thread': row['id'], 'request': PARENT.public_text(row['text']), 'eligible': matched[:8]})
        if len(replies) == 8:
            break
    return latest, offers, replies, spotlight


def option_items(db, offers, replies, spotlight, now, rates, flag):
    reply_keys = {(item['sku'],item['grade']) for reply in replies for item in reply['eligible']}
    items = []
    for offer in offers:
        eligible = bool(spotlight and spotlight_eligible(db, offer, now, rates))
        if eligible or (offer['sku'],offer['grade']) in reply_keys:
            item = {key: offer[key] for key in VISIBLE}
            if flag:
                item['spotlight_eligible'] = eligible
            items.append(item)
    return items


def legacy_context(db, market, now, rates):
    blocked = PARENT.cooldown(db, now, rates)
    if blocked:
        return {'status': blocked}
    _, offers, replies, spotlight = available_options(db, market, now, rates)
    return {'status':'options', 'spotlight_allowed':spotlight,
            'items':option_items(db, offers, replies, spotlight, now, rates, False)[:16],
            'reply_options':replies, 'request_coverage':market._request_coverage}


GRADE_LINE = re.compile(r'^.+ \(([FG][A-Fa-f0-9]{8})\) · ([ABC])등급 · 상품가 [0-9,]+ 크레딧$')


def spotlight_history(db, now):
    rows = db.execute('''SELECT post,sku,content,created FROM forum_publication
        WHERE shop=? AND round=4 AND thread IS NULL AND status='posted' AND post>0
        AND typeof(post)='integer' AND typeof(created)='integer' AND created>0 AND created<=?
        ORDER BY created DESC,post DESC''', (PARENT.shop.SHOP,now))
    history = []
    for row in rows:
        paragraphs = re.split(r'\r?\n[ \t]*\r?\n', row['content'].strip()) if isinstance(row['content'], str) else []
        lines = paragraphs[1].splitlines() if len(paragraphs)>1 else []
        matches = [match for line in lines if (match := GRADE_LINE.fullmatch(line))]
        if len(matches)!=1 or matches[0][1]!=row['sku']:
            continue
        history.append({'grade':matches[0][2], 'category':None, 'at':row['created']})
        if len(history)==512:
            break
    return history


def slate_context(market, now, rates):
    path = Path(PARENT.shop.DB).resolve().as_uri()
    with closing(sqlite3.connect(path+'?mode=ro', uri=True, timeout=1)) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        blocked = PARENT.cooldown(db, now, rates)
        if blocked:
            return {'status':blocked}
        _, offers, replies, spotlight = available_options(db, market, now, rates)
        return {'status':'options','source':{'schema':'outseop-r4.forum-candidates.v1',
                'observed_at':now, 'valid_until':now+90, 'spotlight_allowed':spotlight,
                'own_spotlight_history':spotlight_history(db, now),
                'items':option_items(db, offers, replies, spotlight, now, rates, True), 'reply_options':replies}}


def unique_object(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError('duplicate policy key')
    return result


def owned_secure(info, directory):
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    return (kind(info.st_mode) and info.st_uid == os.geteuid() and not info.st_mode & 0o022
            and (directory or info.st_nlink == 1))


def stat_identity(info):
    return (info.st_dev,info.st_ino,info.st_mtime_ns,info.st_ctime_ns,info.st_size,stat.S_IFMT(info.st_mode))


def read_policy():
    if POLICY.is_absolute() or '..' in POLICY.parts:
        return None
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY
    with ExitStack() as stack:
        root = os.open('.', flags)
        stack.callback(os.close,root)
        if not owned_secure(os.fstat(root),True):
            return None
        directories = []
        directory = root
        for part in POLICY.parts[:-1]:
            child = os.open(part,flags,dir_fd=directory)
            stack.callback(os.close,child)
            info = os.fstat(child)
            if not owned_secure(info,True):
                return None
            directories.append((directory,part,child,info))
            directory = child
        leaf = POLICY.name
        fd = os.open(leaf,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory)
        stack.callback(os.close,fd)
        before = os.fstat(fd)
        if not owned_secure(before,False) or not 0 < before.st_size <= 4096:
            return None
        with os.fdopen(fd,'rb',closefd=False) as handle:
            raw = handle.read(before.st_size)
        after = os.fstat(fd)
        current = os.stat(leaf,dir_fd=directory,follow_symlinks=False)
        if (len(raw)!=before.st_size or not owned_secure(after,False) or not owned_secure(current,False)
                or stat_identity(before)!=stat_identity(after) or stat_identity(before)!=stat_identity(current)
                or not owned_secure(os.fstat(root),True)):
            return None
        for parent,part,child,first in directories:
            reopened = os.stat(part,dir_fd=parent,follow_symlinks=False)
            held = os.fstat(child)
            if (not owned_secure(reopened,True) or not owned_secure(held,True)
                    or stat_identity(first)!=stat_identity(reopened) or stat_identity(first)!=stat_identity(held)):
                return None
        return raw


def active_policy(now):
    raw = read_policy()
    if raw is None:
        return None
    policy = json.loads(raw, object_pairs_hook=unique_object)
    if not isinstance(policy, dict) or set(policy) != {'enabled','id','start','end','lifetime_budget'}:
        return None
    ident, start, end, budget = (policy[key] for key in ('id','start','end','lifetime_budget'))
    if (policy['enabled'] is not True or not isinstance(ident,str) or not ident.strip() or len(ident)>120
            or type(start) not in (int,float) or type(end) not in (int,float)
            or not isfinite(start) or not isfinite(end) or not 0<end-start<=72*3600
            or not start<=now<end or type(budget) is not int or not 1<=budget<=50000):
        return None
    return policy


def identifier(value):
    return '"'+value.replace('"','""')+'"'


SQL_TOKEN = re.compile(r'''''(?:[^']|'')*'|"(?:[^"]|"")*"|`[^`]*`|\[[^\]]*\]|[A-Za-z_][A-Za-z_0-9]*|[0-9]+|[^\s]''')
WALLET_FORM = re.compile(r'0[xX][0-9a-fA-F]{40}\Z')
AWARD_DDL = '''CREATE TABLE welcome_award (
    payer TEXT NOT NULL PRIMARY KEY CHECK(payer=lower(payer)),
    sale_id TEXT NOT NULL UNIQUE,
    amount INTEGER NOT NULL CHECK(typeof(amount)='integer' AND amount BETWEEN 1 AND 5000),
    granted_at INTEGER NOT NULL,
    earned_event_id NOT NULL
)'''


def ddl_tokens(sql):
    if not isinstance(sql,str):
        return ()
    tokens = []
    for token in SQL_TOKEN.findall(sql):
        if token.startswith("'"):
            tokens.append(token)
        elif token[0] in '"`[' and re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*',token[1:-1]):
            tokens.append(token[1:-1].lower())
        else:
            tokens.append(token.lower())
    if tokens[:5] == ['create','table','if','not','exists']:
        del tokens[2:5]
    if tokens and tokens[-1]==';':
        tokens.pop()
    return tuple(tokens)


def tables(db):
    return dict(db.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))


def original_tables():
    with closing(sqlite3.connect(':memory:')) as db:
        db.executescript(PARENT.shop.SCHEMA)
        return tables(db)


def table_columns(db,name):
    return {row[1] for row in db.execute('PRAGMA table_xinfo('+identifier(name)+')')}


def wallet(value):
    return value.lower() if isinstance(value,str) and WALLET_FORM.fullmatch(value) else None


def registered_identity(db, market, live, original):
    shop_name = PARENT.shop.SHOP
    registered = wallet(market.kit.address('shop'))
    if market.kit.name != shop_name or registered is None or wallet(market.wallet)!=registered:
        return False
    candidates = []
    for name, ddl in live.items():
        columns = table_columns(db,name)
        marker = 'identity' in name.lower()
        shops = columns & ({'shop','shop_name','name','agent'} if marker else {'shop_name'})
        wallets = columns & {'wallet','wallet_address','address','shop_wallet'}
        if marker or shops and wallets:
            if len(shops)!=1 or len(wallets)!=1 or ddl_tokens(ddl)!=ddl_tokens(original.get(name)):
                return False
            shop_column = identifier(shops.pop())
            address_column = identifier(wallets.pop())
            candidates.extend(tuple(row) for row in db.execute(
                f'SELECT {shop_column},{address_column} FROM {identifier(name)} LIMIT 2'))
    return len(candidates)==1 and candidates[0][0]==shop_name and wallet(candidates[0][1])==registered


def verified_unawarded_sales(db, live, original):
    verified = False
    for name, ddl in original.items():
        if not name.lower().startswith('sale'):
            continue
        tokens = ddl_tokens(ddl)
        if not {"'settled'","'refunded'"} <= set(tokens):
            continue
        if ddl_tokens(live.get(name))!=tokens:
            return False
        states = table_columns(db,name) & {'status','state'}
        if len(states)!=1:
            return False
        state = identifier(states.pop())
        if db.execute('SELECT 1 FROM '+identifier(name)+' WHERE '+state+" IN ('settled','refunded') LIMIT 1").fetchone():
            return False
        verified = True
    return verified


def welcome_spend(db, live, original):
    objects = db.execute("SELECT type,name FROM sqlite_master WHERE type IN ('table','view') AND lower(name) LIKE '%award%'")
    objects = [tuple(row) for row in objects]
    if not objects:
        return 0 if verified_unawarded_sales(db,live,original) else None
    if objects != [('table','welcome_award')] or ddl_tokens(live.get('welcome_award'))!=ddl_tokens(AWARD_DDL):
        return None
    if table_columns(db,'welcome_award') != {'payer','sale_id','amount','granted_at','earned_event_id'}:
        return None
    total = 0
    for payer, amount in db.execute('SELECT payer,amount FROM welcome_award'):
        if wallet(payer)!=payer or not isinstance(payer,str) or type(amount) is not int or not 1<=amount<=5000:
            return None
        total += amount
    return total


def render_verified(db, market, offer, thread, now):
    original_text = PARENT.render(public_offer(offer), thread, market.shop_url, now)
    try:
        base = offer.get('_base')
        if type(base) is not int or base<=0:
            return original_text
        policy = active_policy(now)
        if policy is None:
            return original_text
        live, original = tables(db), original_tables()
        if not registered_identity(db,market,live,original):
            return original_text
        spent = welcome_spend(db,live,original)
        award = min(5000,base*5//100)
        if spent is None or award<=0 or policy['lifetime_budget']-spent<award:
            return original_text
        due = datetime.fromtimestamp(policy['end'],KST).strftime('%Y-%m-%d %H:%M:%S KST')
    except (sqlite3.Error,OSError,ValueError,TypeError,OverflowError,AttributeError,NotImplementedError):
        return original_text
    return original_text + (f'\n\n첫 구매 추가 5% 적립. 해당 등급 판매 기준가의 5%를 최대 5,000 크레딧까지 적립합니다. '
                            f'원결제 지갑을 확인하고 첫 정상 정산·인도가 완료되면 지갑당 1회 적용합니다. '
                            f'전체 한도는 {policy["lifetime_budget"]:,} 크레딧이며 종료 시각은 {due}입니다. '
                            '기한 내 정산 순서대로 지급액 전액이 남은 한도 안에 드는 거래에 적용합니다. '
                            '첫 정산일부터 7일 동안 다음 거래부터 사용할 수 있으며 환불 시 회수됩니다.')


def run(args, kit):
    global PARENT
    try:
        if PARENT is None:
            PARENT = load_parent()
        if not isinstance(args,dict):
            return {'status':'invalid_action'}
        if args.get('action') == '_test_parent' and kit.testing:
            return {'status':'parent_verified','sha256':SHA}
        if args.get('action') != 'slate_context':
            return PARENT.run(args,kit)
        rates = PARENT.PRESETS.get(args.get('preset','aggressive'))
        if rates is None:
            return {'status':'invalid_preset'}
        return slate_context(PARENT.Market(kit),int(PARENT.time.time()),rates)
    except (OSError,sqlite3.Error,httpx.HTTPError,ValueError,TypeError,KeyError,AttributeError,ImportError,OverflowError):
        return {'status':'authoritative_check_unavailable'}
    except Exception as error:
        if PARENT is not None and isinstance(error,PARENT.shop.Unavailable):
            return {'status':'authoritative_check_unavailable'}
        raise
