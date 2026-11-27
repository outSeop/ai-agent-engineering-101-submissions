import hashlib,re
P='tools/semantic_candidates_v4/logic.py'
H='01e59f9b5e06b0402a669bfbd9c78e350c9cb32e9c65bfd111fdf5ac1a74b39c'
def unavailable(r): return {'status':'unavailable','reason':r}
def load():
    try:
        b=open(P,'rb').read(128*1024+1)
        if len(b)>128*1024 or hashlib.sha256(b).hexdigest()!=H:return None
        n={'__name__':'_pinned_v4'};exec(compile(b,P,'exec'),n);return n
    except Exception:return None
def rows(reply):
    z=[]
    for line in reply.splitlines():
        if '· SKU ' in line:
            m=re.search(r'\bSKU\s+(G[0-9a-f]{8})\b',line,re.I)
            if m:z.append((m.group(1).casefold(),line))
    return z
def repeated(text,phrase):
    if not isinstance(text,str) or not isinstance(phrase,str): return None
    if len(text)>1500 or not 1<=len(phrase)<=48:return None
    p=re.escape(phrase)
    # Only a later, complete, single-clause affirmative stock/fact question.
    pat=re.compile(r'(?<![\w-])\s+'+p+r'(?:은|는|이|가)?\s*어떤\s+상품이\s+있(?:나요|어요|을까요)\?')
    ms=list(pat.finditer(text))
    if len(ms)!=1:return None
    m=ms[0]
    if m.start()==0 or text[m.start()-1] not in '.!?':return None
    prior=text[:m.start()-1]
    if len(re.findall(r'(?<![.!?])\s*'+p+r'(?:은|는|이|가)?',prior))<1:return None
    return text[:m.start()]+text[m.end():]
def run(a,kit):
    if type(a) is not dict:return unavailable('invalid_args')
    if set(a)=={'op','text','product_phrase','queries'} and a.get('op')=='semantic_candidates':
        n=load()
        if n is None:return unavailable('dependency_unavailable')
        r=n['run'](a,kit)
        if r.get('status')!='unavailable' or r.get('reason')!='unsupported_request':return r
        previewed=preview(a,kit,n)
        if previewed is not None:return previewed
        t=repeated(a['text'],a['product_phrase'])
        if t is None:return r
        b=dict(a);b['text']=t
        return n['run'](b,kit)
    if set(a)!={'op','text','groups'} or a.get('op')!='semantic_candidates':return unavailable('invalid_args')
    text=a['text'];groups=a['groups']
    if type(text) is not str or not 1<=len(text)<=1500 or type(groups) is not list or not 1<=len(groups)<=2:return unavailable('invalid_args')
    if any(type(g) is not dict or set(g)!={'product_phrase','queries'} or type(g['product_phrase']) is not str or type(g['queries']) is not list or not 1<=len(g['queries'])<=2 or any(type(q) is not str for q in g['queries']) for g in groups):return unavailable('invalid_args')
    n=load()
    if n is None:return unavailable('dependency_unavailable')
    ps=[g['product_phrase'] for g in groups]
    if len(groups)==1:return run({'op':'semantic_candidates','text':text,'product_phrase':ps[0],'queries':groups[0]['queries']},kit)
    if ps[0]==ps[1] or any(len(x)<1 or len(x)>48 for x in ps):return unavailable('unsupported_request')
    if any(re.search(r'브랜드|제조사|상표|brand|manufacturer',x,re.I) for x in (text+''.join(ps)+''.join(q for g in groups for q in g['queries']))):return unavailable('unsupported_request')
    pat=re.compile(r'(?<![\w-])'+re.escape(ps[0])+r'\s*(와|과)\s*'+re.escape(ps[1])+r'(?![\w-])');ms=list(pat.finditer(text))
    if len(ms)!=1:return unavailable('unsupported_request')
    m=ms[0];obs=until=None;bs=[]
    for i,g in enumerate(groups):
        r=n['run']({'op':'semantic_candidates','text':text[:m.start()]+ps[i]+text[m.end():],'product_phrase':ps[i],'queries':g['queries']},kit)
        if r.get('status')=='rendered':
            if obs is None:obs,until=r.get('observed_at'),r.get('valid_until')
            if (r.get('observed_at'),r.get('valid_until'))!=(obs,until):return unavailable('stale_snapshot')
            bs.append(rows(r.get('reply','')))
        elif r.get('reason') in ('no_match','selection_unavailable'):bs.append([])
        else:return unavailable('unsupported_request')
    seen=set();chosen=[]
    for i,b in enumerate(bs):
        x=next(((s,l) for s,l in b if s not in seen),None)
        if not x:return unavailable('no_match')
        chosen.append('요청 '+str(i+1)+' · '+x[1]);seen.add(x[0])
    out='\n'.join(['유사어로 찾은 참고 후보입니다. 정확한 상품 일치와 요청 조건 전체의 충족 여부는 확인되지 않았습니다. 표시 가격은 공개 상품가.']+chosen+['원하는 SKU로 구매 조건을 다시 문의해 주세요.'])
    return {'status':'rendered','reply':out,'observed_at':obs,'valid_until':until} if len(out)<=450 else unavailable('response_too_long')

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
def related_read(args, kit, n):
    original_load = n['load_catalogue']

    def load_related_catalogue():
        catalogue = original_load()
        original_read = catalogue['read_snapshot']

        def read_related_snapshot():
            raw = original_read()
            codec = catalogue['json']
            try:
                snapshot = codec.loads(
                    raw.decode('utf-8'),
                    object_pairs_hook=catalogue['unique_object'],
                    parse_float=catalogue['reject_number'],
                    parse_constant=catalogue['reject_number'],
                )
                if not isinstance(snapshot, dict):
                    return raw
                units = snapshot.get('units')
                if not isinstance(units, list):
                    return raw
                refs = catalogue['index_units'](units)[3]
                safe_label = catalogue['safe_label']
                changed = False

                for unit in units:
                    if not isinstance(unit, dict):
                        continue
                    path = unit.get('category_path')
                    if not isinstance(path, list) or not 1 <= len(path) <= 8:
                        continue
                    expanded = []
                    for label in path:
                        if not isinstance(label, str):
                            break
                        if '/' not in label:
                            expanded.append(label)
                            continue
                        if len(label) > 128 or not label.isprintable():
                            break
                        parts = [part.strip() for part in label.split('/')]
                        if not 2 <= len(parts) <= 8 or not all(parts):
                            break
                        labels_to_check = (*parts, ' '.join(parts), ''.join(parts))
                        if not all(safe_label(value, 128, refs) for value in labels_to_check):
                            break
                        expanded.extend(parts)
                    else:
                        if len(expanded) <= 8 and expanded != path:
                            unit['category_path'] = expanded
                            changed = True

                if not changed:
                    return raw
                encoded = codec.dumps(
                    snapshot, ensure_ascii=False, allow_nan=False, separators=(',', ':')
                ).encode('utf-8')
                return bytearray(encoded.ljust(len(raw), b' '))
            except (ValueError, TypeError, KeyError, IndexError, RecursionError, OverflowError):
                return raw

        overlay = catalogue.copy()
        overlay['read_snapshot'] = read_related_snapshot
        return overlay

    try:
        n['load_catalogue'] = load_related_catalogue
        return n['run'](args, kit)
    finally:
        n['load_catalogue'] = original_load

def preview(a,kit,n):
    disclaimer=None
    parsed=fact_clause(a,n)
    if parsed is None:
        candidate=fact_fallback(a,n)
        if candidate is None:return None
        text,disclaimer=candidate
        if not isinstance(disclaimer,str) or not 1<=len(disclaimer)<=65:return None
        hold=True
    else:
        text,hold=parsed
    keys=dict(a,text=text)
    if not hold:
        plain=n['run'](keys,kit)
        return plain if plain.get('status')=='rendered' else None
    r=related_read(keys,kit,n) if disclaimer is not None else n['run'](keys,kit)
    if not isinstance(r,dict):
        return None
    out={k:r[k] for k in ('reply','status','observed_at','valid_until') if k in r}
    if 'reply' not in out:
        return r
    if r.get('status')=='rendered':
        msg=out.get('reply','')
        tail='결제서는 발행하지 않았습니다.'
        if tail not in msg:
            msg=(msg+' '+tail).strip()
        if len(msg)>450:
            return None
        out['reply']=msg
        out['payment_request']={'status':'not_issued','reason':'product_selection_required'}
    else:
        return None
    if disclaimer is not None:
        if len(out['reply'])+len(disclaimer)+1>450:return None
        out['reply']=disclaimer+chr(10)+out['reply']
    return out
