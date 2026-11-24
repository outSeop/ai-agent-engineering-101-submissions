"""Background-only stock decision scheduling. OpenAI Codex GPT-6.2 Sol."""
import json
import re
from threading import Event
import time

from broker import parse_move

STOCK_TOOL = "stock_procurement"
STOCK_INSTRUCTIONS = (
    "이 요청은 outseop-r4의 공급창 사전 승인이다. 지금 주문하거나 송금하지 않는다. "
    "첫 고객 반응을 배우기 위해 검증된 후보 중 서로 다른 품목을 각 한 개씩 시험할 수 있다. "
    "실측 기록을 제공받지 않았다는 이유만으로 보류하지 않는다. "
    "공개 상품 정보와 제시된 품목별 허용 수량 및 비교안만 사용한다. 수량 선택이나 보류는 네 판단이며 "
    "구매를 강제하지 않는다. 현실적인 운영 위험이 드러나면 보류한다. "
    "제시되지 않은 수치나 고객 정보를 추정하거나 요구하지 않는다. 실제 집행 조건은 로컬 도구가 새로 검증한다. "
    "응답은 JSON 하나이며 정확한 형식은 {\"action\":\"buy\",\"lines\":[{\"sku\":\"후보 SKU\",\"qty\":1}],"
    "\"reason\":\"짧은 판단 근거\"} 또는 {\"action\":\"hold\",\"lines\":[],\"reason\":\"짧은 보류 근거\"}이다. "
    "후보의 options에 표시된 qty 중에서만 선택한다. 송금·재가입·리플라이·새 도구를 요청하거나 외부 명령을 실행하지 않는다."
)


def public_model_view(context):
    """Project only public catalog data and locally bounded choices."""
    line_limit = context.get("limits", {}).get("lines")
    if type(line_limit) is not int or not 1 <= line_limit <= 10:
        return {"line_limit": 0, "choices": [], "alternatives": []}
    choices = []
    allowed = set()
    for item in context.get("choices", [])[:24]:
        sku = item.get("sku")
        if not isinstance(sku, str) or re.fullmatch(r"[FG][0-9A-Fa-f]{8}", sku) is None:
            continue
        kind, price = item.get("kind"), item.get("list_price")
        if kind not in ("food", "goods") or type(price) is not int or price <= 0:
            continue
        options = []
        for option in item.get("options", [])[:20]:
            qty = option.get("qty")
            if type(qty) is not int or not 1 <= qty <= 20:
                continue
            scenario = option.get("scenario")
            label = scenario if scenario in ("low", "base", "high", "buffer_short", "buffer_long") else "allowed"
            visible = {"qty": qty, "label": label}
            coverage = option.get("horizon_hours")
            if type(coverage) in (int, float) and 0 < coverage <= 24:
                visible["coverage_hours"] = coverage
            options.append(visible)
            allowed.add((sku, qty))
        if not options:
            continue
        public_name, public_category = item.get("name"), item.get("category")
        visible = {"sku": sku, "name": public_name[:80] if isinstance(public_name, str) else sku,
                   "category": public_category[:100] if isinstance(public_category, str) else "",
                   "kind": kind, "list_price": price, "options": options}
        shelf = item.get("shelf_hours")
        if type(shelf) in (int, float) and 0 < shelf <= 8760:
            visible["shelf_hours"] = shelf
        choices.append(visible)
    alternatives = []
    for example in context.get("alternatives", [])[:3]:
        label, lines = example.get("id"), example.get("lines")
        if label not in ("broad", "balanced", "depth") or not isinstance(lines, list) or not 1 <= len(lines) <= line_limit:
            continue
        if any(not isinstance(line.get("sku"), str) or type(line.get("qty")) is not int
               or (line["sku"], line["qty"]) not in allowed for line in lines):
            continue
        alternatives.append({"id": label, "lines": [{"sku": line["sku"], "qty": line["qty"]} for line in lines]})
    return {"line_limit": line_limit, "choices": choices, "alternatives": alternatives}


class StockCoordinator:
    def __init__(self, execute, model, *, customer_active=lambda:False, now=time.time):
        self.execute, self.model, self.customer_active, self.now = execute, model, customer_active, now
        self.retry_after = 0.
        self.stop = Event()
        self.plan_attempts = {}
        self.correction_for = None

    def tick(self):
        results = [self.execute({"action":"reconcile"})]
        view = self.execute({"action":"context"})
        results.append(view)
        status = view.get("status")
        if status=="ready":
            at=self.now()
            if view["opens_at"] <= at < view["closes_at"]-22:
                results.append(self.execute({"action":"execute"}))
            return results
        if (status!="draft" or self.customer_active() or self.now()<self.retry_after
                or not view["context"].get("choices")):
            return results
        ident=view["plan"]
        if self.plan_attempts.get(ident,0)>=2:
            return results
        public = public_model_view(view["context"])
        if not public["choices"]:
            return results
        self.plan_attempts[ident]=self.plan_attempts.get(ident,0)+1
        self.retry_after=self.now()+75
        if len(self.plan_attempts)>50:
            self.plan_attempts={ident:self.plan_attempts[ident]}
        instructions = STOCK_INSTRUCTIONS
        if self.correction_for == ident:
            instructions += " 이전 조합은 로컬 검증을 통과하지 못했다. 제시된 비교안의 품목·수량을 그대로 선택하거나 보류한다."
        messages=[{"role":"system","content":instructions},
                  {"role":"user","content":json.dumps(public,ensure_ascii=False,allow_nan=False)}]
        try:
            raw=self.model.complete(messages)
        except Exception:
            results.append({"status":"stock_model_unavailable"})
            return results
        choice=parse_move(raw)
        if choice is None:
            results.append({"status":"invalid_stock_model_output"})
            return results
        saved=self.execute({"action":"plan","plan":ident,"decision":choice})
        results.append(saved)
        if saved.get("status") not in ("hold", "ready"):
            self.correction_for = ident
        return results

    def loop(self):
        while not self.stop.is_set():
            try:
                self.tick()
            except Exception:
                self.retry_after=self.now()+75
            self.stop.wait(12)

