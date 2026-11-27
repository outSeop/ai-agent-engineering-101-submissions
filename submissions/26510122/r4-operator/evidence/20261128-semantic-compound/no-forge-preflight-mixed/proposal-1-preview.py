def preview(a,kit,n):
    c=n['load_catalogue']()
    s=a.get('text','')
    if not isinstance(s,str) or not s.strip():
        return None
    original=s
    fact_re=c.get('PREP_FACT')
    plain=c.get('PREP_PLAIN',frozenset())
    if not fact_re or not isinstance(plain,(set,frozenset)):
        return None
    products=[]
    for k in ('products','catalogue','catalog','items'):
        v=c.get(k)
        if isinstance(v,dict):
            products += [str(x) for x in v.keys()]
        elif isinstance(v,(list,tuple,set,frozenset)):
            products += [str(x) for x in v]
    products=[x for x in products if x]
    if not products:
        for k,v in c.items():
            if isinstance(v,dict) and k not in ('PREP_FACT','PREP_PLAIN'):
                products += [str(x) for x in v.keys()]
    products=sorted(set(products),key=len,reverse=True)
    if not products:
        return None
    bad=re.compile(r'(환불|반품|보증|워런티|인증|알레르기|브랜드|정확한[ ]*상품명|정확히|SKU|sku|비공개|private|재고번호|시리얼|최저|이상|이하|미만|초과|보다[ ]*많|보다[ ]*적|개|병|박스|원|[%％]|[0-9０-９])')
    if bad.search(s):
        return None
    product=None
    hits=[]
    for p in products:
        for m in re.finditer(re.escape(p)+r'(?:[은는이가을를의도만]|[ ]*상품)?',s):
            hits.append((m.start(),m.end(),p))
    if not hits:
        return None
    names=set(x[2] for x in hits)
    if len(names)!=1:
        return None
    product=next(iter(names))
    # Remove only a complete, explicitly future/document request suffix.
    doc=False
    dm=re.search(r'[ ]*(?:결제|지불)[ ]*(?:서|문서)?[은는이가을를]?[ ]*(?:발행|작성|준비|만들)[ ]*(?:해[ ]*주|해주세요|해[ ]*주세요|부탁)[ ]*(?:세요|합니다|해요)?[.!。]?$',s)
    if dm:
        doc=True
        s=s[:dm.start()]
    # A complete future-consideration clause is harmless and may be removed.
    fm=re.search(r'[ ]*(?:구매|결제|주문)[ ]*(?:할|하려)[ ]*(?:예정|생각|계획)[이은는]?[ ]*(?:있습니다|이에요|입니다|입니다만)?[.!。]?$',s)
    if fm:
        s=s[:fm.start()]
    # Remove one bounded visit-purpose sentence, without treating it as consent.
    vm=re.match(r'^\s*'+re.escape(product)+r'(?:[은는이가을를])?[ ]*(?:사러|찾으러|구매하러)[ ]*(?:방문|왔|가)[^.!?。!?]*[.!?。][ ]*',s)
    if vm:
        s=s[vm.end():]
    # Mask the affirmed product mentions, retaining only factual grammar around them.
    s=re.sub(re.escape(product)+r'(?:[은는이가을를의도만])?', ' ', s)
    s=re.sub(r'[.!?。]+',' ',s)
    s=re.sub(r'[ ]+',' ',s).strip()
    if not s:
        return None
    # Only whitelist catalogue fact words and ordinary polite factual/request grammar.
    words=[x for x in re.findall(r'[가-힣A-Za-z]+',s) if x]
    if not words:
        return None
    allowed=set(plain)|set(['재고','가격','판매','등급','상품명','유통기한','수량','있나요','있습니까','알려','주세요','보여','확인','가능','합니까','인가요','인가','입니다','이에요','있는','없나요','없습니까','및','과','와','도','은','는','이','가','을','를','의','에','서','만','좀','현재','판매중','판매중인','표시','제목','정보','어떤','무엇','요','부탁'])
    if any(x not in allowed and not re.fullmatch(fact_re,x) for x in words):
        return None
    fields=[]
    for x in words:
        if x in plain or re.fullmatch(fact_re,x):
            if x not in fields:
                fields.append(x)
    if not fields:
        return None
    canonical=product+' '+ ' '.join(fields)
    r=n['run'](dict(a,text=canonical),kit)
    if not isinstance(r,dict) or r.get('status')!='v4':
        return None
    if doc:
        r=dict(r)
        r['reply']=str(r.get('reply',''))+' 결제서는 발행하지 않았습니다.'
        r['payment_request']={'status':'not_issued','reason':'product_selection_required'}
    if len(str(r.get('reply','')))>450:
        return None
    return r