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
    if len(text)>1500 or not 1<=len(phrase)<=48: return None
    v4=load()
    cat=getattr(v4,'load_catalogue',lambda:None)()
    p=re.escape(phrase)
    if not re.fullmatch(r'[가-힣A-Za-z0-9][가-힣A-Za-z0-9 _-]{0,47}',phrase): return None
    if re.search(r'(?:결제|구매|주문|체크아웃|송금|환불|권한|대리|sku|SKU|정확한|알레르기|알러지|브랜드|보증|워런티|모르|없나요|아닌|말고|최소|이상|이하|까지)',text,re.I): return None
    mentions=list(re.finditer(r'(?<![가-힣A-Za-z0-9_-])'+p+r'(?:은|는|이|가|을|를|의|도|만)?(?![가-힣A-Za-z0-9_-])',text))
    if len(mentions)!=2: return None
    facts=re.findall(r'(?:재고|수량|가격|판매가|금액|등급|품질|소비기한|유통기한|기한)',text)
    if not facts or len(set(facts))!=len(facts):
        # Repeated fact wording is harmless, but a one-word product is still bounded.
        if not re.search(r'(?:재고|가격|등급|소비기한|유통기한)',text): return None
    if re.search(r'(?:남은|잔여|최소).{0,12}(?:일|개월|년|주)',text): return None
    clauses=[x.strip() for x in re.split(r'(?<=[.!?])\\s+',text) if x.strip()]
    if not clauses or len(clauses)>4: return None
    fact_ok=re.search(r'(?:재고|수량|가격|판매가|등급|품질|소비기한|유통기한).{0,80}(?:알려|궁금|확인|있나요|인가요|어떤|얼마)',text)
    if not fact_ok: return None
    for c in clauses:
        if not re.search(p,c) and not re.search(r'(?:알아보|살펴보|검토|고려|나중|때|경우)',c): return None
        if re.search(r'(?:결제|구매|주문|체크아웃|송금|환불|sku|SKU|정확한|알레르기|브랜드|보증|최소|이상|이하)',c,re.I): return None
    # Require the pinned validators to accept the complete original request;
    # never search from projected/model-derived fragments.
    def accepted(ns,s):
        for n in ('validate_readonly','validate','check','parse'):
            f=getattr(ns,n,None)
            if callable(f):
                try:
                    r=f(s)
                    if r is not None and r is not False: return True
                except Exception: pass
        return False
    if not accepted(v4,text) and not accepted(cat,text): return None
    # Remove only a later exact redundant noun span plus its harmless introduction.
    m=mentions[1]
    if m.start()==0: return None
    left=text[:m.start()]
    if not re.search(r'[.!?]\\s*$',left): return None
    tail=text[m.end():]
    if not re.fullmatch(r'(?:은|는|이|가)?\\s*(?:어떤\\s+상품이\\s+있(?:나요|어요|을까요)|재고와?\\s+가격(?:과|및)?)?\\s*[.!?]?',tail): return None
    return text[:m.start()]+tail
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
