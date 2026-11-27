def fact_clause(a, n):
    text = a.get('text', '')
    phrase = a.get('product_phrase', '')
    catalogue = n.get('load_catalogue', lambda: {})()
    if not isinstance(text, str) or not isinstance(phrase, str) or not phrase:
        return None
    if not isinstance(catalogue, dict):
        return None

    # A product noun must be an actual catalogue key; this also prevents
    # partial or substring-based product matching.
    noun = None
    for k in catalogue:
        if isinstance(k, str) and k == phrase:
            noun = k
            break
    if noun is None:
        return None

    s = text.strip()
    if not s:
        return None

    # Reject material which is never part of a read-only public fact query.
    forbidden = ('정확한 제품', '정확히 그', '다른 상품', '대체', '대신', '없으면',
                 '아니', '말고', 'SKU', '개인정보', '알레르기', '브랜드', '보증',
                 '환불', '송금', '이체', '결제해', '구매해', '주문해', '예약해',
                 '수량', '몇 개', '킬로', '그램', '원 이상', '원 이하', '만원',
                 '등급 이상', '등급 이하', '개월 이상', '일 이상')
    for x in forbidden:
        if x in s:
            return None
    if any(ch.isdigit() for ch in s):
        return None

    requested = False
    # The document request is accepted only as a complete anchored suffix.
    doc = re.search(r'(?:^|[,.!? ]+)(결제[ ]?서)(?:[은는이가을를도만])?[ ]*(?:부탁(?:드려요|드립니다|해요)|주세요|요청(?:해요|드립니다))[.!?]*$', s)
    if doc:
        requested = True
        s = s[:doc.start()].rstrip(' ,.?!')

    # Remove only a complete, same-noun non-assenting visit introduction.
    visit = re.match(r'^' + re.escape(noun) + r'(?:을|를)?[ ]*(?:사러|보러|구경하러)[ ]*(?:가게에[ ]*)?(?:왔습니다|왔어요|왔어|들렀습니다|들렀어요|들렀어)[,. ]*', s)
    browse = re.match(r'^' + re.escape(noun) + r'(?:은|는|이|가)?[ ]*(?:구경|둘러보|살펴보)(?:러|려고)[ ]*(?:왔습니다|왔어요|왔어)[,. ]*', s)
    if visit:
        s = s[visit.end():].strip()
    elif browse:
        s = s[browse.end():].strip()

    if not s:
        return None

    # The remaining text must mention this exact noun with a Korean particle
    # boundary and at least one recognized public field.
    if not re.search(r'(?<![가-힣])' + re.escape(noun) + r'(?:은|는|이|가|을|를|의|도|만|에|에서|으로|로)?(?![가-힣])', s):
        return None
    fields = []
    field_patterns = (
        ('title', r'(?:상품명|상품 이름|제품명|제품 이름)'),
        ('grade', r'(?:등급|품질)'),
        ('price', r'(?:가격|판매가|판매 가격|표시 가격)'),
        ('shelf_life', r'(?:소비기한|유통기한)'),
        ('stock', r'(?:재고|재고가|살 수 있|구매 가능|판매 가능)')
    )
    for name, pat in field_patterns:
        if re.search(pat, s):
            fields.append(name)
    if not fields:
        return None

    # Keep grammar strict: only public-field wording, particles, polite
    # connectors and harmless modifiers may surround the recognized spans.
    clean = re.sub(r'(?<![가-힣])' + re.escape(noun) + r'(?:은|는|이|가|을|를|의|도|만|에|에서|으로|로)?(?![가-힣])', '', s)
    clean = re.sub(r'(?:상품명|상품 이름|제품명|제품 이름|등급|품질|가격|판매가|판매 가격|표시 가격|소비기한|유통기한|재고|재고가|살 수 있|구매 가능|판매 가능)', '', clean)
    clean = re.sub(r'[ ,·및과와/의는은이가을를도만에에서으로로정확한현재지금있는가능한확인해주시고알려주세요알려주시고알려줘요알려주세요부탁드려요해주세요요[ ]]', '', clean)
    if clean:
        return None

    order = ('title', 'grade', 'price', 'shelf_life', 'stock')
    selected = [x for x in order if x in fields]
    labels = {'title': '상품명', 'grade': '등급', 'price': '가격', 'shelf_life': '소비기한', 'stock': '재고'}
    canonical = noun + '의 ' + ', '.join(labels[x] for x in selected) + '을 알려주세요'
    return (canonical, requested)