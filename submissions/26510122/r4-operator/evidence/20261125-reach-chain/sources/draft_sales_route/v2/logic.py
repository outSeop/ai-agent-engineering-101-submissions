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
        earned_at = max(settled, delivered)
        expires_at = earned_at + 604800
        if (mileage.get('next_trade') is True and mileage.get('unused') is True
                and earned_at <= now < expires_at):
            benefits.append(('정상 정산·인도 후 적립된 기준가 1% 마일리지(7일 이내 다음 거래)', expires_at))
    delay = record(value.get('delay'))
    issued = delay.get('issued_at')
    if (delay.get('confirmed') is True and delay.get('unused') is True
            and delay.get('sku') == sku and whole(issued) and issued <= now < issued + 120):
        benefits.append(('앞선 처리 지연 대기권 1%(발급 후 120초 이내 같은 상품 재문의)', issued + 120))
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
    if channel == 'forum':
        context = forum.get('kind')
        last = forum.get('last_post_at')
        if forum.get('reviewed') is not True or context not in ('purchase_request', 'own_stock'):
            return blocked('forum_context')
        if 'last_post_at' not in forum or (last is not None and (not whole(last) or now - last < 300)):
            return blocked('forum_post_gap')
        if context == 'purchase_request' and (not whole(forum.get('thread_id'), 1) or not fits(forum.get('acceptable_skus'), sku)):
            return blocked('forum_request_mismatch')
        if context == 'own_stock' and forum.get('thread_id') is not None:
            return blocked('own_stock_requires_top_level')
    elif not fits(fixture.get('acceptable_skus'), sku):
        return blocked('requested_sku_mismatch')

    hours = fixture.get('use_within_hours', 0)
    if not whole(hours):
        return blocked('remaining_shelf_life')
    if kind == 'food' and hours:
        latest_eligible = expiry - hours * 3600
        if now > latest_eligible:
            return blocked('remaining_shelf_life')
        # The final eligible second is inclusive. The output cutoff is exclusive.
        end = min(end, latest_eligible + 1)

    fees = record(fixture.get('fees'))
    bps, standard = (fees.get(key) for key in ('market_fee_bps', 'network_fee_credits'))
    if not whole(bps) or bps > 10000 or not whole(standard) or standard % 2:
        return blocked('fee_schedule_required')
    market_fee, half_network = price * bps // 10000, standard // 2
    if price - market_fee - half_network <= 0:
        return blocked('invalid_seller_transfer_amount')

    returning = record(fixture.get('returning'))
    benefits = benefits_for(returning, sku, now) if channel == 'return' else []
    if benefits:
        baseline = returning.get('baseline_price')
        if not whole(baseline, 1) or price > baseline:
            return blocked('benefit_price_baseline')
        end = min(end, min(expires_at for _, expires_at in benefits))

    try:
        timing = f'재고·등급·가격 확인 {kst(checked)} · 안내 유효 {kst(end)} 전까지.'
    except (OverflowError, OSError, ValueError):
        return blocked('invalid_timestamp')
    lines = ['[합성 초안 · 발송·게시 금지]']
    if benefits:
        suffix = ' · 두 혜택은 함께 쓸 수 있습니다.' if len(benefits) == 2 else '.'
        lines.append('기존 혜택 안내 · ' + ' / '.join(label for label, _ in benefits) + suffix)
    lines.append(f'outseop-r4 · {name} ({sku}) · 현재 {grade}등급 · 판매 가능 확인 1개 · {price:,} 크레딧.')
    if grade == 'C':
        lines.append('C등급은 낮은 마진으로 빠르게 판매하는 정책을 적용합니다.')
    lines.extend([
        timing,
        f'구매자 표준 수수료 {market_fee + half_network:,} 크레딧(시장 {market_fee:,} + 표준 네트워크 몫 {half_network:,}). 결제 전 시장 수수료 조건과 구매자 지갑의 실제 Maroo 가스를 확인해 주세요.',
        f'구매하려면 시장 에이전트 목록({BOARD})에서 outseop-r4 최신 Agent Card를 찾아 A2A로 SKU와 수량 1개를 보내 주세요. 판매자 EIP-191 서명 checkout_jwt를 받으면 검증하고 구매자 주문에 연결해 결제·정산합니다.',
        '증빙은 체크아웃의 판매 조건, Maroo 원결제 영수증(상품 대금과 해당 시 시장 수수료), 시장 서명 정산 영수증, 실제 인도 기록, 환불 송금 영수증을 각각 확인합니다.',
    ])
    if channel != 'forum':
        lines.append('확인된 초기 문제 또는 판매자 귀책 미인도는 증빙을 접수해 수업 모델이 검토·승인하고, 처리 도구가 한도와 중복을 검증하는 절차입니다.')
    draft = '\n'.join(lines)
    if channel == 'forum' and len(draft) > 2000:
        return blocked('forum_character_limit')
    return {'mode': 'synthetic', 'status': 'draft', 'text': draft, 'valid_until': end,
            'thread_id': forum.get('thread_id') if channel == 'forum' else None,
            'preference_or_conversion_measured': False}
