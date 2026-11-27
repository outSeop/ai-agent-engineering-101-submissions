import hashlib,re
P='tools/semantic_candidates_v4/logic.py'
H='01e59f9b5e06b0402a669bfbd9c78e350c9cb32e9c65bfd111fdf5ac1a74b39c'
def unavailable(r): return {'status':'unavailable','reason':r}
def load():
    try:
        b=open(P,'rb').read(128*1024+1)
        if len(b)>128*1024 or hashlib.sha256(b).hexdigest()!=H:return None
        n={'__name__':'_pinned_v4'};exec(compile(b,P,'exec'),n);return n
    except Exception:return None
def rows(reply):
    z=[]
    for line in reply.splitlines():
        if '· SKU ' in line:
            m=re.search(r'\bSKU\s+(G[0-9a-f]{8})\b',line,re.I)
            if m:z.append((m.group(1).casefold(),line))
    return z
def repeated(text, phrase):
    import re
    s = str(text or '').strip()
    p = str(phrase or '').strip()
    if not s or not p:
        return False
    c = load()['load_catalogue']()
    prep_fact = c['PREP_FACT']
    prep_plain = c['PREP_PLAIN']
    fact_words = c['FACT']
    restricted = c.get('RESTRICTED', ())
    negation = c.get('NEGATION', ())
    exact = c.get('EXACT', ())
    proof = c.get('PROOF_OR_AUTHORITY', ())
    unknown_fact = c.get('UNKNOWN_FACT', ())
    neutral = c.get('NEUTRAL_SENTENCE', ())
    span = product_span(s)
    def words(x):
        return re.findall(r'[가-힣A-Za-z0-9]+', x.lower())
    def has_boundary(x, y):
        return re.search(r'(?<![가-힣A-Za-z0-9])' + re.escape(y) + r'(?![가-힣A-Za-z0-9])', x.lower()) is not None
    if not has_boundary(s, p):
        return False
    toks = words(s)
    ptoks = words(p)
    if not ptoks or any(t not in toks for t in ptoks):
        return False
    for group in (restricted, negation, exact, proof, unknown_fact):
        for item in group or ():
            item = str(item)
            if has_boundary(s, item):
                return False
    bad_action = ('주문', '구매', '결제할게', '결제합니다', '송금', '이체', '보증', '환불', '예약')
    bad_proof = ('증빙', '인증서', '근거', '출처', '보장', '보증서')
    bad_threshold = ('최소', '이상', '이하', '미만', '동안', '일간')
    for item in bad_action + bad_proof + bad_threshold:
        if has_boundary(s, item):
            if item in ('결제할게',) and ('나중에' in s or '검토' in s) and ('지금' not in s or '재고' in s):
                continue
            return False
    if '소비기한' in s and any(x in s for x in ('7일', '일 이상', '최소')):
        return False
    nouns = []
    for w in words(span or s):
        if w in fact_words or any(has_boundary(w, str(f)) for f in fact_words):
            nouns.append(w)
    if not nouns:
        return False
    for w in toks:
        if w in ('알려주세요', '알려', '확인', '조회', '보고', '있어요', '있나요', '싶어요', '할게요', '검토할게요', '및', '와', '과', '은', '는', '을', '를', '이', '가', '요', '지금', '나중에', '그때', '어떤', '상품', '재고', '가격', '소비기한'):
            continue
        if any(w == str(x).lower() for x in prep_fact or ()) or any(w == str(x).lower() for x in prep_plain or ()):
            continue
    return True
def run(a,kit):
    if type(a) is not dict:return unavailable('invalid_args')
    if set(a)=={'op','text','product_phrase','queries'} and a.get('op')=='semantic_candidates':
        n=load()
        if n is None:return unavailable('dependency_unavailable')
        r=n['run'](a,kit)
        if r.get('status')!='unavailable' or r.get('reason')!='unsupported_request':return r
        t=repeated(a['text'],a['product_phrase'])
        if t is None:return r
        b=dict(a);b['text']=t
        return n['run'](b,kit)
    if set(a)!={'op','text','groups'} or a.get('op')!='semantic_candidates':return unavailable('invalid_args')
    text=a['text'];groups=a['groups']
    if type(text) is not str or not 1<=len(text)<=1500 or type(groups) is not list or not 1<=len(groups)<=2:return unavailable('invalid_args')
    if any(type(g) is not dict or set(g)!={'product_phrase','queries'} or type(g['product_phrase']) is not str or type(g['queries']) is not list or not 1<=len(g['queries'])<=2 or any(type(q) is not str for q in g['queries']) for g in groups):return unavailable('invalid_args')
    n=load()
    if n is None:return unavailable('dependency_unavailable')
    ps=[g['product_phrase'] for g in groups]
    if len(groups)==1:return run({'op':'semantic_candidates','text':text,'product_phrase':ps[0],'queries':groups[0]['queries']},kit)
    if ps[0]==ps[1] or any(len(x)<1 or len(x)>48 for x in ps):return unavailable('unsupported_request')
    if any(re.search(r'브랜드|제조사|상표|brand|manufacturer',x,re.I) for x in (text+''.join(ps)+''.join(q for g in groups for q in g['queries']))):return unavailable('unsupported_request')
    pat=re.compile(r'(?<![\w-])'+re.escape(ps[0])+r'\s*(와|과)\s*'+re.escape(ps[1])+r'(?![\w-])');ms=list(pat.finditer(text))
    if len(ms)!=1:return unavailable('unsupported_request')
    m=ms[0];obs=until=None;bs=[]
    for i,g in enumerate(groups):
        r=n['run']({'op':'semantic_candidates','text':text[:m.start()]+ps[i]+text[m.end():],'product_phrase':ps[i],'queries':g['queries']},kit)
        if r.get('status')=='rendered':
            if obs is None:obs,until=r.get('observed_at'),r.get('valid_until')
            if (r.get('observed_at'),r.get('valid_until'))!=(obs,until):return unavailable('stale_snapshot')
            bs.append(rows(r.get('reply','')))
        elif r.get('reason') in ('no_match','selection_unavailable'):bs.append([])
        else:return unavailable('unsupported_request')
    seen=set();chosen=[]
    for i,b in enumerate(bs):
        x=next(((s,l) for s,l in b if s not in seen),None)
        if not x:return unavailable('no_match')
        chosen.append('요청 '+str(i+1)+' · '+x[1]);seen.add(x[0])
    out='\n'.join(['유사어로 찾은 참고 후보입니다. 정확한 상품 일치와 요청 조건 전체의 충족 여부는 확인되지 않았습니다. 표시 가격은 공개 상품가.']+chosen+['원하는 SKU로 구매 조건을 다시 문의해 주세요.'])
    return {'status':'rendered','reply':out,'observed_at':obs,'valid_until':until} if len(out)<=450 else unavailable('response_too_long')
