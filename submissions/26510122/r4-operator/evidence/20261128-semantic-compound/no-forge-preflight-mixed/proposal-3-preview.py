def preview(a,kit,n):
    c=n['load_catalogue']()
    t=a.get('text')
    p=a.get('product_phrase')
    q=a.get('queries') or []
    if not isinstance(t,str) or not isinstance(p,str) or not p or not isinstance(q,list): return None
    fact=c.get('PREP_FACT')
    plain=c.get('PREP_PLAIN',set())
    if fact is None: return None
    def clean(s):
        x=fact.sub('',s)
        for w in plain: x=x.replace(w,'')
        return x
    if clean(t).strip(' .,!?。！？\t\n') not in ('','알려주세요','부탁해요'): return None
    if t.count(p)!=1: return None
    if any(x in t for x in ('정확한 상품명','등급','가격','소비기한','결제서')) and not p in t: return None
    final=bool(__import__('re').fullmatch(r'[ ]*결제[ ]*서[ ]*(를|도|요청)?[ ]*(부탁드립니다|부탁해요|해주세요|요청합니다)[ ]*[.!?。！？]?',t))
    intro=bool(__import__('re').search(r'[ ]*(사러|구매하러|보러|찾으러)[ ]*가게에[ ]*왔습니다[.!?。！？]?|[ ]*(둘러보|구경하)러[ ]*왔습니다[.!?。！？]?',t))
    if not (final or intro or any(w in t for w in ('살 수 있는','구매할 수 있는','현재 구매 가능'))): return None
    if any(w in t for w in ('알레르기','보증','환불','송금','이체','브랜드','개인','번호','수량','최소','이상','이하','안 ','없')): return None
    labels=[x for x in ('정확한 상품명','등급','가격','소비기한') if x in t]
    if not labels: return None
    r=p+'의 '+', '.join(labels)+'을 알려주세요.'
    out={'rendered':r,'reply':r,'observed_at':n.get('observed_at'),'valid_until':n.get('valid_until')}
    if final or '결제서' in t:
        z=r+' 결제서는 발행하지 않았습니다.'
        if len(z)<=450:
            out['rendered']=z; out['reply']=z; out['payment_request']={'status':'not_issued','reason':'product_selection_required'}
    return out