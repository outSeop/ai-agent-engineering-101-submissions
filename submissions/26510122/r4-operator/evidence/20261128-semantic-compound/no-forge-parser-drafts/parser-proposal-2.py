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
    noun = r'(?<![가-힣])' + re.escape(phrase) + r'(?![가-힣])'
    if not re.search(noun, s):
        return None
    forbidden = ('다른 상품','대체','대신','없으면','아니','말고','SKU','개인정보','알레르기','브랜드','보증','환불','송금','이체','결제해','구매해','주문해','예약해','수량','몇 개','킬로','그램','원 이상','원 이하','만원','등급 이상','등급 이하','개월 이상','일 이상','정확히 그')
    if any(x in s for x in forbidden):
        return None
    requested = False
    m = re.search(r'(?:^|[,.!? ]+)(결제[ ]?서)(?:[은는이가을를도만])?[ ]*(?:부탁(?:드려요|드립니다|해요)|주세요|요청(?:해요|드립니다))[.!?]*$', s)
    if m:
        requested = True
        s = s[:m.start()].rstrip(' ,.?!')
    m = re.search(r'(?:^|[,.!? ]+)(?:결제|구매|주문)(?:는|은|을|를)?[ ]*(?:나중에|후에|다음에)[ ]*(?:생각할게요|생각하겠습니다|결정할게요|결정하겠습니다|검토할게요|검토하겠습니다)[.!?]*$', s)
    if m:
        s = s[:m.start()].rstrip(' ,.?!')
    for pat in (r'^'+noun+r'(?:을|를)?[ ]*(?:사러|구매하러|보러|구경하러)[ ]*(?:가게에[ ]*)?(?:왔습니다|왔어요|왔어|들렀습니다|들렀어요|들렀어)[,. ]*', r'^'+noun+r'(?:은|는|이|가)?[ ]*(?:구경|둘러보|살펴보)(?:러|려고)[ ]*(?:왔습니다|왔어요|왔어)[,. ]*'):
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
    rest = re.sub(noun,'',s)
    for _,p in specs:
        rest = re.sub(p,'',rest)
    rest = re.sub(r'(?:정확한|현재|지금|있는|가능한|확인해|알려주세요|알려주시고|알려줘요|부탁드려요|부탁드립니다|해주세요|살|수|구매|판매|가능|을|를|은|는|이|가|의|도|만|에|에서|으로|로|및|과|와|그리고|[ ,·/!?.,])','',rest)
    if re.search(r'[가-힣A-Za-z0-9]',rest):
        return None
    labels={'title':'상품명','grade':'등급','price':'가격','shelf_life':'소비기한','stock':'재고'}
    chosen=[k for k in ('title','grade','price','shelf_life','stock') if k in fields]
    return (phrase+'의 '+', '.join(labels[k] for k in chosen)+'을 알려주세요', requested)