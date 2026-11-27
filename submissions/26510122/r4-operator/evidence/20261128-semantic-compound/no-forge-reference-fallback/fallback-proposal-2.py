def fact_fallback(a,n):
    if not isinstance(a,str):
        return None
    s=a.strip()
    if not s:
        return None
    def hit(k,x):
        r=n.get(k)
        return bool(r and r.search(x))
    for k in ('SKU','EXACT','NEGATION','UNVERIFIED','PROOF_OR_AUTHORITY'):
        if hit(k,s):
            return None
    for k in ('PRIVATE','REFUND','TRANSFER','ORDER','BRAND','WARRANTY','ALLERGY','EXACT_PRODUCT','NO_ALTERNATIVES','UNKNOWN_ATTRIBUTE','NUMBER','GRADE','PRICE','QTY','MINLIFE'):
        if hit(k,s):
            return None
    suffix=n.get('PAYMENT_SUFFIX')
    if suffix and suffix.search(s):
        s=suffix.sub('',s,count=1).strip()
    else:
        p=s.rfind('.')
        if p>=0 and p==len(s)-1:
            lead=s[:p].strip()
            rest=''
        else:
            lead=''
            rest=s
        if lead:
            if len(lead)>n.get('LEADING_MAX',80) or hit('HARD',lead) or hit('RISK',lead) or not hit('SIMPLE_KO',lead):
                return None
            s=rest.strip()
    if not s:
        return None
    if hit('PRIVATE',s) or hit('REFUND',s) or hit('TRANSFER',s) or hit('ORDER',s):
        return None
    prep=n.get('PREP_FACT')
    if prep is None or not prep.search(s):
        return None
    boundary=n.get('NOUN_PARTICLE')
    if boundary is None or not boundary.search(s):
        return None
    plain=n.get('APPROVED_PLAIN')
    if plain is None or not plain.fullmatch(s):
        return None
    buy=n.get('BUYABILITY_MOD')
    public=n.get('PUBLIC_FIELD_MOD')
    stock=n.get('STOCK_CONDITION')
    if buy and buy.search(s) and not n.get('BUYABILITY_ALLOWED',buy).search(s):
        return None
    if public and public.search(s) and n.get('PUBLIC_FIELD_ALLOWED') and not n['PUBLIC_FIELD_ALLOWED'].search(s):
        return None
    if stock and stock.search(s) and n.get('STOCK_ALLOWED') and not n['STOCK_ALLOWED'].search(s):
        return None
    ending=n.get('POLITE_INFO_END')
    if ending and not ending.search(s):
        return None
    s=' '.join(s.split())
    s=n.get('BARE_PHRASE',lambda x:x).sub('',s).strip() if hasattr(n.get('BARE_PHRASE'), 'sub') else s
    labels=[]
    for k in ('PUBLIC_FIELD_LABELS','STOCK_LABELS'):
        v=n.get(k,())
        for x in v:
            if x.search(s) if hasattr(x,'search') else x in s:
                labels.append(x.pattern if hasattr(x,'pattern') else x)
    canonical=(s if s else ' '.join(labels))
    if not canonical:
        return None
    return (canonical,'관련 재고 참고 정보이며 원래 조건은 확인되지 않았습니다.')