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
        def _fact_intent(text,phrase):
            if not isinstance(text,str) or not isinstance(phrase,str) or not phrase:
                return None
            s=' '.join(text.split())
            if not s or phrase not in s:
                return None
            particles=('이','가','은','는','을','를','의','에','에서','으로','로','와','과','도','만','까지','부터','보다','처럼','요')
            def boundary(i):
                j=i+len(phrase)
                if i and not (s[i-1].isspace() or s[i-1] in '.,?!:;()[]{}'):
                    return False
                if j<len(s) and not (s[j].isspace() or s[j] in '.,?!:;()[]{}' or any(s.startswith(x,j) for x in particles)):
                    return False
                return True
            if not any(boundary(i) for i in range(len(s)) if s.startswith(phrase,i)):
                return None
            bad=('최대','이하','이상','수량','개수','최저','최소','정확한','sku','SKU','비공개','보증','알레르기','브랜드','환불','송금','이체','구매','결제해','사줘','주문해','아니','없나요','없는')
            if any(x in s for x in bad):
                return None
            info=('재고','있나요','있습니까','판매가','가격','얼마','등급','등급이','유통기한','소비기한','언제까지')
            doc=('결제서','결제 서','영수증','거래명세서','세금계산서','발행해','발급해','문서')
            if not any(x in s for x in info+doc):
                return None
            if any(x in s for x in doc) and not any(x in s for x in ('요청','부탁','주세요','주시겠','발행','발급')):
                return None
            return {'subject':phrase,'text':s,'document':any(x in s for x in doc)}

        _fi=_fact_intent(a.get('text',''),a.get('product_phrase',''))
        if _fi is not None:
            b=dict(a)
            b['subject']=_fi['subject']
            b['text']=_fi['text']
            b['verified_public_facts']=_fi['text']
            z=n['run'](b,kit)
            if _fi['document'] and isinstance(z,dict):
                z=dict(z)
                z['payment_request']={'status':'not_issued','reason':'product_selection_required'}
                z['reply']=(z.get('reply','')+' 결제서는 발행하지 않았습니다.')[:450]
            return z
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
