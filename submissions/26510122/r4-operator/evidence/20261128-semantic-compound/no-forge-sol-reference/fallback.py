def fact_fallback(a, n):
    text = a.get('text')
    noun = a.get('product_phrase')
    if not isinstance(text, str) or not isinstance(noun, str) or not noun:
        return None
    if any(not ('가' <= ch <= '힣') for ch in noun):
        return None

    sentence_marks = '.!?。！？'
    separators = ' ,·、/'
    whole = text.rstrip()
    if not whole or whole[-1] not in sentence_marks:
        return None
    body = whole[:-1]
    verb = next((v for v in ('부탁드립니다', '부탁해요', '부탁합니다', '주세요')
                 if body.endswith(' ' + v)), None)
    if verb is None:
        return None
    head = body[:-len(verb)].rstrip(' ')
    doc_start = -1
    for label in ('결제 서류', '결제서류', '결제 서', '결제서'):
        for particle in ('', '을', '를', '도', '은', '는'):
            form = label + particle
            start = len(head) - len(form)
            if start > 0 and head.endswith(form) and head[start - 1] in separators + sentence_marks:
                doc_start = start
                break
        if doc_start >= 0:
            break
    if doc_start < 0:
        return None

    original = text[:doc_start] + text[len(whole):]
    split = next((i for i, ch in enumerate(original) if ch in sentence_marks), -1)
    if split < 0 or original[split] in '?？':
        return None
    lead = original[:split].strip(' ')
    if not 0 < len(lead) <= 28 or any(ch != ' ' and not ('가' <= ch <= '힣') for ch in lead):
        return None
    if any(term in lead for term in ('알려', '말씀해', '보여', '주세요', '주십시오', '주실', '부탁', '요청', '해줘', '궁금', '확인해', '어디', '무엇', '어떤', '얼마')):
        return None

    hard_terms = (
        '실명', '신원', '신분', '담당자', '대표자', '계정', '가게 이름', '상호명', '지갑', '주소', '계좌', '연락처', '전화번호',
        '이메일', '사업자등록', '개인정보', '개인 정보', '비공개', '내부 정보', '비밀', '고객 정보', '구매자 정보', '판매자 정보',
        '송금', '입금', '출금', '이체', '전송', '환불', '반품', '환급', '결제', '주문', '발주', '예약', '홀드', '찜해', '담아',
        '구매해', '구매 부탁', '구입해', '사 주세요', '사주세요', '거래 확정', '거래 실행', '대체 불가', '다른 건', '다른 상품은',
        '다른 제품은', '바로 그', '똑같은', '오직', '말고', '빼고', '싫습니다', '브랜드', '상표', '알레르', '알러지',
        '건강', '의약', '치료', '효능', '보증', '정품', '인증', '유기농', '무농약', '무첨가', '이상', '이하', '이내', '미만',
        '초과', '최소', '최대', '등급 이상', '상 등급', '특등급', '일등급', '상급', '최상급', '고급', '만원', '만 원', '천원', '천 원',
    )
    if any(ch.isnumeric() for ch in original) or any(term in original for term in hard_terms):
        return None
    temporal = ('오늘', '내일', '모레', '금일', '당일', '익일', '이번 주', '다음 주', '오전', '오후')
    limits = ('까지', '안에', '이전', '이후', '전에', '배송', '출고', '도착', '수령', '발송', '받을', '받으')
    if any(t + gap + limit in original for t in temporal for limit in limits for gap in ('', ' ')):
        return None
    numbers = ('한', '두', '세', '네', '다섯', '여섯', '일곱', '여덟', '아홉', '열', '몇', '여러')
    units = ('개', '병', '봉', '팩', '상자', '박스', '묶음', '킬로', '그램', '인분', '등급', '시간', '분', '일', '주', '개월')
    if any(number + gap + unit in original for number in numbers for unit in units for gap in ('', ' ')):
        return None

    def bounded_end(value, start, phrase, particles=('',)):
        if not value.startswith(phrase, start):
            return None
        base = start + len(phrase)
        for particle in particles:
            end = base + len(particle)
            if value.startswith(particle, base) and (end == len(value) or value[end] in separators):
                return end
        return None

    clause_start = split + 1
    while clause_start < len(original) and original[clause_start] == ' ':
        clause_start += 1
    clause = original[clause_start:].rstrip(' ')
    if clause and clause[-1] in ',、' + sentence_marks:
        clause = clause[:-1].rstrip(' ')
    if clause.endswith(' 그리고'):
        clause = clause[:-len(' 그리고')].rstrip(' ')
    reports = ('알려주시고', '알려 주시고', '알려주세요', '알려 주세요', '알려주시면', '알려 주시면',
               '말씀해 주시고', '말씀해 주세요', '알려주시겠어요', '알려 주시겠어요')
    report = next((word for word in reports if clause.endswith(' ' + word)), None)
    if report is None:
        return None
    details = clause[:-len(report)].rstrip(' ')
    mask = list(details)
    fact_spans = []
    title_spans = []
    buy_spans = []

    def cover(start, end, spans=None):
        mask[start:end] = [' '] * (end - start)
        if spans is not None:
            spans.append((clause_start + start, clause_start + end))

    pos = 0
    for modifier in ('혹시', '현재', '지금', '우선'):
        if details.startswith(modifier + ' ', pos):
            end = pos + len(modifier)
            cover(pos, end)
            pos = end
            while pos < len(details) and details[pos] == ' ':
                pos += 1
    descriptors = ('살 수 있는', '구매할 수 있는', '구입할 수 있는', '판매 중인', '판매중인', '구매 가능한', '구입 가능한')
    for descriptor in descriptors:
        if details.startswith(descriptor + ' ', pos):
            end = pos + len(descriptor)
            cover(pos, end, buy_spans)
            pos = end
            while pos < len(details) and details[pos] == ' ':
                pos += 1
            break
    end = bounded_end(details, pos, noun, ('', '이', '가', '은', '는', '을', '를', '의', '도'))
    if end is None:
        return None
    cover(pos, end)
    pos = end
    while pos < len(details) and details[pos] in ' ,、':
        pos += 1

    facts = set()
    predicates = ('있으면', '있다면', '있는 경우', '있을 경우', '있으시면')
    condition = next((end for prefix in ('재고가 ', '재고 ', '') for predicate in predicates
                      for end in (bounded_end(details, pos, prefix + predicate),) if end is not None), None)
    if condition is not None:
        cover(pos, condition, fact_spans)
        facts.add('재고')
        pos = condition

    c = n['load_catalogue']()
    patterns = c['PREP_FACT']
    if hasattr(patterns, 'finditer'):
        patterns = (patterns,)
    elif hasattr(patterns, 'values'):
        patterns = tuple(patterns.values())
    hits = [(match.start(), match.end()) for pattern in patterns for match in pattern.finditer(details)
            if match.end() > match.start()]
    titles = ('상품명', '상품 이름', '제품명', '제품 이름')
    prices = ('가격', '판매가', '판매 가격', '판매가격', '정가', '금액', '표시가', '게시가', '등록가')
    fields = (
        ('재고', ('재고', '재고 여부', '재고 유무', '재고 수량', '현재 재고', '재고가 있는지', '재고 있는지')),
        ('상품명', tuple(prefix + title for prefix in ('', '정확한 ', '공개 ', '등록 ', '등록된 ', '표기된 ', '정확한 등록 ') for title in titles)),
        ('등급', ('등급', '상품 등급', '제품 등급', '등록 등급', '표시 등급')),
        ('가격', tuple(prefix + price for prefix in ('', '표시 ', '표시된 ', '게시 ', '게시된 ', '등록 ', '등록된 ', '공개 ', '표기 ', '표기된 ', '기재된 ') for price in prices)
         + ('표시가격', '게시가격', '공개가격', '등록가격')),
        ('유통기한', ('유통기한', '유통 기한', '유통기간', '유통 기간', '소비기한', '소비 기한', '보관기한', '보관 기한',
                   '유효기간', '유효 기간', '표시 유통기한', '유통기한이 언제인지')),
    )
    particles = ('', '이', '가', '은', '는', '을', '를', '과', '와', '도', '까지', '이랑', '랑', '하고')
    while pos < len(details):
        if pos and details[pos - 1] not in separators:
            pos += 1
            continue
        best = None
        for fact, forms in fields:
            for form in forms:
                end = bounded_end(details, pos, form, particles)
                if end is not None and (best is None or end > best[0]) and any(pos <= first < last <= end for first, last in hits):
                    best = (end, fact, form)
        if best is None:
            pos += 1
            continue
        end, fact, form = best
        cover(pos, end, fact_spans)
        if fact == '상품명' and form.startswith('정확한 '):
            title_spans.append((clause_start + pos, clause_start + end))
        facts.add(fact)
        pos = end

    plain = c['PREP_PLAIN']
    connective = {'및', '그리고', '와', '과', '도', '을', '를', '은', '는', '이', '가', '함께', '같이', '모두', '각각', '좀', '정보', '여부'}
    remainder = ''.join(mask)
    for separator in separators[1:]:
        remainder = remainder.replace(separator, ' ')
    if not facts or any(word not in plain or word not in connective for word in remainder.split()):
        return None

    exceptions = {'EXACT': title_spans, 'OTHER_HARD_ATTRIBUTE': fact_spans, 'RESTRICTED': buy_spans}
    for key in ('SKU', 'EXACT', 'NEGATION', 'PROOF_OR_AUTHORITY', 'UNVERIFIED', 'RESTRICTED', 'OTHER_HARD_ATTRIBUTE'):
        for match in n[key].finditer(original):
            if not any(start <= match.start() < match.end() <= end for start, end in exceptions.get(key, ())):
                return None
    canonical = ' '.join([noun] + [fact for fact, forms in fields if fact in facts] + ['알려주세요'])
    return canonical, '관련 재고에 관한 참고 정보이며 견적이 아닙니다. 원문의 조건은 확인되지 않았습니다.'