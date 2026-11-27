def preview(a,kit,n):
    c=n['load_catalogue']()
    text=a.get('text')
    if not isinstance(text,str) or not text.strip(): return None
    fact=c.get('PREP_FACT'); plain=c.get('PREP_PLAIN')
    if fact is None or not isinstance(plain,(set,frozenset)): return None
    src=text.strip()
    forbidden=re.compile(r'(?:환불|반품|보증|워런티|인증|알레르기|브랜드|정확|정품|비공개|private|SKU|sku|시리얼|번호|[0-9０-９]|[%％]|원|개|병|박스|이상|이하|미만|초과|보다[ ]*많|보다[ ]*적)')
    if forbidden.search(src): return None
    vals=[]
    for key in ('products','items','catalogue','catalog'):
        x=c.get(key)
        if isinstance(x,dict): vals.extend(str(k) for k in x)
        elif isinstance(x,(list,tuple,set,frozenset)):
            for z in x:
                if isinstance(z,str): vals.append(z)
                elif isinstance(z,dict):
                    for k in ('name','title','product','sku'):
                        if isinstance(z.get(k),str): vals.append(z[k]); break
    vals=sorted(set(x for x in vals if x),key=len,reverse=True)
    if not vals: return None
    found=[]
    for p in vals:
        for m in re.finditer(re.escape(p)+r'(?:[은는이가을를의도만])?',src): found.append((m,p))
    if not found or len(set(p for m,p in found))!=1: return None
    product=found[0][1]
    rest=src
    doc=False
    m=re.search(r'[ ]*(?:결제|지불)[ ]*(?:서|문서)?[은는이가을를]?[ ]*(?:발행|작성|준비|만들)[ ]*(?:해[ ]*주세요|해주세요|해[ ]*주|부탁드려요|부탁)[.!。]?$',rest)
    if m: rest=rest[:m.start()]; doc=True
    m=re.search(r'[ ]*(?:구매|결제|주문)[ ]*(?:할|하려)[ ]*(?:예정|생각|계획)[이은는]?[ ]*(?:있습니다|입니다|이에요|있어요)[.!。]?$',rest)
    if m: rest=rest[:m.start()]
    m=re.match(r'^'+re.escape(product)+r'(?:[은는이가을를])?[ ]*(?:사러|찾으러|구매하러)[ ]*(?:방문|왔|갑)[^.!?。]*[.!?。][ ]*',rest)
    if m: rest=rest[m.end():]
    rest=re.sub(re.escape(product)+r'(?:[은는이가을를의도만])?',' ',rest)
    rest=re.sub(r'[.!?。]',' ',rest)
    rest=re.sub(r'[ ]+',' ',rest).strip()
    if not rest: return None
    tokens=re.findall(r'[가-힣A-Za-z]+',rest)
    grammar=set(plain)|{'재고','가격','판매','판매중','등급','상품명','제목','유통기한','수량','정보','공개','현재','확인','알려','보여','주세요','부탁','가능','있나요','있습니까','없나요','없습니까','인가요','인가','인가요','어떤','무엇','및','과','와','도','은','는','이','가','을','를','의','에','서','만','있는','있습니다','입니다','이에요','요'}
    if any(t not in grammar and re.fullmatch(fact,t) is None for t in tokens): return None
    fields=[]
    for t in tokens:
        if t in plain or re.fullmatch(fact,t):
            if t not in fields: fields.append(t)
    if not fields: return None
    out=n['run'](dict(a,text=product+' '+' '.join(fields)),kit)
    if not isinstance(out,dict) or out.get('status')!='v4' or len(str(out.get('reply','')))>450: return None
    if doc:
        out=dict(out); out['reply']=str(out.get('reply',''))+' 결제서는 발행하지 않았습니다.'; out['payment_request']={'status':'not_issued','reason':'product_selection_required'}
    return out