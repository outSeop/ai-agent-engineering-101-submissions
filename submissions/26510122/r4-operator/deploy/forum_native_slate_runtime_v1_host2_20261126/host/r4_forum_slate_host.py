"""Read-only acquisition and selection scope for the native forum slate."""
from copy import deepcopy
from contextlib import closing
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import re
import sqlite3
from tempfile import TemporaryDirectory
from time import time

LEGACY_PIN = "c15424eacded61da86e9f27303b16a705287cecf81c5254a2da5360db3ee9b48"
NAME = "prioritize_forum_candidates"
FACTS = {"sku", "name", "grade", "price", "category", "expiry", "certificate"}
PACK = {"pack_label", "pack_count"}
SOURCE_FILES = {"forge.json", "logic.py", "test.py", "permission.yml"}


def key(row):
    return row["sku"], row["grade"]


def public_post_mix(posts,shop):
    counts={grade:0 for grade in ("A","B","C","unclassified")}
    for row in posts:
        if row.get("author")!=shop or row.get("role")!="shop" or row.get("round")!=4:
            continue
        labels=re.findall(r"·\s*([ABC])등급\s*·",row["text"]) if isinstance(row.get("text"),str) else []
        counts[labels[0] if len(labels)==1 else "unclassified"]+=1
    return {"scope":"own explicitly graded posts in fetched public forum page","count":counts}


def full_options(db, market, legacy, now, *, include_history=False):
    """Project the verified legacy options before its presentation-only slice."""
    if sha256(Path(legacy.__file__).read_bytes()).hexdigest() != LEGACY_PIN:
        raise ValueError("unreviewed legacy eligibility source")
    rates = legacy.PRESETS["aggressive"]
    blocked = legacy.cooldown(db, now, rates)
    if blocked:
        return {"status": blocked}
    posts, offers, replies, spotlight = legacy.available_options(db, market, now, rates)
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
            "spotlight_allowed": bool(spotlight), "items": items, "reply_options": deepcopy(replies)}
    return (source,public_post_mix(posts,legacy.shop.SHOP)) if include_history else source


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
            or result.get("spotlight_allowed") is not source["spotlight_allowed"]):
        raise ValueError("invalid native forum slate")
    source_items={key(item):item for item in source["items"]}
    displayed=set()
    for row in result["items"]:
        pair=key(row)
        fields=FACTS|{"spotlight_eligible"}
        if (pair in displayed or set(row)!=fields|PACK
            or {field:row[field] for field in fields}!=source_items.get(pair)):
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
    return deepcopy(result)


class ScopedExecutor:
    """Bind a native slate to one model selection before the existing publisher."""
    def __init__(self, legacy_execute, acquire, native_context, *, clock=time):
        self.legacy_execute=legacy_execute
        self.acquire=acquire
        self.native_context=native_context
        self.clock=clock
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
            except (OSError,TypeError,KeyError,ValueError):
                return {"status":"native_forum_slate_unavailable"}
            self.scope=(view,source["valid_until"])
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


def bind(official, root, source, pins, readonly_kit, legacy_execute):
    """Shared factory for a manual driver or the optional background executor."""
    original=root/"codex-r4/forum.py"
    if original.resolve(strict=True)!=original or sha256(original.read_bytes()).hexdigest()!=LEGACY_PIN:
        raise ValueError("legacy forum eligibility source changed")
    spec=spec_from_file_location("pinned_forum_eligibility",original)
    module=module_from_spec(spec)
    spec.loader.exec_module(module)
    path=root/"state/r4-benefits/benefits.sqlite3"

    def acquire():
        return acquire_from_legacy(path,module.Market(readonly_kit),module)

    def native(facts):
        return ordinary_context(official,source,pins,facts)

    return ScopedExecutor(legacy_execute,acquire,native)
