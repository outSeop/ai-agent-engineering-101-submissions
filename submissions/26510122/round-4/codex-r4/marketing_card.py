"""Render shop card content only from verified public inventory offers."""
from datetime import datetime
from zoneinfo import ZoneInfo

from forum import BENEFITS, WARRANTY, public_text


def build_card(offers, *, now=None):
    display=[]
    for row in offers:
        price=row.get("price") or row.get("preferred_price") or row.get("reference_price")
        if (row.get("available", True) is not True or row.get("grade") not in ("A","B","C")
                or type(price) is not int or price<=0 or not isinstance(row.get("sku"),str)):
            continue
        name=public_text(row.get("name"),67)
        if name:
            display.append(f"{name} ({row['sku']}) · {row['grade']}등급 · {price:,} 크레딧")
        if len(display)>=6:
            break
    seoul=ZoneInfo("Asia/Seoul")
    stamp=datetime.fromtimestamp(now,seoul) if now is not None else datetime.now(seoul)
    title=stamp.strftime("%Y-%m-%d %H:%M KST 확인 재고")
    verified=title+chr(10)+chr(10).join(display) if display else "현재 공개할 확인 상품이 없습니다."
    intro="outseop-r4에 처음 연락할 때 원하는 상품명이나 SKU와 필요한 조건을 알려 주세요. 재방문 시 비공개 권리코드로 누적 혜택을 확인할 수 있습니다."
    caveat="표시는 조사 시점 기준입니다. 구매 전 A2A에서 재고·현재 등급·가격과 별도 시장 수수료·가스 조건을 확인해 주세요."
    return {"description":"\n\n".join((intro,verified,caveat)),
            "skills":[{"id":"a2a-checkout","name":"상품·등급 확인과 구매",
                       "description":"원하는 상품명 또는 SKU와 가격·등급 조건을 A2A에 보내세요. 구매를 결정하면 서명된 결제권을 받을 수 있습니다.",
                       "tags":["inventory","checkout"],"examples":["키친타올 걸이의 현재 등급과 가격을 알려주세요."]},
                      {"id":"repeat-benefits","name":"대기할인 및 재방문 마일리지",
                       "description":BENEFITS,"tags":["mileage","wait-voucher"],
                       "examples":["보유 마일리지와 대기할인을 함께 쓸 수 있나요?"]},
                      {"id":"refund-review","name":"증빙 기반 환불 검토","description":WARRANTY,
                       "tags":["warranty","refund"],"examples":["원결제 증빙으로 환불 검토를 요청합니다."]}]}

