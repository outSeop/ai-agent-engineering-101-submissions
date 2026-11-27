def fact_fallback(a, n):
    if not isinstance(a, dict) or not isinstance(n, dict):
        return None
    text = a.get('text')
    phrase = a.get('product_phrase')
    queries = a.get('queries')
    if not isinstance(text, str) or not text.strip() or not isinstance(phrase, str) or not phrase.strip() or not isinstance(queries, (list, tuple)) or not queries:
        return None
    c = n['load_catalogue']()
    prep = c.get('PREP_FACT')
    if prep is None:
        return None
    t = text.strip()
    low = t.lower()
    forbidden = ('개인', '내 정보', '주문자', '주소', '전화번호', '연락처', '배송지', '회원', '비공개', '사적인', '말고', '제외', '아니', '없나', '없으면', '다른 상품', '대체품', '동일 상품', '같은 상품', '정확한 sku', 'sku', '수량', '개', 'kg', 'g', 'ml', '원 이상', '원 이하', '보다 비싸', '보다 싸', '등급 이상', '등급 이하', '유통기한', '까지', '최소', '알레르', '건강', '복용', '호환', '적합', '보증', '워런티', '브랜드', '성분', '환불', '송금', '이체', '결제하', '지불하', '구매하', '주문하', '예약하', '확정', '약속')
    if any(x in t or x in low for x in forbidden):
        return None
    if phrase not in t:
        return None
    doc = None
    for x in ('결제서류', '결제 문서', '결제문서'):
        p = t.rfind(x)
        if p >= 0:
            tail = t[p + len(x):].strip()
            if tail in ('알려주세요.', '알려주세요!', '알려주세요?', '알려 주세요.', '알려 주세요!', '알려 주세요?', '을 알려주세요.', '를 알려주세요.', '을 알려 주세요.', '를 알려 주세요.'):
                doc = t[:p].strip()
                break
    if doc is None:
        return None
    if not doc or not doc.endswith(phrase) and phrase not in doc:
        return None
    m = prep.search(doc)
    if m is None:
        return None
    clause = m.group(0) if hasattr(m, 'group') else ''
    if not clause or phrase not in clause:
        return None
    if any(x in clause for x in ('말고', '제외', '아니', '다른', '같은', '정확한', '수량', '원 이상', '원 이하', '유통기한', '알레르', '호환', '보증', '브랜드', '환불', '결제', '구매')):
        return None
    fields = []
    for q in queries:
        if not isinstance(q, str):
            continue
        q = q.strip()
        if q in ('상품명', '상품 이름', '제품명', '가격', '판매가', '등급', '재고', '수량'):
            if q not in fields:
                fields.append(q)
    if not fields:
        return None
    noun = '·'.join(fields)
    return (noun + ' 알려주세요', '관련 재고 참고 정보이며 원래 조건은 확인되지 않았습니다.')