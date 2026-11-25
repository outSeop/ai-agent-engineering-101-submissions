"""One official Mind.run_once on reviewed legacy forum v5. Dry unless explicitly authorized."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys


TOOL = "forum_marketing"
PIN = {
    "permission.yml":"da96a18919a24399b5b8eb549367f62a4bbcf4eed2015681898f95e160da08c1",
    "logic.py":"c15424eacded61da86e9f27303b16a705287cecf81c5254a2da5360db3ee9b48",
    "test.py":"22b2c0890e24a3b1871b7b95d29ba14276678ab36bdec7b11a3cfabc3d7c8c3b",
}
STATES = {"options","posted","unknown","declined","cooldown","superseded","hold",
          "unresolved_publish","invalid_choice","authoritative_check_unavailable",
          "stock_changed","daily_limit","spotlight_cooldown","reconciled","none"}


class NoWallet:
    def grant(self, name, permission, timeout):
        if permission.get("wallet"):
            raise PermissionError("no wallet operations")
        return None


def verify_source(root):
    directory = root / "tools" / TOOL
    manifest = json.loads((directory / "forge.json").read_text())
    if (manifest.get("tool"), manifest.get("version"), manifest.get("sha256")) != (TOOL,5,PIN):
        raise ValueError("reviewed forum manifest does not match")
    if any(sha256((directory / key).read_bytes()).hexdigest() != value for key,value in PIN.items()):
        raise ValueError("reviewed forum source changed")
    return directory


class Canary:
    """Model-facing call cage. The original forged tool remains the only renderer."""
    tools = {TOOL:{}}

    def __init__(self, execute, allow_post=False):
        self.execute = execute
        self.allow_post = allow_post
        self.eligible = set()
        self.attempted = False
        self.result = {"status":"no_selection"}

    def listing(self):
        return (
            "- forum_marketing: call with exactly {\"action\":\"context\"} for eligible public food. "
            "If you choose one item, call exactly {\"action\":\"publish\",\"sku\":\"G01234567\",\"grade\":\"C\"}; "
            "use the actual SKU and grade from context. Then sleep."
        )

    def forge(self, args):
        return {"status":"disabled"}

    def read(self, name):
        return {"status":"disabled"}

    @staticmethod
    def result_only(envelope):
        if not isinstance(envelope,dict) or envelope.get("ok") is not True or not isinstance(envelope.get("result"),dict):
            return {"status":"authoritative_check_unavailable"}
        return envelope["result"]

    def call(self, name, args):
        if name != TOOL or not isinstance(args,dict):
            return {"status":"invalid_action"}
        if args == {"action":"context"}:
            result = self.result_only(self.execute(args))
            self.eligible.clear()
            if result.get("status") != "options":
                status = result.get("status")
                return {"status":status if status in STATES else "not_available"}
            menu = []
            for row in result.get("items",[]):
                sku, grade = row.get("sku"), row.get("grade")
                product, category, price = row.get("name"), row.get("category"), row.get("price")
                if (not isinstance(sku,str) or not re.fullmatch(r"[FG][a-fA-F0-9]{8}",sku)
                    or grade not in ("A","B","C") or not isinstance(product,str) or not product.isprintable()
                    or not isinstance(category,str) or not category.startswith("식품")
                    or type(price) is not int or price < 1):
                    continue
                menu.append({"sku":sku,"name":product[:120],"grade":grade,"price":price,
                             "category":category.split(">")[0]})
            if result.get("spotlight_allowed") is not True:
                menu = []
            menu = menu[:8]
            self.eligible = {(r["sku"],r["grade"]) for r in menu}
            return {"status":"options","items":menu}
        if (set(args) != {"action","sku","grade"} or args["action"] != "publish"
            or not isinstance(args["sku"],str) or not isinstance(args["grade"],str)):
            return {"status":"invalid_action"}
        if self.attempted or (args["sku"],args["grade"]) not in self.eligible:
            return {"status":"choice_not_eligible"}
        self.attempted = True
        self.result = {"status":"dry_selection","sku":args["sku"],"grade":args["grade"]}
        if self.allow_post:
            result = self.result_only(self.execute({"action":"publish","decision":{
                "action":"spotlight","sku":args["sku"],"grade":args["grade"],
            }}))
            self.result["status"] = result.get("status") if result.get("status") in STATES else "not_available"
            post = result.get("post")
            if self.result["status"] == "posted" and type(post) is int and post > 0:
                self.result["post"] = post
        return self.result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operator",type=Path,required=True)
    parser.add_argument("--session",type=Path,required=True)
    parser.add_argument("--allow-one-post",action="store_true")
    args = parser.parse_args()
    op = args.operator.resolve(strict=True)
    runtime = (op / "runtime").resolve(strict=True)
    session = args.session.resolve()
    if session.parent != runtime or not session.name.startswith("forum-mind-canary-") or session.exists():
        parser.error("expected a fresh canary session directly under operator/runtime")
    os.umask(0o077)
    session.mkdir(mode=0o700)
    (session / "logs").mkdir(mode=0o700)
    production = op.parent / "round-4"
    sys.path[:0] = [str(op / "kit"),str(production / "codex-r4")]
    import agent_kit as official
    import worker_bootstrap

    official.mk.LOG_FILE = session / "logs" / "agent-kit.log"
    for key in ("AGENT_LLM_BASE","AGENT_LLM_MODEL","AGENT_LLM_KEY"):
        os.environ.pop(key,None)
    try:
        with (session / "logs" / "console-private.log").open("x") as private, redirect_stdout(private), redirect_stderr(private):
            verify_source(production)
            registered = worker_bootstrap.validated_kit(production)
            token = registered.token("shop")
            tool_ctx = {"name":registered.name,"market":registered.market,"shop_url":registered.shop_url,
                        "tokens":{"shop":token},"addresses":{"shop":registered.address("shop")},
                        "signer":NoWallet()}
            stock = official.Toolbox(production,tool_ctx)

            def execute(request):
                verify_source(production)
                return stock.run(TOOL,"call",request,d=production / "tools" / TOOL)

            gate = Canary(execute,args.allow_one_post)
            agent = {"llm":{"base":"market"},"max_steps":5,"run_minutes":3,
                     "persona":"outseop-r4의 정확한 홍보 담당자",
                     "goal":"기존 검증 도구로 공개 식품을 조회하고 게시할 실제 품목 하나를 선택한다. "
                            "C등급이나 다른 품목이 적합한지 공개 조건으로 판단한다. "
                            "포럼에 직접 쓸 글을 만들 필요가 없다. 도구의 지정된 인자를 그대로 사용한다. "
                            "게시할 것이 없으면 sleep. 다른 도구를 만들거나 수정하지 않는다."}
            model = official.Model(agent,registered.market,{"tokens":{"shop":token}})
            model_ctx = {"name":registered.name,"market":registered.market,"shop_url":None,
                         "tokens":{},"addresses":{}}
            mind = official.Mind(session,agent,model,gate,model_ctx,[])
            mind.run_once([])
        summary = {"formal_entrypoint":"official Mind.run_once","tool_authorship":"reused external Codex implementation",
                   "tool_version":5,"live_post_enabled":args.allow_one_post,"result":gate.result}
        (session / "summary.json").write_text(json.dumps(summary,ensure_ascii=False)+"\n")
        print(json.dumps(summary,ensure_ascii=False))
    except Exception as error:
        print(json.dumps({"status":"canary_failed","error_type":type(error).__name__}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

