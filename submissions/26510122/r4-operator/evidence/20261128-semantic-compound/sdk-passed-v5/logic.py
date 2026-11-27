import hashlib,re,time

P='tools/semantic_candidates_v4/logic.py'
H='01e59f9b5e06b0402a669bfbd9c78e350c9cb32e9c65bfd111fdf5ac1a74b39c'

def unavailable(r): return {'status':'unavailable','reason':r}

def load():
    try:
        b=open(P,'rb').read(128*1024+1)
        if len(b)>128*1024 or hashlib.sha256(b).hexdigest()!=H:return None
        n={'__name__':'_pinned_v4'};exec(compile(b,P,'exec'),n);return n
    except Exception:return None

def run(a,kit):
    if type(a) is not dict:return unavailable('invalid_args')
    # Preserve the published v4 route byte-for-byte at the argument boundary.
    if set(a)=={'op','text','product_phrase','queries'} and a.get('op')=='semantic_candidates':
        n=load()
        if n is None:return unavailable('dependency_unavailable')
        return n['run'](a,kit)
    if set(a)!={'op','text','groups'} or a.get('op')!='semantic_candidates':return unavailable('invalid_args')
    text=a['text']; groups=a['groups']
    if type(text) is not str or not 1<=len(text)<=1500 or type(groups) is not list or not 1<=len(groups)<=2:return unavailable('invalid_args')
    if any(type(g) is not dict or set(g)!={'product_phrase','queries'} or type(g['product_phrase']) is not str or type(g['queries']) is not list or not 1<=len(g['queries'])<=2 or any(type(q) is not str for q in g['queries']) for g in groups):return unavailable('invalid_args')
    n=load()
    if n is None:return unavailable('dependency_unavailable')
    ps=[g['product_phrase'] for g in groups]
    if len(groups)==1:
        return n['run']({'op':'semantic_candidates','text':text,'product_phrase':ps[0],'queries':groups[0]['queries']},kit)
    if ps[0]==ps[1] or any(len(x)<1 or len(x)>48 for x in ps):return unavailable('unsupported_request')
    # Only the anchored Korean A와/과 B construction is admitted.
    pat=re.compile(r'(?<![\w-])'+re.escape(ps[0])+r'\s*(와|과)\s*'+re.escape(ps[1])+r'(?![\w-])')
    ms=list(pat.finditer(text))
    if len(ms)!=1:return unavailable('unsupported_request')
    m=ms[0]; conj=m.group(1)
    if (conj=='와' and ps[0][-1] not in 'aeiouAEIOU') or (conj=='과' and ps[0][-1] in 'aeiouAEIOU'): pass
    out=[]; seen=set(); observed=None; until=None
    for i,g in enumerate(groups):
        phrase=ps[i]
        projected=text[:m.start()]+phrase+text[m.end():]
        r=n['run']({'op':'semantic_candidates','text':projected,'product_phrase':phrase,'queries':g['queries']},kit)
        if r.get('status') not in ('rendered','unavailable') or (r.get('status')=='unavailable' and r.get('reason') not in ('no_match','selection_unavailable')):return unavailable('unsupported_request')
        if r.get('status')=='rendered':
            observed=r.get('observed_at') if observed is None else observed
            until=r.get('valid_until') if until is None else until
            if r.get('observed_at')!=observed or r.get('valid_until')!=until:return unavailable('stale_snapshot')
            for line in r.get('reply','').splitlines():
                if '· SKU ' in line:
                    sku=re.search(r'\bSKU\s+(G[0-9a-f]{8})\b',line,re.I)
                    if sku and sku.group(1).casefold() not in seen:out.append(('A' if i==0 else 'B')+' · '+line);seen.add(sku.group(1).casefold())
    if not out:return unavailable('no_match')
    lines=['유사어로 찾은 참고 후보입니다. 정확한 상품 일치와 요청 조건 전체의 충족 여부는 확인되지 않았습니다. 표시 가격은 공개 상품가.']+out[:3]+['원하는 SKU로 구매 조건을 다시 문의해 주세요.']
    reply='\n'.join(lines)
    return {'status':'rendered','reply':reply[:450],'observed_at':observed,'valid_until':until}
