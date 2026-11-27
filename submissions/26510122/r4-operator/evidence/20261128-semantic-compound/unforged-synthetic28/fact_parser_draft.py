def fact_clause(a, n):
    text = a.get('text', '')
    phrase = a.get('product_phrase', '')
    if not isinstance(text, str) or not isinstance(phrase, str) or not phrase:
        return None
    try:
        n.get('load_catalogue', lambda: {})()
    except Exception:
        return None
    s = text.strip()
    if not s or any(ch.isdigit() for ch in s):
        return None
    noun = r'(?<![가-힣])' + re.escape(phrase) + r'(?:[은는이가을를도만])?(?![가-힣])'
    if not re.search(noun, s):
        return None
    forbidden = ('다른 상품','대체','대신','없으면','아니','말고','SKU','개인정보','알레르기','브랜드','보증','환불','송금','이체','결제해','구매해','주문해','예약해','수량','몇 개','킬로','그램','원 이상','원 이하','만원','등급 이상','등급 이하','개월 이상','일 이상','정확히 그')
    if any(x in s for x in forbidden):
        return None
    requested = False
    dm=r'(?:결제[ ]*서류?|영수증|계산서)'
    particle=r'(?:이|가|은|는|을|를|도|만|의|에|에서|으로|로|와|과|께|랑|이나|라도)?'
    verb=r'(?:부탁드립니다|부탁드려요|부탁해요|부탁합니다|주시겠어요|주실래요|발행[ ]*주세요|발급[ ]*주세요|주세요)'
    rx=re.compile(r'(?P<suffix>'+dm+particle+r'[ ]*'+verb+r')[ ]*[.!！?？。]*[ ]*$')
    m=rx.search(s)
    if m:
        requested = True
        s = s[:m.start()].rstrip(' ,.?!')
    for pat in (r'(?:^|[,.!? ]+)(?:결제|구매|주문)(?:는|은|을|를)?[ ]*(?:나중에|후에|다음에)[ ]*(?:생각할게요|생각하겠습니다|결정할게요|결정하겠습니다|검토할게요|검토하겠습니다)[.!?]*$', r'(?:^|[,.!? ]+)(?:재고가[ ]*있으면|재고가[ ]*있을[ ]*때|재고가[ ]*있다면)[ ]*(?:그때[ ]*)?결제(?:를)?[ ]*(?:검토할게요|검토하겠습니다)[.!?]*$'):
        m = re.search(pat, s)
        if m:
            s = s[:m.start()].rstrip(' ,.?!')
    visit_patterns = (r'^(?:(?:저는|제가|사실|실은|혹시|그냥)[ ]*){0,2}'+noun+r'(?:은|는|이|가|을|를)?[ ]*(?:(?:(?:가게|매장|상점)(?:에|으로|로)?[ ]*)?)(?:사러|구매하러|구입하러|사고자|사기 위해)[ ]*(?:(?:가게|매장|상점)(?:에|으로|로)?[ ]*)?(?:왔습니다|왔어요|왔어|들렀습니다|들렀어요|들렀어|방문했습니다|방문했어요|방문했어)(?:[,.!?。！?]+[ ]*)', r'^(?:(?:저는|제가|사실|실은|혹시|그냥)[ ]*){0,2}'+noun+r'(?:은|는|이|가)?[ ]*(?:(?:구경|둘러보|살펴보|보)(?:러|려고)[ ]*(?:(?:가게|매장|상점)(?:에|으로|로)?[ ]*)?(?:왔습니다|왔어요|왔어|들렀습니다|들렀어요|들렀어|방문했습니다|방문했어요|방문했어)|알아보고[ ]*있어요)(?:[,.!?。！?]+[ ]*)')
    for pat in visit_patterns:
        m = re.match(pat, s)
        if m:
            s = s[m.end():].strip()
            break
    if not s or not re.search(noun, s):
        return None
    specs = [('title',r'(?:상품명|상품 이름|제품명|제품 이름)'),('grade',r'(?:등급|품질)'),('price',r'(?:가격|판매가|판매 가격|표시 가격)'),('shelf_life',r'(?:소비기한|유통기한)'),('stock',r'(?:재고|재고가|살 수 있|구매 가능|판매 가능)')]
    fields = [k for k,p in specs if re.search(p,s)]
    if not fields:
        return None
    c = n['load_catalogue']()
    rest = s
    approved = []
    for m0 in re.finditer(noun, rest):
        approved.append((m0.start(), m0.end()))
    fact_rx = c['PREP_FACT']
    for m0 in re.finditer(fact_rx, rest):
        approved.append((m0.start(), m0.end()))
    for m0 in re.finditer(r'정확한[ ]*(?=(?:상품명|상품 이름|제품명|제품 이름|등급|품질|가격|판매가|판매 가격|표시 가격|소비기한|유통기한|재고|재고가|살 수 있|구매 가능|판매 가능))', rest):
        approved.append((m0.start(), m0.end()))
    approved.sort()
    masked=[]; pos=0
    for a,b in approved:
        if a < pos: continue
        masked.append(rest[pos:a]); masked.append(' '*(b-a)); pos=b
    masked.append(rest[pos:])
    remainder=''.join(masked)
    plain=set(c['PREP_PLAIN'])|{'알려주시고'}
    for tok in re.findall(r'[가-힣A-Za-z]+', remainder):
        if tok not in plain:
            return None
    if re.search(r'[0-9]', remainder):
        return None
    labels={'title':'상품명','grade':'등급','price':'가격','shelf_life':'소비기한','stock':'재고'}
    chosen=[k for k in ('title','grade','price','shelf_life','stock') if k in fields]
    return (phrase+' '+', '.join(labels[k] for k in chosen)+'을 알려주세요', requested)