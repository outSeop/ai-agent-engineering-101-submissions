"""Read-only acquisition and selection scope for the native forum slate."""
from copy import deepcopy
from contextlib import closing
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
from tempfile import TemporaryDirectory
from time import time

LEGACY_PIN = "c15424eacded61da86e9f27303b16a705287cecf81c5254a2da5360db3ee9b48"
NAME = "prioritize_forum_candidates"
FACTS = {"sku", "name", "grade", "price", "category", "expiry", "certificate"}
PACK = {"pack_label", "pack_count"}
SOURCE_FILES = {"forge.json", "logic.py", "test.py", "permission.yml"}


def key(row):
    return row["sku"], row["grade"]


def own_spotlight_history(db, shop, now):
    """Read confirmed, attributable spotlights from the local publication journal."""
    history = []
    rows = db.execute(
        "SELECT sku,content,created FROM forum_publication "
        "WHERE shop=? AND round=4 AND thread IS NULL AND status='posted' "
        "AND post IS NOT NULL AND post>0 AND created<=? "
        "ORDER BY created DESC, post DESC",
        (shop, now),
    )
    for sku, content, created in rows:
        if not isinstance(content, str):
            continue
        parts = content.split(chr(10)*2, 2)
        if len(parts) < 2:
            continue
        label = re.search(r" \(" + re.escape(sku) + r"\) · ([ABC])등급 · 상품가 [\d,]+ 크레딧$", parts[1])
        if label is None or not 0 < created <= now:
            continue
        history.append({"grade": label[1], "category": None, "at": int(created)})
        if len(history) == 512:
            break
    return history


def full_options(db, market, legacy, now, *, include_history=False):
    """Project the verified legacy options before its presentation-only slice."""
    if sha256(Path(legacy.__file__).read_bytes()).hexdigest() != LEGACY_PIN:
        raise ValueError("unreviewed legacy eligibility source")
    rates = legacy.PRESETS["aggressive"]
    blocked = legacy.cooldown(db, now, rates)
    if blocked:
        return {"status": blocked}
    _, offers, replies, spotlight = legacy.available_options(db, market, now, rates)
    reply_items = {key(pair) for reply in replies for pair in reply["eligible"]}
    items = []
    for row in offers:
        can_spotlight = bool(spotlight and not db.execute(
            "SELECT id FROM forum_publication WHERE fingerprint=? AND status!='declined'",
            (legacy.offer_fingerprint(row, None),),
        ).fetchone())
        if can_spotlight or key(row) in reply_items:
            items.append({**{name: row[name] for name in FACTS}, "spotlight_eligible": can_spotlight})
    source={"schema": "outseop-r4.forum-candidates.v1", "observed_at": int(now), "valid_until": int(now)+90,
            "spotlight_allowed": bool(spotlight), "own_spotlight_history": own_spotlight_history(db, legacy.shop.SHOP, now), "items": items, "reply_options": deepcopy(replies)}
    history=source["own_spotlight_history"]
    mix={"scope":"confirmed owned R4 spotlight journal, at most 512 graded rows",
         "count":{grade:sum(row["grade"]==grade for row in history) for grade in "ABC"}}
    return (source,mix) if include_history else source


def acquire_from_legacy(path, market, legacy, *, clock=time):
    """Read the existing forum ledger without schema setup or writes."""
    path=Path(path)
    if path.resolve(strict=True)!=path:
        raise ValueError("forum ledger path changed")
    with closing(sqlite3.connect(path.as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
        db.row_factory=sqlite3.Row
        identity=db.execute("SELECT shop,wallet FROM identity WHERE singleton=1").fetchone()
        if identity is None or tuple(identity)!=(legacy.shop.SHOP,market.wallet):
            raise ValueError("forum ledger identity changed")
        return full_options(db,market,legacy,clock(),include_history=True)


def validate_scope(source, result):
    if (not isinstance(result,dict) or result.get("status")!="options"
            or not isinstance(result.get("items"),list) or len(result["items"])>16
            or not isinstance(result.get("reply_options"),list)
            or type(result.get("spotlight_allowed")) is not bool
            or result["spotlight_allowed"] and not source["spotlight_allowed"]):
        raise ValueError("invalid native forum slate")
    policy=result.get("selection_policy")
    if not isinstance(policy,dict) or set(policy)!={"consecutive_c_guard"} or type(policy["consecutive_c_guard"]) is not bool:
        raise ValueError("invalid native forum selection policy")
    source_items={key(item):item for item in source["items"]}
    displayed=set()
    for row in result["items"]:
        pair=key(row)
        original = source_items.get(pair)
        if (pair in displayed or set(row)!=FACTS|PACK|{"spotlight_eligible"} or original is None
            or {field:row[field] for field in FACTS}!={field:original[field] for field in FACTS}
            or type(row["spotlight_eligible"]) is not bool
            or row["spotlight_eligible"] and (not original["spotlight_eligible"] or not result["spotlight_allowed"])):
            raise ValueError("unproven native forum item")
        displayed.add(pair)
    source_threads={row["thread"]:row for row in source["reply_options"]}
    threads=set()
    for row in result["reply_options"]:
        thread=row["thread"]
        if thread in threads or thread not in source_threads or set(row)!={"thread","request","eligible"}:
            raise ValueError("unproven native forum thread")
        original=source_threads[thread]
        if not isinstance(row["eligible"],list) or row["request"]!=original["request"]:
            raise ValueError("unproven native forum response")
        possible={key(pair) for pair in original["eligible"]}&displayed
        if not all(set(pair)=={"sku","grade"} and key(pair) in possible for pair in row["eligible"]):
            raise ValueError("unproven native reply choice")
        threads.add(thread)
    if len(json.dumps(result,ensure_ascii=False,separators=(",",":")))>5500:
        raise ValueError("native forum slate exceeds model layout")
    scoped=deepcopy(result)
    if policy["consecutive_c_guard"]:
        for row in scoped["items"]:
            if row["grade"]=="C":
                row["spotlight_eligible"]=False
    return scoped


class ScopedExecutor:
    """Bind a native slate to one model selection before the existing publisher."""
    def __init__(self, legacy_execute, acquire, native_context, *, clock=time, audit=None):
        self.legacy_execute=legacy_execute
        self.acquire=acquire
        self.native_context=native_context
        self.clock=clock
        self.audit=audit
        self.scope=None

    def __call__(self, request):
        if request=={"action":"reconcile"}:
            self.scope=None
            return self.legacy_execute(request)
        if request=={"action":"context"}:
            self.scope=None
            try:
                value=self.acquire()
                source,history=value if isinstance(value,tuple) else (value,None)
                if "schema" not in source:
                    return source
                view=validate_scope(source,self.native_context(source))
                if history is not None:
                    view["recent_public_post_mix"]=history
                if self.clock()>=source["valid_until"]:
                    raise ValueError("native forum slate expired")
            except (OSError,sqlite3.Error,TypeError,KeyError,ValueError):
                return {"status":"native_forum_slate_unavailable"}
            self.scope=(view,source["valid_until"])
            if self.audit is not None:
                self.audit("context",{
                    "visible_rows":len(view["items"]),
                    "eligible_by_grade":{grade:sum(row["grade"]==grade and row["spotlight_eligible"]
                                                   for row in view["items"]) for grade in "ABC"},
                    "small_ab":sum(row["grade"] in "AB" and row["pack_label"]=="explicit_small"
                                   and row["spotlight_eligible"] for row in view["items"]),
                    "history_size":len(source["own_spotlight_history"]),
                    "selection_policy":view.get("selection_policy",{}),
                })
            return deepcopy(view)
        if (not isinstance(request,dict) or set(request)!={"action","decision"}
                or request.get("action")!="publish" or self.scope is None):
            return {"status":"choice_not_eligible"}
        view,expiry=self.scope
        self.scope=None
        decision=request.get("decision")
        if self.clock()>=expiry or not isinstance(decision,dict):
            return {"status":"choice_not_eligible"}
        selected=(decision.get("sku"),decision.get("grade"))
        if decision.get("action")=="spotlight" and set(decision)=={"action","sku","grade"}:
            eligible=any(key(row)==selected and row["spotlight_eligible"] for row in view["items"])
        elif decision.get("action")=="reply" and set(decision)=={"action","sku","grade","thread"}:
            eligible=any(decision.get("thread")==row["thread"] and any(key(p)==selected for p in row["eligible"])
                         for row in view["reply_options"])
        else:
            eligible=False
        return self.legacy_execute(request) if eligible else {"status":"choice_not_eligible"}


class NoWallet:
    def grant(self, name, permission, timeout):
        if (name!=NAME or any(permission.get(k) for k in ("wallet","identity","network","write","exec","handles"))
                or permission.get("pay_limit",0)!=0):
            raise ValueError("unexpected forum slate permissions")
        return None


def ordinary_context(official, source, pins, facts):
    files={name:(source/name).read_bytes() for name in SOURCE_FILES}
    if {name:sha256(value).hexdigest() for name,value in files.items()}!=pins:
        raise ValueError("native forum slate source changed")
    manifest=json.loads(files["forge.json"])
    if manifest.get("tool")!=NAME or manifest.get("sha256")!={k:v for k,v in pins.items() if k!="forge.json"}:
        raise ValueError("native forum slate manifest mismatch")
    with TemporaryDirectory(prefix="r4-genuine-forum-slate-") as folder:
        root=Path(folder)
        target=root/"tools"/NAME
        target.mkdir(mode=0o700,parents=True)
        for name,raw in files.items():
            (target/name).write_bytes(raw)
        inputs=root/"host_inputs"
        inputs.mkdir(mode=0o700)
        (inputs/"forum_candidates.json").write_text(json.dumps(facts,ensure_ascii=False,separators=(",",":")))
        ctx={"name":"outseop-r4","market":"https://market.ourolabs.ai","tokens":{},"addresses":{},"signer":NoWallet()}
        response=official.Toolbox(root,ctx).run(NAME,"call",{"mode":"context"})
        if not response.get("ok") or "result" not in response:
            raise ValueError("ordinary native forum slate unavailable")
        return response["result"]


def bind_policy_path(root, policy):
    directory=root/"codex-r4"
    path=directory/"launch-price-policy.json"
    path_info=path.lstat()
    if (directory.resolve(strict=True)!=directory or path.resolve(strict=True)!=path
            or not stat.S_ISREG(path_info.st_mode) or path_info.st_uid!=os.getuid()
            or path_info.st_nlink!=1 or path_info.st_mode & 0o022):
        raise ValueError("untrusted launch price policy path")
    policy.POLICY_PATH=path


def bind(official, root, source, pins, readonly_kit, legacy_execute, *, audit=None):
    """Shared factory for a manual driver or the optional background executor."""
    original=root/"codex-r4/forum.py"
    if original.resolve(strict=True)!=original or sha256(original.read_bytes()).hexdigest()!=LEGACY_PIN:
        raise ValueError("legacy forum eligibility source changed")
    spec=spec_from_file_location("pinned_forum_eligibility",original)
    module=module_from_spec(spec)
    spec.loader.exec_module(module)
    path=root/"state/r4-benefits/benefits.sqlite3"

    def acquire():
        bind_policy_path(root,module.shop.price_policy)
        return acquire_from_legacy(path,module.Market(readonly_kit),module)

    def native(facts):
        if audit is not None:
            audit("native_input",deepcopy(facts))
        result=ordinary_context(official,source,pins,facts)
        if audit is not None:
            audit("native_result",deepcopy(result))
        return result

    return ScopedExecutor(legacy_execute,acquire,native,audit=audit)
