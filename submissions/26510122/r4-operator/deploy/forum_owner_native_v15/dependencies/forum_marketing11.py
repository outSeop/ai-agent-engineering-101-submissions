import ast
from contextvars import ContextVar
from datetime import datetime
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from threading import RLock
from time import monotonic
from types import FunctionType, ModuleType

V10 = ('codex-r4/forum_marketing10.py', 'bd80f8236c415ffc962b5b651f24232e8e34320a621145954abbbf0bedca073a')
V9 = ('codex-r4/forum_marketing9.py', 'b2edc8dba8c214a22074eb1f3db35ce5eb8234f444cf22710f025078b64e48e9')
LOCK = RLock()
OWNER = None
CURRENT = ContextVar('forum_marketing_current')
URGENT_TITLE = 'C등급 재고의 남은 유통기한을 다시 안내합니다.'
REFERENCE_TITLE = '관련 재고 참고 안내입니다. 요청하신 전체 조건의 충족 여부는 확인되지 않았습니다. 주문 수락, 조건 보장 또는 예약의 의미는 없습니다.'
INTENT = r'필요\s*(?:해요|합니다|해서|한데요)|(?:가격\s*)?문의\s*(?:드립니다|합니다|드려요|하고\s*싶어요)?|찾는\s*물건(?:은|이)?|찾고\s*있(?:어요|습니다)|\b(?:i\s+)?(?:needs?|looking\s+for|want\s+to\s+buy)\b|\b(?:request\s+a|please\s+send\s+a)\s+quote\b'
NEUTRAL = re.compile(r'(?:지금\s*)?재고(?:와|를)?\s*(?:견적을?\s*)?알려\s*주실\s*수\s*있나요|(?:가격|재고|견적)(?:을|를)?\s*알려\s*(?:주세요|주실\s*수\s*있나요)|(?:상품\s*)?후보(?:를)?\s*보고\s*싶어요|\b(?:please|thanks)\b', re.I)
PRIVATE = re.compile(r'https?\s*:|www\s*\.|\b[a-z0-9-]+\.(?:com|net|org|io|ai|co\.kr|kr)\b|@|카카오|카톡|텔레그램|전화|휴대폰|이메일|주소|개인\s*거래|직거래|계좌|메신저|(?:시|군|구)\s+[가-힣]+(?:로|길|동)\s*\d|알레르기|알러지|건강|환불|취소|영수증|증빙|후기|불만|구매했|샀어요|\b(?:contact|email|phone|address|dm|private|allergy|allergic|refund|cancel|proof|complaint|receipt|reviews?|previously|health|vegan|gluten)\b', re.I)
UNRESOLVED = re.compile(r'아닌|아니|제외|빼고|말고|없(?:이|는|어야|으면|습니다)|금지|불가|외에는|대체|반드시|무조건|필수|이상|이하|이내|미만|초과|최[대소]|정확히|수량|묶음|세트|대용량|중량|용량|등급|유통|소비기한|인증|배송|보증|\b(?:no|not|without|except|only|must|minimum|maximum|grade|pack|packs|certified|under|over)\b|[0-9₩$%<>≤≥=+×*/@]', re.I)
SOFT = re.compile(r'소포장|(?:산뜻한|깔끔한|고소한|담백한|부드러운|상큼한|은은한|진한|가벼운|무난한|달콤한)\s+(?:느낌|맛|쪽)(?:이면\s*좋겠(?:어요|습니다))?|(?:보기\s*좋은|무난한)\s*후보')
PUNCT = re.compile(r'[\s,.:!?()\[\]·~]+')
PACK_BOUNDARY = r'(?![A-Za-z가-힣])'
PACK_PARTICLES = r'(?:이|가|은|는|을|를|으로|로)?(?![A-Za-z가-힣0-9])'


def verified_file(pin):
    path, digest = pin
    source = Path(path).read_bytes()
    if sha256(source).hexdigest() != digest:
        raise ValueError('publisher digest mismatch')
    return source


def request_pack_pattern(v9):
    pattern = v9.PACK.pattern
    if not pattern.endswith(PACK_BOUNDARY):
        raise ValueError('unexpected packaging boundary')
    return re.compile(pattern[:-len(PACK_BOUNDARY)] + PACK_PARTICLES, v9.PACK.flags)


def classify(v9, post, offer, now):
    parent = v9.PARENT
    ts, author, raw = post.get('ts'), post.get('author'), post.get('text')
    if (not v9.public_root(post) or type(post.get('round')) is not int or post['round'] != 4
            or post.get('role') != 'buyer' or not isinstance(author, str) or not author.strip()
            or author.strip().casefold() == parent.shop.SHOP.casefold()
            or type(ts) not in (int, float) or not math.isfinite(ts)
            or not 0 <= now - ts <= min(21600, parent.THREAD_MAX_AGE)
            or not isinstance(raw, str) or not 1 <= len(raw) <= 2000
            or any(v9.unicodedata.category(c) in ('Cc', 'Cf', 'Cs') and c not in '\r\n\t' for c in raw)):
        return None
    text = v9.normalize(raw)
    if v9.EXCLUDE.search(text.replace('?', '')) or PRIVATE.search(text) or '\\' in text:
        return None
    intent = re.compile('(?:' + v9.ASK.pattern + '|' + INTENT + ')', re.I)
    inquiry = re.compile(r'(?:지금\s*)?(?:재고와\s*)?(?:견적|가격)(?:을|를)?\s*알려\s*(?:주세요|주실\s*수\s*있나요)', re.I)
    if not (intent.search(text) or inquiry.search(text)):
        return None
    text = re.sub(r'(이하|이내|까지)로(?=\s|[,.!?]|$)', r'\1', text)
    text = re.sub(r'([ABC]\s*(?:등급|급))(?:이|가|은|는|을|를)(?=\s|[,.!?]|$)', r'\1', text, flags=re.I)
    skus = {sku.casefold() for sku in v9.SKU.findall(text)}
    if skus and skus != {offer['sku'].casefold()}:
        return None
    grades = v9.GRADE.findall(text)
    positive = {grade.upper() for grade, excluded in grades if not excluded}
    negative = {grade.upper() for grade, excluded in grades if excluded}
    if (positive and positive != {offer['grade']}) or offer['grade'] in negative:
        return None
    caps = v9.CAP.findall(text)
    if len(caps) > 1 or (caps and offer['price'] > int(caps[0].replace(',', ''))):
        return None
    expiry = offer['expiry']
    if expiry is not None and (type(expiry) not in (int, float) or not math.isfinite(expiry) or expiry <= now):
        return None
    for count, unit in v9.LIFE.findall(text):
        if expiry is None or expiry - now < int(count) * (86400 if unit == '일' else 3600):
            return None
    if v9.CERT.search(text) and not offer['certificate']:
        return None
    rest = text
    for pattern in (v9.CERT, v9.LIFE, v9.CAP, v9.GRADE, NEUTRAL, inquiry, intent):
        rest = pattern.sub(' ', rest)
    if skus:
        sku = re.escape(offer['sku'])
        rest = re.sub(r'(?<![A-Za-z0-9])(?:only\s+' + sku + '|' + sku + r'(?:\s+only|\s*만))(?![가-힣A-Za-z0-9])', ' ', rest, flags=re.I)
    rest = v9.SKU.sub(' ', rest)
    product_seen = False
    for word in v9.product_words(offer):
        pattern = r'(?<![가-힣A-Za-z0-9])' + re.escape(word) + r'(?:입니다|으로|에서|에게|을|를|은|는|이|가|도|만|과|와|로)?(?![가-힣A-Za-z])'
        rest, hits = re.subn(pattern, ' ', rest, flags=re.I)
        product_seen = product_seen or bool(hits)
    if (not skus and not product_seen) or v9.MULTIPACK.search(rest):
        return None
    pack = request_pack_pattern(v9)
    matches = pack.findall(rest)
    if matches:
        requested = v9.pack_terms(' '.join(number + ' ' + unit for number, unit in matches))
        label = v9.normalize(offer['name'])
        available = v9.pack_terms(label)
        if (v9.MULTIPACK.search(label) or not requested <= available or len(matches) != len(requested)
                or any(sum(other == unit for _, other in available) != 1 for _, unit in requested)):
            return None
        rest = pack.sub(' ', rest)
    if UNRESOLVED.search(rest):
        return None
    rest = PUNCT.sub(' ', v9.FILLER.sub(' ', rest)).strip()
    if not rest:
        return 'strict'
    if not product_seen or UNRESOLVED.search(rest):
        return None
    if '소포장' in rest and not re.search(r'소포장\s*후보(?:를)?\s*보고\s*싶어요', text):
        return None
    chunks = re.split(r'\s+(?:그리고|또|및)\s+', rest)
    return 'reference' if len(chunks) <= 3 and all(SOFT.fullmatch(chunk) for chunk in chunks) else None


def epoch_identity(v9, sku, now):
    day = datetime.fromtimestamp(now, v9.KST).date().isoformat()
    return sha256(json.dumps(['urgent-c-v1', sku.casefold(), day], separators=(',', ':')).encode()).hexdigest()


def confirm_post(v9, market, record):
    post, content, created = record
    deadline = min(market.deadline, monotonic() + 2)
    try:
        rows = v9.checked_page(market, post - 1 if post > 1 else 0, 1 if post > 1 else 100, deadline)
    except v9.READ_ERRORS:
        return False
    return any(row['id'] == post and row.get('author') == v9.PARENT.shop.SHOP
               and row.get('role') == 'shop' and type(row.get('round')) is int and row['round'] == 4
               and v9.public_root(row) and row.get('text') == content and abs(row['ts'] - created) <= 150
               for row in rows)


def urgent_epoch(v9, db, market, offer, now, rates):
    expiry, sku = offer.get('expiry'), offer.get('sku')
    if (market is None or offer.get('grade') != 'C' or type(expiry) not in (int, float)
            or not math.isfinite(expiry) or not 1200 <= expiry - now <= 21600
            or not isinstance(sku, str) or not v9.SKU.fullmatch(sku)):
        return None
    shop = v9.PARENT.shop.SHOP
    base = v9.PARENT.offer_fingerprint(offer, None)
    epoch = epoch_identity(v9, sku, now)
    rows = db.execute('SELECT shop,round,thread,status,post,content,created,fingerprint FROM forum_publication WHERE sku=? COLLATE NOCASE', (sku,))
    evidence = []
    for owner, round_, thread, status, post, content, created, fingerprint in rows:
        if (owner != shop or type(round_) is not int or round_ != 4 or status not in ('posted', 'declined')
                or type(created) not in (int, float) or not math.isfinite(created) or not 0 < created <= now
                or not isinstance(fingerprint, str) or not fingerprint or fingerprint == epoch
                or (thread is not None and (type(thread) is not int or not 0 < thread <= 2**63 - 1))):
            return None
        if status == 'posted' and (type(post) is not int or not 0 < post <= 2**63 - 1 or not isinstance(content, str) or not content.strip()):
            return None
        if now - created < max(3600, rates[1]):
            return None
        if thread is None and fingerprint == base:
            if status != 'posted' or content.startswith(URGENT_TITLE):
                return None
            evidence.append((post, content, created))
    if not evidence:
        return None
    last, spotlight, day_count = db.execute('SELECT max(created), max(CASE WHEN thread IS NULL THEN created END), count(CASE WHEN created>? THEN 1 END) FROM forum_publication WHERE shop=? AND round=4', (now - 86400, shop)).fetchone()
    if (type(last) not in (int, float) or type(spotlight) not in (int, float)
            or not math.isfinite(last) or not math.isfinite(spotlight)
            or now - last < 330 or now - spotlight < max(600, rates[0]) or day_count >= 96):
        return None
    prior = max(evidence, key=lambda record: (record[2], record[0]))
    return epoch if confirm_post(v9, market, prior) else None


def factual_reference(v9, offer, _thread, shop_url, now):
    name = v9.PARENT.public_text(offer['name'])
    expiry = offer['expiry']
    facts = [f'{name} ({offer["sku"]}) · {offer["grade"]}등급 · 상품가 {offer["price"]:,} 크레딧']
    if expiry is not None:
        due = datetime.fromtimestamp(expiry, v9.KST).strftime('%Y-%m-%d %H:%M KST')
        facts.append(f'유통기한 {due} · 안내 시점 기준 약 {max(0, int((expiry - now) // 60))}분 남음')
    if offer['certificate']:
        facts.append('시장 인증서 있음')
    return REFERENCE_TITLE + '\n\n' + '\n'.join(facts) + f'\n\n재고와 조건은 상점에서 문의해 주세요. {shop_url}'


def same_current_offer(parent, db, market, offer, now):
    probe = parent.Market(market.kit)
    probe.deadline = min(probe.deadline, market.deadline)
    current = [item for item in parent.stock_offers(db, probe, now)
               if item.get('sku') == offer['sku'] and item.get('grade') == offer['grade']]
    return len(current) == 1 and current[0] == offer


def publisher_patch(source):
    calls = {'offer_fingerprint': 0, 'render_verified': 0}

    class Patch(ast.NodeTransformer):
        def visit_Call(self, node):
            self.generic_visit(node)
            if not isinstance(node.func, ast.Name) or node.func.id not in calls:
                return node
            name = node.func.id
            expected = ['offer', 'thread'] if name == 'offer_fingerprint' else ['db', 'market', 'offer', 'thread', 'now']
            if node.keywords or [arg.id if isinstance(arg, ast.Name) else None for arg in node.args] != expected:
                raise ValueError('unexpected publisher hook arguments')
            calls[name] += 1
            if name == 'offer_fingerprint':
                node.func.id = '_v11_publication_fingerprint'
                node.args = [ast.Name(id=key, ctx=ast.Load()) for key in ('db', 'market', 'offer', 'thread', 'now', 'rates')]
            else:
                node.func.id = '_v11_render_publication'
                node.args.append(ast.Name(id='rates', ctx=ast.Load()))
            return node

    tree = Patch().visit(ast.parse(source))
    if any(count != 1 for count in calls.values()):
        raise ValueError('unexpected publisher hook count')
    return ast.unparse(ast.fix_missing_locations(tree)) + '\n'


def install(v9):
    request_pack_pattern(v9)
    old_edit = v9.edit
    patched = 0

    def edit(source, old, new):
        nonlocal patched
        source = old_edit(source, old, new)
        if old.startswith('(content=? AND created>?)'):
            patched += 1
            return publisher_patch(source)
        return source

    v9.edit = edit
    try:
        parent = v9.load_parent()
    finally:
        v9.edit = old_edit
    if patched != 1:
        raise ValueError('missing publisher hook')
    v9.PARENT = parent
    original_market = parent.Market
    original_options = v9.available_options
    original_spotlight = v9.spotlight_eligible
    normal_render = v9.render_verified

    class FactualParent:
        def __getattr__(self, name):
            return getattr(parent, name)

        def render(self, offer, thread, shop_url, now):
            return factual_reference(v9, offer, thread, shop_url, now)

    reference_render = FunctionType(normal_render.__code__, dict(normal_render.__globals__, PARENT=FactualParent()))

    class Market(original_market):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            state = CURRENT.get()
            if state['market'] is None:
                state['market'] = self

    def options(db, market, now, rates):
        latest, offers, replies, allowed = original_options(db, market, now, rates)
        for option in replies:
            option['request'] = market._reply_evidence[option['thread']]['text']
        return latest, offers, replies, allowed

    def spotlight(db, offer, now, rates):
        return (original_spotlight(db, offer, now, rates)
                or urgent_epoch(v9, db, CURRENT.get()['market'], offer, now, rates) is not None)

    def choose(db, market, offer, thread, now, rates):
        if thread is not None or original_spotlight(db, offer, now, rates):
            result = ('normal', parent.offer_fingerprint(offer, thread))
        else:
            epoch = urgent_epoch(v9, db, market, offer, now, rates)
            if epoch is None:
                raise ValueError('urgent spotlight is unavailable')
            result = ('urgent', epoch)
        previous = CURRENT.get().setdefault('publication', result)
        if previous != result:
            raise ValueError('publication identity changed')
        return result

    def fingerprint(db, market, offer, thread, now, rates):
        return choose(db, market, offer, thread, now, rates)[1]

    def render(db, market, offer, thread, now, rates):
        mode, _ = choose(db, market, offer, thread, now, rates)
        if thread is None and mode == 'normal':
            return normal_render(db, market, offer, thread, now)
        check_time = int(parent.time.time())
        if not same_current_offer(parent, db, market, offer, check_time):
            raise ValueError('current offer changed')
        check_time = int(parent.time.time())
        if thread is not None:
            if not v9.fresh_match(market, thread, offer, check_time):
                raise ValueError('fresh request changed')
            kind = classify(v9, market._reply_evidence[thread], offer, int(parent.time.time()))
            if kind == 'strict':
                return normal_render(db, market, offer, thread, check_time)
            if kind == 'reference':
                return reference_render(db, market, offer, thread, check_time)
            raise ValueError('fresh request no longer matches')
        if choose(db, market, offer, thread, check_time, rates)[0] != 'urgent':
            raise ValueError('urgent spotlight changed')
        minutes = int((offer['expiry'] - check_time) // 60)
        return f'{URGENT_TITLE} 안내 시점 기준 약 {minutes}분 남았습니다.\n\n' + normal_render(db, market, offer, thread, check_time)

    parent.Market = Market
    v9.is_match = lambda post, offer, now: classify(v9, post, offer, now) is not None
    parent.available_options = v9.available_options = options
    parent.spotlight_eligible = v9.spotlight_eligible = spotlight
    parent._v11_publication_fingerprint = fingerprint
    parent._v11_render_publication = render
    return v9


def load_owner():
    source = verified_file(V10)
    module = ModuleType('_outseop_r4_forum_marketing_v10')
    module.__file__ = V10[0]
    exec(compile(source, module.__file__, 'exec'), module.__dict__)
    if str(module.V9_PATH).replace('\\', '/') != V9[0] or module.V9_HASH != V9[1]:
        raise ValueError('v9 lineage mismatch')
    original_loader = module.load_v9
    installed = None

    def hooked_loader():
        nonlocal installed
        if installed is None:
            verified_file(V9)
            installed = install(original_loader())
        return installed

    module.load_v9 = hooked_loader
    return module


def run(args, kit):
    global OWNER
    state = CURRENT.set({'market': None})
    try:
        with LOCK:
            if OWNER is None:
                OWNER = load_owner()
            return OWNER.run(args, kit)
    except Exception:
        return {'status': 'hold'}
    finally:
        CURRENT.reset(state)
