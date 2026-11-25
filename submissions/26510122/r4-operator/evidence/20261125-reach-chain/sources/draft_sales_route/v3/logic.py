import re
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
BOARD = 'https://market.ourolabs.ai/api/agents'


def whole(value, minimum=0):
    return type(value) is int and value >= minimum


def record(value):
    return value if isinstance(value, dict) else {}


def blocked(reason):
    return {'mode': 'synthetic', 'status': 'blocked', 'reason': reason}


def kst(value):
    return datetime.fromtimestamp(value, KST).strftime('%Y-%m-%d %H:%M:%S KST')


def fits(values, sku):
    return isinstance(values, list) and sku in values


def benefits_for(value, sku, now):
    if value.get('matched') is not True:
        return []
    benefits = []
    mileage = record(value.get('mileage'))
    settled = mileage.get('settled_at')
    delivered = mileage.get('delivered_at')
    if whole(settled) and whole(delivered):
        earned = max(settled, delivered)
        expires = earned + 604800
        if mileage.get('next_trade') is True and mileage.get('unused') is True and earned <= now < expires:
            benefits.append(('기존 마일리지 1%', '정상 정산과 인도가 모두 끝난 때부터 7일 이내의 다음 거래에 기준가의 1%를 적용합니다.', expires))
    delay = record(value.get('delay'))
    issued = delay.get('issued_at')
    if (delay.get('confirmed') is True and delay.get('unused') is True
            and delay.get('sku') == sku and whole(issued) and issued <= now < issued + 120):
        benefits.append(('대기권 1%', '확인된 앞선 처리 지연으로 발급된 대기권은 발급 후 120초 이내의 같은 SKU 재문의에 적용됩니다.', issued + 120))
    return benefits


def run(args, kit):
    args = record(args)
    fixture = record(args.get('fixture'))
    channel = args.get('channel')
    now = fixture.get('now')
    if fixture.get('mode') != 'synthetic' or channel not in ('first', 'return', 'forum') or not whole(now):
        return blocked('synthetic_fixture_required')

    offer = record(fixture.get('offer'))
    sku, name, grade = (offer.get(key) for key in ('sku', 'name', 'grade'))
    kind, price = offer.get('kind'), offer.get('price')
    checked, end, expiry = (offer.get(key) for key in ('checked_at', 'valid_until', 'expires_at'))
    if (not isinstance(sku, str) or not re.fullmatch(r'sim-[a-z0-9_-]{1,32}', sku)
            or not isinstance(name, str) or not re.fullmatch(r'가상 [가-힣A-Za-z0-9 ()-]{1,35}', name)
            or grade not in ('A', 'B', 'C') or kind not in ('food', 'goods')
            or offer.get('available') is not True or not whole(price, 1)):
        return blocked('saleable_unit_required')
    if not whole(checked) or not whole(end) or not checked <= now < end:
        return blocked('offer_outside_validity')
    if kind == 'food' or expiry is not None:
        if not whole(expiry) or expiry <= now:
            return blocked('unit_expired_or_expiry_unknown')
        end = min(end, expiry)

    forum = record(fixture.get('forum'))
    thread = None
    intent = 'inquiry'
    if channel == 'forum':
        context = forum.get('kind')
        last = forum.get('last_post_at')
        if forum.get('reviewed') is not True or context not in ('purchase_request', 'own_stock'):
            return blocked('forum_context')
        if 'last_post_at' not in forum or (last is not None and (not whole(last) or now - last < 300)):
            return blocked('forum_post_gap')
        if context == 'purchase_request':
            thread = forum.get('thread_id')
            if not whole(thread, 1) or not fits(forum.get('acceptable_skus'), sku):
                return blocked('forum_request_mismatch')
        elif forum.get('thread_id') is not None:
            return blocked('own_stock_requires_top_level')
    else:
        if not fits(fixture.get('acceptable_skus'), sku):
            return blocked('requested_sku_mismatch')
        intent = fixture.get('intent', 'inquiry')
        quantity = fixture.get('quantity')
        if intent not in ('inquiry', 'request_checkout') or ('quantity' in fixture and not whole(quantity, 1)):
            return blocked('invalid_contact_intent')
        if intent == 'request_checkout' and quantity != 1:
            return blocked('checkout_requires_explicit_single_unit')

    hours = fixture.get('use_within_hours', 0)
    if not whole(hours):
        return blocked('remaining_shelf_life')
    if kind == 'food' and hours:
        latest_eligible = expiry - hours * 3600
        if now > latest_eligible:
            return blocked('remaining_shelf_life')
        end = min(end, latest_eligible + 1)

    fees = record(fixture.get('fees'))
    bps, standard = (fees.get(key) for key in ('market_fee_bps', 'network_fee_credits'))
    if not whole(bps) or bps > 10000 or not whole(standard) or standard % 2:
        return blocked('fee_schedule_required')
    market_fee, half_network = price * bps // 10000, standard // 2
    seller_transfer = price - market_fee - half_network
    if seller_transfer <= 0:
        return blocked('invalid_seller_transfer_amount')
    buyer_standard_fee = market_fee + half_network
    standard_total = price + buyer_standard_fee
    transfers_before_gas = seller_transfer + 2 * market_fee

    returning = record(fixture.get('returning'))
    benefits = benefits_for(returning, sku, now) if channel == 'return' else []
    if benefits:
        baseline = returning.get('baseline_price')
        if not whole(baseline, 1) or price > baseline:
            return blocked('benefit_price_baseline')
        end = min(end, min(expires for _, _, expires in benefits))

    try:
        timing = f'재고·등급·가격 확인 {kst(checked)} · 안내 유효 {kst(end)} 전까지.'
        benefit_details = [f'{condition} 유효 {kst(expires)} 전까지.' for _, condition, expires in benefits]
    except (OverflowError, OSError, ValueError):
        return blocked('invalid_timestamp')
    if len(benefits) == 2:
        benefit_details.append('같은 SKU에 두 혜택을 함께 쓸 수 있으며 혜택을 상쇄하는 가격 인상은 금지됩니다.')

    lines = ['[합성 초안 · 발송·게시 금지]']
    if benefits:
        names = ' + '.join(label for label, _, _ in benefits)
        suffix = ' 병용 가능' if len(benefits) == 2 else ' 사용 가능'
        lines.append(f'{names}{suffix}. 아래 합계는 혜택 적용 전입니다.')
    lines.append(f'outseop-r4 · {name} ({sku}) · {grade}등급 · 재고 1개 · 상품가 {price:,} 크레딧.')
    if grade == 'C':
        lines.append('C등급은 낮은 마진으로 빠르게 판매하는 정책을 적용합니다.')
    lines.extend([
        f'표준 예상합계 {standard_total:,} 크레딧(상품가 + 표준 수수료 {buyer_standard_fee:,}). 실제 지갑 지출은 송금액 {transfers_before_gas:,}과 Maroo 가스 실비의 합입니다.',
        timing,
        f'{BOARD}에서 outseop-r4의 최신 Agent Card가 확인되면 해당 카드의 A2A로 문의하세요.',
    ])
    if intent == 'request_checkout':
        lines.append('결제권 요청 수량 1개. 결제 전 EIP-191 서명 checkout_jwt의 상품·금액과 Maroo 가스를 확인하세요.')
    else:
        lines.append('SKU·수량을 문의할 수 있습니다. 구매를 결정하면 해당 SKU 1개의 결제권을 별도로 요청하세요.')
    lines.append('결제권·결제·정산·인도 증빙과 환불 조건은 함께 제공되는 상세 조건을 확인하세요.')
    text = '\n'.join(lines)
    if channel == 'forum' and len(text) > 2000:
        return blocked('forum_post_length')

    details = {
        'purchase': '구매에 동의한 뒤 A2A로 SKU 1개의 checkout_jwt를 요청합니다. 결제권이 제공되면 서명·판매자·SKU·가격을 확인하고 구매자 측에서 주문과 결제·정산을 진행합니다.',
        'fees': f'표준 수수료 {buyer_standard_fee:,} 크레딧은 시장 수수료 {market_fee:,}와 표준 네트워크 분담액 {half_network:,}의 합입니다. 실제 지갑 지출은 판매자 송금 {seller_transfer:,}과 시장 송금 {2 * market_fee:,}에 실제 원결제 가스를 더해 계산합니다. 결제 전 지갑에서 가스를 확인하세요.',
        'evidence': '결제권은 판매자 지갑의 EIP-191 서명 checkout_jwt로 확인합니다. Maroo 거래 영수증으로 원결제 송금을, 시장 정산 영수증으로 정산을 확인합니다. 실제 인도는 인도 증빙으로, 승인 후 실행된 환불은 별도 반환 송금 영수증으로 확인합니다.',
        'refund': '인도 후 48시간 이내 확인된 초기 문제 또는 판매자 귀책 미인도가 검토 대상입니다. 증빙을 수업 모델이 검토·승인한 뒤 도구에서 한도와 중복을 확인해야 하며, 승인된 반환은 원결제에서 검증한 송금인에게만 진행하는 경로입니다. 실제 반영 여부는 반환 송금 영수증으로 확인합니다.',
    }
    if benefit_details:
        details['benefits'] = benefit_details
    return {
        'mode': 'synthetic', 'status': 'draft', 'channel': channel, 'intent': intent,
        'sku': sku, 'available_quantity': 1, 'valid_until': end, 'text': text,
        'policy_details': details,
        'fees': {'item_price': price, 'market_fee': market_fee, 'standard_network_share': half_network,
                 'buyer_standard_fee': buyer_standard_fee, 'standard_total': standard_total,
                 'transfers_before_gas': transfers_before_gas, 'actual_gas': None},
        'thread_id': thread,
    }
