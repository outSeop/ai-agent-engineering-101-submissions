import hashlib
import json
import os
import re
import tempfile
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

SHOP = 'outseop-r4'
CARD = Path('card.json')
CONTEXT = Path('host_inputs/card_offer_context.json')
STAGE = Path('card_update_stage')
DIRECTORY = 'https://market.ourolabs.ai/api/agents'
KST = timezone(timedelta(hours=9))
MAX_AGE = 180
MAX_INPUT_BYTES = 8 * 1024 * 1024
CONTEXT_FIELDS = {'schema', 'shop', 'observed_at', 'valid_until', 'card_sha256', 'replace_text', 'offers', 'market'}
OFFER_FIELDS = {'sku', 'name', 'category_path', 'state', 'grade', 'price_credits', 'standard_fee_credits', 'valid_until', 'expires_at'}
MARKET_FIELDS = {'start', 'end', 'coverage', 'counts'}
SKU = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}')
TITLE = re.compile(r'현재 대표 상품 \([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2} KST 기준\)\n')
SECRET = re.compile(r'0x[a-fA-F0-9]{40,}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+')


class Invalid(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise Invalid(code)


def integer(value, minimum=0):
    return type(value) is int and value >= minimum


def sku_ok(value):
    return isinstance(value, str) and SKU.fullmatch(value) is not None and not SECRET.search(value)


def label(value):
    return (isinstance(value, str) and 0 < len(value) <= 160 and value == value.strip()
            and not SECRET.search(value)
            and all(not unicodedata.category(char).startswith('C') and char not in '\u2028\u2029' for char in value))


def fields(value, expected, code):
    require(isinstance(value, dict) and value.keys() == expected, code)


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate_json_key')
        result[key] = value
    return result


def invalid_constant(value):
    raise Invalid('invalid_json_number')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('utf-8')


def read_raw(path):
    with path.open('rb') as stream:
        raw = stream.read(MAX_INPUT_BYTES + 1)
    require(len(raw) <= MAX_INPUT_BYTES, 'input_too_large')
    return raw


def decode(raw):
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=unique_pairs, parse_constant=invalid_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise Invalid('invalid_json') from exc


def verify_market(market, observed_at):
    if market is None:
        return
    fields(market, MARKET_FIELDS, 'invalid_market_observation')
    require(integer(market['start']) and integer(market['end'])
            and market['start'] < market['end'] <= observed_at
            and market['coverage'] in ('partial', 'boundaries_observed')
            and isinstance(market['counts'], dict), 'invalid_market_observation')
    require(all(sku_ok(sku) and integer(count) for sku, count in market['counts'].items()), 'invalid_market_count')


def verify_offer(row):
    fields(row, OFFER_FIELDS, 'invalid_offer_fields')
    require(sku_ok(row['sku']) and label(row['name']) and isinstance(row['category_path'], list)
            and row['category_path'] and all(label(part) for part in row['category_path']), 'invalid_public_catalog_fields')
    require(row['state'] in ('available', 'reserved', 'sold_out'), 'invalid_stock_state')
    require(row['grade'] in ('A', 'B', 'C') and integer(row['price_credits'], 1), 'invalid_grade_or_price')
    require(row['standard_fee_credits'] is None or integer(row['standard_fee_credits']), 'invalid_standard_fee')
    require(integer(row['valid_until'], 1)
            and (row['expires_at'] is None or integer(row['expires_at'], 1)), 'invalid_offer_expiry')


def expiry(row, view):
    deadline = min(row['valid_until'], view['valid_until'])
    if row['expires_at'] is not None:
        deadline = min(deadline, row['expires_at'])
    return deadline


def load(now):
    card_raw = read_raw(CARD)
    view_raw = read_raw(CONTEXT)
    card = decode(card_raw)
    view = decode(view_raw)
    require(isinstance(card, dict) and card.get('name') == SHOP
            and isinstance(card.get('description'), str) and isinstance(card.get('skills'), list)
            and len(card['skills']) == 3 and all(isinstance(skill, dict) for skill in card['skills']), 'invalid_card_identity_or_skills')
    fields(view, CONTEXT_FIELDS, 'invalid_context_fields')
    require(view['schema'] == 'outseop-r4.card-offers.v1' and view['shop'] == SHOP, 'wrong_context_shop_or_schema')
    require(integer(view['observed_at']) and integer(view['valid_until'])
            and view['observed_at'] <= now < view['valid_until'] <= view['observed_at'] + MAX_AGE, 'stale_or_future_view')
    require(view['card_sha256'] == digest(card_raw), 'card_changed')
    section = view['replace_text']
    require(isinstance(section, str) and section.strip() and card['description'].count(section) == 1, 'reviewed_card_section_missing_or_ambiguous')
    verify_market(view['market'], view['observed_at'])
    require(isinstance(view['offers'], list), 'invalid_offers')
    offers = {}
    for row in view['offers']:
        verify_offer(row)
        require(row['sku'] not in offers, 'duplicate_offer_sku')
        offers[row['sku']] = row
    return card_raw, view_raw, card, view, offers


def compare(offers, view, now):
    market = view['market']
    candidates = []
    for row in sorted(offers.values(), key=lambda item: (item['category_path'], item['sku'])):
        if row['state'] != 'available' or now >= expiry(row, view):
            continue
        item = dict(row)
        item['valid_until'] = expiry(row, view)
        fee = row['standard_fee_credits']
        item['standard_estimated_total_credits'] = None if fee is None else row['price_credits'] + fee
        if market is not None:
            item['public_settlement_count'] = market['counts'].get(row['sku'])
        candidates.append(item)
    sample = None if market is None else {key: market[key] for key in ('start', 'end', 'coverage')}
    return {'candidates': candidates, 'public_market_sample': sample, 'market_directory': DIRECTORY}


def render(rows, observed_at):
    stamp = datetime.fromtimestamp(observed_at, KST).strftime('%Y-%m-%d %H:%M:%S KST')
    lines = [f'현재 대표 상품 ({stamp} 기준)']
    for row in rows:
        price = row['price_credits']
        fee = row['standard_fee_credits']
        line = f"- {row['name']} · SKU {row['sku']} · 현재 {row['grade']}등급 · 상품가 {price:,} 크레딧"
        if fee is not None:
            line += f' · 표준 수수료 {fee:,} · 표준 예상 총액 {price + fee:,} 크레딧'
        lines.append(line)
    lines.extend([
        '',
        '재고·등급·가격은 변동될 수 있습니다. 시장 보드 또는 /api/agents에서 outseop-r4의 최신 Agent Card를 찾으세요. A2A에서 SKU 재고·등급·최신 조건을 확인하고, 구매를 명시적으로 결정한 뒤 결제권을 요청하세요.',
        '표준 예상 총액은 상품가와 표준 수수료의 합입니다. Maroo 실제 가스는 결제 시 별도로 확인하세요.',
        '정상 정산과 인도 후 기준가의 1% 마일리지를 지급하며, 7일 동안 다음 거래에 쓸 수 있습니다. 실제 앞선 처리로 지연된 경우 발급한 1% 대기권은 발급 후 120초 이내 같은 상품 재문의 시 기존 마일리지와 함께 쓸 수 있습니다. 혜택을 상쇄하는 가격 인상은 적용하지 않습니다.',
        '환불 대상은 인도 후 48시간 내 확인된 초기 문제 또는 판매자 귀책 미인도입니다. 증빙을 수업 모델이 검토·승인한 뒤 환불 한도와 중복 여부를 확인해 검증된 원송금인에게 반환하는 절차입니다. 통합 승인과 실제 환불 송금 연결은 개발 중입니다.'
    ])
    return '\n'.join(lines)


def record_once(record_id, payload):
    destination = STAGE / (record_id + '.json')
    with tempfile.NamedTemporaryFile(mode='wb', dir=STAGE, prefix='.pending-', delete=False) as stream:
        pending = Path(stream.name)
        try:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
            stream.close()
            try:
                os.link(pending, destination)
            except FileExistsError:
                require(destination.read_bytes() == payload, 'stage_record_conflict')
                return False
            return True
        finally:
            stream.close()
            pending.unlink(missing_ok=True)


def run(args, kit):
    try:
        require(isinstance(args, dict), 'invalid_arguments')
        op = args.get('op')
        require(op in ('compare', 'stage'), 'invalid_operation')
        expected = {'op'} if op == 'compare' else {'op', 'skus', 'view_sha256'}
        fields(args, expected, 'unexpected_arguments')
        now = int(time.time())
        card_raw, view_raw, card, view, offers = load(now)
        view_hash = digest(view_raw)
        result = {'view_sha256': view_hash, 'observed_at': view['observed_at'], 'valid_until': view['valid_until']}
        if op == 'compare':
            return {**result, **compare(offers, view, now), 'status': 'ready'}
        require(args['view_sha256'] == view_hash, 'view_changed')
        skus = args['skus']
        require(isinstance(skus, list) and skus and all(sku_ok(sku) for sku in skus), 'invalid_selection')
        require(len(set(skus)) == len(skus), 'duplicate_selected_sku')
        chosen = []
        for sku in skus:
            row = offers.get(sku)
            require(row is not None and row['state'] == 'available' and now < expiry(row, view), 'sku_not_sellable')
            chosen.append(row)
        deadline = min(expiry(row, view) for row in chosen)
        before_section = view['replace_text']
        after_section = render(chosen, view['observed_at'])
        match = TITLE.match(before_section)
        new_title = TITLE.match(after_section)
        if match and new_title and before_section[match.end():].rstrip('\n') == after_section[new_title.end():]:
            return {**result, 'valid_until': deadline, 'status': 'unchanged'}
        retained = card['description'].replace(before_section, '', 1)
        after = {**card, 'description': after_section + ('\n\n' + retained if retained else '')}
        after_raw = encode(after)
        record = {
            'schema': 'outseop-r4.card-stage.v1', 'shop': SHOP, 'skus': skus,
            'observed_at': view['observed_at'], 'valid_until': deadline,
            'view_sha256': view_hash, 'before_sha256': digest(card_raw), 'after_sha256': digest(after_raw),
            'before_card_json': card_raw.decode('utf-8'), 'after_card_json': after_raw.decode('utf-8')
        }
        payload = encode(record)
        record_id = digest(payload)
        require(read_raw(CARD) == card_raw and read_raw(CONTEXT) == view_raw, 'inputs_changed_during_stage')
        require(int(time.time()) < deadline, 'selection_expired_during_stage')
        created = record_once(record_id, payload)
        return {**result, 'valid_until': deadline, 'status': 'staged' if created else 'already_staged', 'record_id': record_id}
    except Invalid as exc:
        return {'status': 'rejected', 'error': str(exc)}
    except (OSError, OverflowError, UnicodeError):
        return {'status': 'rejected', 'error': 'host_input_or_stage_unavailable'}
