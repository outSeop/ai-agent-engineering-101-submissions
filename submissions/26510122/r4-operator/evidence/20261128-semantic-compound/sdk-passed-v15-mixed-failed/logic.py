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
    c=n['load_catalogue']()
    text=a.get('text','')
    if not isinstance(text,str) or not text.strip():
        return None
    original=text
    product=a.get('product_phrase')
    if not isinstance(product,str) or not product.strip():
        return None
    product=product.strip()
    if product not in text:
        return None
    low=text.replace(' ','').replace('\t','')
    p0=product.replace(' ','').replace('\t','')
    if not p0:
        return None
    # A document request is removable only when it is a complete suffix,
    # never merely because a document noun occurs after a known prefix.
    docs=('결제서','결제 서','결제서류','결제 서류','영수증','계산서')
    verbs=('부탁드립니다','부탁드려요','부탁해요','부탁합니다','주세요','주시겠어요','주실래요','발행해주세요','발급해주세요','발행해 주세요','발급해 주세요')
    suffix=None
    for d in docs:
        for v in verbs:
            for lead in ('','도 ','도','를 ','를','을 ','을','은 ','은','는 ','는','좀 ','좀 '):
                x=(lead+d+v).strip()
                if low.endswith(x.replace(' ','')):
                    suffix=x
                    break
            if suffix: break
        if suffix: break
    if suffix is None:
        return None
    # Ensure the suffix begins at a grammatical boundary and contains no
    # arbitrary material between the document noun and its polite predicate.
    cut=len(text)-len(suffix)
    if cut<0 or (cut and text[cut-1] not in ' \t,，.。!！?？;；'):
        return None
    fact=text[:cut].rstrip(' \t,，.。!！?？;；')
    if not fact:
        return None
    # Reject unsafe intents and unsupported commitments before normalization.
    bad=('송금','이체','환불','개인정보','전화번호','주소','알레르기','브랜드','보증','교환','최저','이상','미만','정확한','정확히','수량','개','확약','예약','보관','홀드','결제하겠습니다','구매하겠습니다')
    for w in bad:
        if w in fact:
            return None
    # The product must occur as an exact bounded noun span, allowing only a
    # Korean particle after it; unrelated substrings are never replaced.
    pos=fact.find(product)
    if pos<0:
        return None
    if fact.find(product,pos+len(product))>=0:
        return None
    before=fact[:pos]
    after=fact[pos+len(product):]
    particles=('이','가','은','는','을','를','도','만','의','에','에서','으로','로','와','과','께','랑','이나','라도')
    if after and not after.startswith(tuple(particles)) and after[:1] not in ' \t,，.。':
        return None
    # Strip only catalogue-recognized factual tokens and harmless grammar.
    pf=c.get('PREP_FACT')
    cleaned=fact
    if pf is not None:
        while True:
            z=pf.sub('',cleaned).strip()
            if z==cleaned: break
            cleaned=z
    plain=c.get('PREP_PLAIN',set())
    words=cleaned.split()
    kept=[]
    for w in words:
        q=w.strip(' ,，.。!！?？;；')
        if q in plain or q in ('지금','있으면','있다면','알려주시고','알려주세요','알려줘','부탁드립니다','부탁드려요','그리고','및','과','와'):
            continue
        kept.append(w)
    cleaned=' '.join(kept).strip()
    # Preserve the visit narrative and all unsupported/unknown preface text;
    # only accept the narrow visit predicates supplied by the catalogue.
    visit=('보러 왔','보러왔','살펴보려고 방문','살펴보러 방문','구경하러 왔','알아보러 왔','관심이 있어 방문')
    if not any(v in fact for v in visit):
        return None
    verified_fact_text=fact
    keys={k:a[k] for k in ('op','text','product_phrase','queries') if k in a}
    keys['text']=verified_fact_text
    r=n['run'](keys,kit)
    if not isinstance(r,dict):
        return None
    out={k:r[k] for k in ('reply','status','observed_at','valid_until') if k in r}
    if 'reply' not in out:
        return r
    if r.get('status')=='hold':
        msg=out.get('reply','')
        tail='결제서는 발행하지 않았습니다.'
        if tail not in msg:
            msg=(msg+' '+tail).strip()
        out['reply']=msg[:450]
        out['payment_request']={'status':'not_issued','reason':'product_selection_required'}
    return out
