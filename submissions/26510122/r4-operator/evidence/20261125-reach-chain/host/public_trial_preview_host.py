"""Official Mind host preview for a pinned public summary and pinned pure planner."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import sys
import time

from class_host_guards import SUMMARY_TOOL, safe_reviewed_result, public_label, valid_count


PLAN = "plan_public_sku_trials"
TTL = 150
PINNED = {
    SUMMARY_TOOL: ("8bd66751466e92515db06a7b58492e038f0bdde0342c8c7036f7c67f03c7ea14",
                   "5f8641150e3cb9dfc27d6d8d78e791eb02d88ad60c39ba94a8416ba22cb50846",
                   "26612cafb34bed41d4e693bbb12ac4530bf71ecf39c441ee55d6e44206b84b84"),
    PLAN: ("c15e2998e8afcf1d0dbafb38af330c3b41ca1805a6a93f090cc5d55540d4dcda",
           "77449caeecd41b4a26e249a17b38946f7f4e62f4bc451d2956ec60951bf3f393",
           "8fbae23e9939946eeec58363d8062d68f989f344fd6f9c836ebe147c5f2a9099"),
}


class NoWallet:
    def grant(self, name, permission, timeout):
        if permission.get("wallet") or permission.get("identity"):
            raise PermissionError("preview has no wallet or identity capability")
        return None


def bundle(source, tool):
    files = dict(zip(("permission.yml", "logic.py", "test.py"), PINNED[tool]))
    directory = source / tool
    records = {p: (directory / p).read_bytes() for p in (*files, "forge.json")}
    manifest = json.loads(records["forge.json"])
    if ((manifest.get("tool"), manifest.get("version"), manifest.get("sha256")) != (tool, 2, files)
        or any(sha256(records[p]).hexdigest() != digest for p, digest in files.items())):
        raise ValueError("tool does not match reviewed v2 bytes")
    return records


class Preview:
    tools = {SUMMARY_TOOL:{}, PLAN:{}}

    def __init__(self, execute, monotonic=time.monotonic, now=time.time):
        self.execute = execute
        self.monotonic = monotonic
        self.now = now
        self.observation = None
        self.result = {"status":"no_preview"}

    def listing(self):
        return (
            "- summarize_public_settlements: {} or {\"window_seconds\":3600}; hosts a verified public observation.\n"
            "- plan_public_sku_trials: exactly {\"observation_ref\":\"<ref just returned>\",\"max_trials\":3}. "
            "Uses that observation only, no buying or held-stock exclusions."
        )

    def forge(self, args):
        return {"status":"disabled"}

    def read(self, name):
        return {"status":"disabled"}

    def call(self, name, args):
        if not isinstance(args, dict):
            return {"status":"invalid_arguments"}
        if name == SUMMARY_TOOL:
            if not set(args) <= {"window_seconds"}:
                return {"status":"invalid_arguments"}
            window = args.get("window_seconds",3600)
            if type(window) is not int or not 60 <= window <= 86400:
                return {"status":"invalid_arguments"}
            self.observation = None
            safe = safe_reviewed_result(name, self.execute(name,args))
            result = safe.get("result",{})
            if safe.get("ok") is not True or "error" in result:
                return {"status":"summary_unavailable"}
            age = self.now() - result["requested_time"]["end"]
            if not -5 <= age <= TTL:
                return {"status":"summary_stale"}
            reference = secrets.token_urlsafe(24)
            self.observation = (reference,self.monotonic()+TTL,deepcopy(result))
            return {"status":"observation_ready","observation_ref":reference,
                    "coverage":result["coverage"],"requested_time":result["requested_time"],
                    "sku_count":len(result["by_sku"]), "category_count":len(result["by_category"])}
        if name != PLAN or set(args) != {"observation_ref","max_trials"}:
            return {"status":"invalid_arguments"}
        reference, maximum = args["observation_ref"],args["max_trials"]
        if not isinstance(reference,str) or type(maximum) is not int or not 1 <= maximum <= 8:
            return {"status":"invalid_arguments"}
        if self.observation is None:
            return {"status":"observation_unavailable"}
        expected, expiry, summary = self.observation
        if (reference != expected or self.monotonic() >= expiry
                or self.now() - summary["requested_time"]["end"] > TTL):
            return {"status":"observation_unavailable"}
        self.observation = None
        raw = self.execute(PLAN,{"summary":deepcopy(summary),"existing_skus":[]})
        self.result = self.project_plan(raw,summary,maximum)
        return deepcopy(self.result)

    @staticmethod
    def project_plan(envelope,summary,maximum):
        unavailable = {"status":"preview_unavailable"}
        if not isinstance(envelope,dict) or set(envelope) != {"ok","result"} or envelope["ok"] is not True:
            return unavailable
        result = envelope["result"]
        fields = {"mode","status","coverage","provisional","requested_time","sample_time","candidates",
                  "sealed_count","unclassified_count","basis","limits","before_purchase"}
        if (not isinstance(result,dict) or set(result) != fields or result["status"] != "planning_only"
            or any(result[k]!=summary[k] for k in ("mode","coverage","requested_time","sample_time",
                                                    "sealed_count","unclassified_count"))
            or type(result["provisional"]) is not bool or not isinstance(result["candidates"],list)):
            return unavailable
        observed = {(r["sku"],r["category"],r["count"]) for r in summary["by_sku"]}
        for row in result["candidates"]:
            if (not isinstance(row,dict) or set(row)!={"sku","category","observed_count","planned_units"}
                or not public_label(row["sku"]) or not public_label(row["category"])
                or not valid_count(row["observed_count"]) or type(row["planned_units"]) is not int
                or row["planned_units"] != 1 or (row["sku"],row["category"],row["observed_count"]) not in observed):
                return unavailable
        return {"status":"planning_only","coverage":result["coverage"],"provisional":result["provisional"],
                "inventory_exclusions_applied":False,"candidates":result["candidates"][:maximum]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operator",type=Path,required=True)
    parser.add_argument("--session",type=Path,required=True)
    args = parser.parse_args()
    op = args.operator.resolve(strict=True)
    runtime = (op / "runtime").resolve(strict=True)
    session = args.session.resolve()
    if session.parent != runtime or not session.name.startswith("public-trial-preview-") or session.exists():
        parser.error("a new dedicated preview session is required")
    os.umask(0o077)
    origin = runtime / "class-rebuild-reach-20261125" / "tools"
    prepared = {tool:bundle(origin,tool) for tool in PINNED}
    session.mkdir(mode=0o700)
    (session / "logs").mkdir()
    for tool, files in prepared.items():
        folder = session / "tools" / tool
        folder.mkdir(parents=True)
        for filename,data in files.items():
            (folder / filename).write_bytes(data)
    for key in ("AGENT_LLM_BASE","AGENT_LLM_MODEL","AGENT_LLM_KEY"):
        os.environ.pop(key,None)
    sys.path.insert(0,str(op / "kit"))
    import agent_kit as official
    official.mk.LOG_FILE = session/"logs"/"agent-kit.log"
    market = "https://market.ourolabs.ai"
    ctx = {"name":"outseop-r4","market":market,"tokens":{},"addresses":{},"signer":NoWallet()}
    with (session/"logs"/"console-private.log").open("x") as stream, redirect_stdout(stream), redirect_stderr(stream):
        toolbox = official.Toolbox(session,ctx)
        for tool in PINNED:
            perm = toolbox.tools[tool]["perm"]
            if (any(perm.get(k) for k in ("wallet","identity","exec","write"))
                or set(perm.get("network") or []) != ({"market.ourolabs.ai"} if tool==SUMMARY_TOOL else set())):
                raise ValueError("unexpected preview permission")

        def execute(tool, data):
            bundle(session / "tools",tool)
            return toolbox.run(tool,"call",data)

        gate = Preview(execute)
        agent = {"llm":{"base":"market"},"max_steps":5,"run_minutes":3,
                 "persona":"공개 관측만 사용하는 상품 검토 담당자",
                 "goal":"공개 정산을 조회하고 반환된 관측 참조로 최대 3개 시범 후보를 미리 보라. "
                        "기존 재고 제외나 매입은 이 실행에서 하지 않는다. 이후 sleep."}
        token = (op.parent/"round-4"/".kit"/"worker-token").read_text().strip()
        model = official.Model(agent,market,{"tokens":{"shop":token}})
        official.Mind(session,agent,model,gate,ctx,[]).run_once([])
    report = {"provider":"market-class","formal_entrypoint":"official Mind.run_once",
              "copied_forges_not_new_authorship":True,"preview":gate.result}
    (session/"summary.json").write_text(json.dumps(report,ensure_ascii=False)+"\n")
    print(json.dumps(report,ensure_ascii=False))


if __name__ == "__main__":
    main()

