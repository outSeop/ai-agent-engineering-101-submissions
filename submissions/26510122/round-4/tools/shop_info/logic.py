"""Read-only public-format information for the class model. OpenAI Codex GPT-6.2 Sol."""
import re

import httpx


MARKET = "https://market.ourolabs.ai"
SHOP = "outseop-r4"
POLICY = "실제 처리 지연 때 발급한 대기권은 120초 동안 유효하며 이번 거래 기준가의 1% 할인입니다. 정상 정산 뒤 기준가의 1%가 7일 마일리지로 적립됩니다. 확인된 인도 후 48시간 내 초기 문제는 운영자가 검토합니다. 구매·대기·잔액·환불 절차는 고객이 공개 상점으로 직접 문의하면 안내합니다."


def run(args, kit):
    result = {"reply": "현재 재고 조회를 사용할 수 없습니다. " + POLICY, "state": "completed"}
    if kit.name != SHOP or kit.market != MARKET:
        return result
    try:
        response = httpx.get(MARKET + "/api/inventory",
                             headers={"authorization": "Bearer " + kit.token("shop")},
                             timeout=4, trust_env=False)
        response.raise_for_status()
        info = response.json()
        if info.get("round") != 4 or info.get("wallet", "").lower() != kit.address("shop").lower():
            return result
        by_sku = {}
        for unit in info.get("units", []):
            sku, grade = unit.get("sku"), unit.get("grade")
            if isinstance(sku, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", sku) and grade in ("A", "B", "C"):
                by_sku.setdefault(sku, set()).add(grade)
        known = [f"{sku} ({'/'.join(sorted(grades))})" for sku, grades in sorted(by_sku.items())[:25]]
        inventory = ("시장 재고 목록 확인 결과 " + ", ".join(known) + "입니다. 구매 가능 여부는 상점에서 확인해 주세요."
                     if known else "시장 재고 목록에서 확인 가능한 상품이 없습니다.")
        return {"reply": inventory + " " + POLICY, "state": "completed"}
    except (httpx.HTTPError, OSError, PermissionError, KeyError, ValueError, AttributeError, TypeError):
        return result

