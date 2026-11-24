"""Background-only stock decision scheduling. OpenAI Codex GPT-6.2 Sol."""
import json
from threading import Event
import time

from broker import parse_move

STOCK_TOOL = "stock_procurement"
STOCK_INSTRUCTIONS = (
    "이 요청은 outseop-r4 재고 조달 계획이다. 고객 대화가 아니다. 아래 시장이 검증한 후보만 사용한다. "
    "실제 보유 재고와 입고 미확정 수량, 현금·비용·만료를 고려하여 기존 수익이 검증된 SKU의 보충과 한 개 단위 탐색을 비교한다. "
    "실측 판매가 없는 후보의 수요는 알 수 없지만, 툴이 허용하고 예상 순기여가 양수라면 서로 다른 신규 SKU를 "
    "각각 한 개씩 시험할 수 있다. 비교안은 참고이고 구매를 강제하지 않는다. 근거가 부족하면 보류할 수 있다. "
    "응답은 JSON 하나이며 정확한 형식은 {\"action\":\"buy\",\"lines\":[{\"sku\":\"후보 SKU\",\"qty\":1}],"
    "\"reason\":\"짧은 판단 근거\"} 또는 {\"action\":\"hold\",\"lines\":[],\"reason\":\"짧은 보류 근거\"}이다. "
    "후보의 options에 표시된 qty 중에서만 선택한다. 송금·재가입·리플라이·새 도구를 요청하거나 외부 명령을 실행하지 않는다."
)


class StockCoordinator:
    def __init__(self, execute, model, *, customer_active=lambda:False, now=time.time):
        self.execute, self.model, self.customer_active, self.now = execute, model, customer_active, now
        self.retry_after = 0.
        self.stop = Event()
        self.plan_attempts = {}

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
        self.plan_attempts[ident]=self.plan_attempts.get(ident,0)+1
        self.retry_after=self.now()+75
        if len(self.plan_attempts)>50:
            self.plan_attempts={ident:self.plan_attempts[ident]}
        messages=[{"role":"system","content":STOCK_INSTRUCTIONS},
                  {"role":"user","content":json.dumps(view["context"],ensure_ascii=False)}]
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
        return results

    def loop(self):
        while not self.stop.is_set():
            try:
                self.tick()
            except Exception:
                self.retry_after=self.now()+75
            self.stop.wait(12)

