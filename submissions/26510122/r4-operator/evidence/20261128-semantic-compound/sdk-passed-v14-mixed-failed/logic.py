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
        previewed=preview(a,kit,n)
        if previewed is not None:return previewed
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

def preview(a,kit,n):
    c=n.get('load_catalogue',lambda: {})() or {}
    fact=c.get('PREP_FACT')
    plain=c.get('PREP_PLAIN',set()) or set()
    if fact is None:
        return None
    text=a.get('text','')
    product=a.get('product_phrase','')
    if not isinstance(text,str) or not isinstance(product,str) or not product.strip():
        return None
    p=product.strip()
    hold=False
    rest=text
    for base in ('결제서','결제 서'):
        i=rest.find(base)
        while i>=0:
            tail=rest[i+len(base):]
            if tail.startswith(('를','을','는','은','가','이','에','도')):
                tail=tail[1:]
            if tail.startswith((' 발행',' 발급',' 보내',' 보내주',' 주세요',' 주실래',' 부탁',' 요청')) or tail.startswith(('발행','발급','보내','보내주','주세요','주실래','부탁','요청')):
                j=len(rest)-len(tail)
                k=j
                while k<len(rest) and rest[k] not in '.!?。！？,，;；\n':
                    k+=1
                rest=rest[:i]+rest[k:]
                hold=True
                i=rest.find(base)
            else:
                i=rest.find(base,i+len(base))
    rest=' '.join(rest.split())
    if not rest:
        return None
    if p not in rest:
        return None
    clauses=[]
    for x in rest.replace('。','.').replace('！','!').replace('？','?').replace('，',',').split(','):
        for y in x.replace('!','.').replace('?','.').split('.'):
            y=y.strip()
            if y:
                clauses.append(y)
    if not clauses:
        return None
    for q in clauses:
        ok=False
        try:
            ok=bool(fact.fullmatch(q))
        except Exception:
            try:
                ok=bool(fact.match(q)) and fact.match(q).group(0)==q
            except Exception:
                return None
        if not ok:
            words=q.split()
            if not words or not all(w in plain or w==p for w in words):
                return None
        if any(z in q for z in ('브랜드','보증','알레르','SKU','정확','환불','결제','송금','이체','청구','영수증','증빙','구매','주문','수량','가격 조건','유통기한 조건','만료','없','아니','않')):
            return None
    verified_fact_text=' '.join(clauses)
    response=n['run'](dict(a,text=verified_fact_text),kit)
    if not isinstance(response,dict) or response.get('status') not in ('rendered',None):
        return None
    reply=response.get('reply')
    observed_at=response.get('observed_at')
    valid_until=response.get('valid_until')
    if not isinstance(reply,str) or observed_at is None or valid_until is None:
        return None
    out={'status':'rendered','reply':reply,'observed_at':observed_at,'valid_until':valid_until}
    if hold:
        suffix='결제서는 발행하지 않았습니다.'
        if len(reply)+len(suffix)>450:
            return None
        out['payment_request']={'status':'not_issued','reason':'product_selection_required'}
        out['reply']=reply+suffix
    return out
