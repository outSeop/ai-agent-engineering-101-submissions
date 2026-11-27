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
def repeated(text,phrase):
    if not isinstance(text,str) or not isinstance(phrase,str): return None
    if len(text)>1500 or not 1<=len(phrase)<=48:return None
    p=re.escape(phrase)
    # Only a later, complete, single-clause affirmative stock/fact question.
    pat=re.compile(r'(?<![\w-])\s+'+p+r'(?:은|는|이|가)?\s*어떤\s+상품이\s+있(?:나요|어요|을까요)\?')
    ms=list(pat.finditer(text))
    if len(ms)!=1:return None
    m=ms[0]
    if m.start()==0 or text[m.start()-1] not in '.!?':return None
    prior=text[:m.start()-1]
    if len(re.findall(r'(?<![.!?])\s*'+p+r'(?:은|는|이|가)?',prior))<1:return None
    return text[:m.start()]+text[m.end():]
def run(a,kit):
    if type(a) is not dict:return unavailable('invalid_args')
    if set(a)=={'op','text','product_phrase','queries'} and a.get('op')=='semantic_candidates':
        n=load()
        if n is None:return unavailable('dependency_unavailable')
        r=n['run'](a,kit)
        if r.get('status')!='unavailable' or r.get('reason')!='unsupported_request':return r
    def _public_checkout_hold():
        op, text, product_phrase, queries = a['op'], a['text'], a['product_phrase'], a['queries']
        if not isinstance(text, str) or not isinstance(product_phrase, str) or not product_phrase.strip():
            return None
        s = text.strip()
        if not (('결제서' in s) or ('결제 서' in s)):
            return None
        if not any(x in s for x in ('발행', '발급', '보내', '요청', '주세요', '부탁')):
            return None
        forbidden = ('구매', '구입', '사줘', '주문', '송금', '이체', '결제해', '결제하', '실제', '증빙', '증명', '알레르기', '건강', '보증', '브랜드', '수량', '개수', '이상', '이하', '까지', '이내', '후', '전')
        if any(x in s for x in forbidden):
            return None
        noun = product_phrase.strip()
        if s.count(noun) < 1:
            return None
        fact = s
        for mark in ('결제서', '결제 서'):
            if mark in fact:
                fact = fact.split(mark, 1)[0].strip(' ,，.。;:')
                break
        if not fact or fact.count(noun) != 1:
            return None
        if any(c in fact for c in ('?', '？', '!', '！', '\n')):
            return None
        allowed_connectors = ('의', '은', '는', '이', '가', '을', '를', '에', '로', '만', '및', '이고', '이며', '이고', '이며', '있', '없')
        units = ('개', '병', '봉', '상자', '팩', '포', 'kg', 'g', 'ml', 'L')
        words = fact.split()
        if not words or words[0] != noun:
            return None
        seen = {'stock': 0, 'price': 0, 'grade': 0, 'expiry': 0}
        for w in words[1:]:
            if w in ('재고', '가격', '판매가', '등급', '유통기한', '소비기한') or w.rstrip('은는이가을를') in ('재고', '가격', '판매가', '등급', '유통기한', '소비기한'):
                continue
            if any(w.endswith(u) and w[:-len(u)].isdigit() for u in units):
                seen['stock'] += 1
                continue
            if w.endswith(('원', '원입니다', '원이에요')) and w[:-1].rstrip('입니다이에요').isdigit():
                seen['price'] += 1
                continue
            if w.rstrip('은는이가을를') in ('A', 'B', 'C', '특', '상', '중', '하'):
                seen['grade'] += 1
                continue
            if any(ch.isdigit() for ch in w) and any(x in w for x in ('년', '월', '일', '까지')):
                seen['expiry'] += 1
                continue
            if w in allowed_connectors or w.endswith(allowed_connectors):
                continue
            return None
        if sum(seen.values()) == 0 or any(v > 1 for v in seen.values()):
            return None
        target = dict(a)
        target['text'] = fact
        result = n['run']({'op': op, 'text': target['text'], 'product_phrase': product_phrase, 'queries': queries})
        if not isinstance(result, dict) or not result.get('status'):
            return None
        rendered = result.get('text', result.get('message'))
        if not isinstance(rendered, str) or not rendered.strip():
            return None
        result = dict(result)
        result['text'] = rendered.rstrip() + '\n결제서는 발행하지 않았습니다.'
        result['payment_request'] = {'status': 'not_issued', 'reason': 'product_selection_required'}
        return result

    _held = _public_checkout_hold()
    if _held is not None:
        return _held
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
