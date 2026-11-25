"""Operator-only ordinary SDK notice preview and class-model, one-attempt dispatch."""
import argparse
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from tempfile import mkstemp

import httpx
from check_notice_public_card_host import MARKET, observe
from first_purchase_bonus_sdk_host import checked_file
from smoke_notice_ordinary_sdk_preview import NoWallet

NAME="first_purchase_bonus_notice"
VERSION=5
FILES={"logic.py","test.py","permission.yml","forge.json"}
STATES={"preview","posted","declined","unknown","blocked","unavailable"}
POLICY_NAME="first-purchase-bonus-policy.json"
APPROVAL_NAME="first-purchase-bonus-notice-approval.json"


def digest(raw):
    return sha256(raw).hexdigest()


def verified_source(source,pin):
    if source.resolve(strict=True)!=source:
        raise ValueError("notice source path is not canonical")
    files={name:checked_file(source/name) for name in FILES}
    doc=json.loads(files["forge.json"])
    if (digest(files["forge.json"])!=pin or doc.get("tool")!=NAME or doc.get("version")!=VERSION
            or doc.get("sha256")!={name:digest(files[name]) for name in FILES-{"forge.json"}}):
        raise ValueError("reviewed native notice bundle changed")
    return {name:digest(raw) for name,raw in files.items()}


def encoded(values):
    return (json.dumps(values,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()


def create_file(path,raw):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,"wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def update_file(path,prior,raw):
    if checked_file(path,4096)!=prior:
        raise ValueError("notice approval changed outside the operator")
    fd,tmp=mkstemp(prefix=".notice-approval-",dir=path.parent)
    try:
        with os.fdopen(fd,"wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if checked_file(path,4096)!=prior:
            raise ValueError("notice approval changed outside the operator")
        os.replace(tmp,path)
    finally:
        Path(tmp).unlink(missing_ok=True)


@contextmanager
def approval(path,facts):
    if path.parent.resolve(strict=True)!=path.parent:
        raise ValueError("notice state directory is not canonical")
    current=encoded(facts)
    create_file(path,current)
    def refresh(updated):
        nonlocal current
        raw=encoded(updated)
        update_file(path,current,raw)
        current=raw
    try:
        yield refresh
    finally:
        try:
            if checked_file(path,4096)==current:
                path.unlink()
        except FileNotFoundError:
            pass


def envelope_only(response):
    result=response.get("result") if isinstance(response,dict) and response.get("ok") is True else None
    if not isinstance(result,dict) or result.get("status") not in STATES:
        return {"status":"unavailable"}
    if result["status"]=="preview":
        if (set(result)!={"status","lane","fingerprint","text"} or not isinstance(result["text"],str)
                or not 1<=len(result["text"])<=2000 or not isinstance(result["fingerprint"],str)
                or not 1<=len(result["fingerprint"])<=256):
            return {"status":"unavailable"}
    return result


class NoticeGate:
    tools={NAME:{}}

    def __init__(self,public,dispatch):
        self.context={"genuine_notice_preview":public}
        self.dispatch=dispatch
        self.result={"status":"hold"}
        self.attempted=False

    def listing(self):
        return (
            '- first_purchase_bonus_notice: exact {"mode":"preview"} reads the current verified notice. '
            'If the notice is appropriate, call exactly {"mode":"dispatch"} once. No other keys.'
        )

    def forge(self,args):
        return {"status":"disabled"}

    def read(self,name):
        return {"status":"disabled"}

    def call(self,name,args):
        if name!=NAME:
            return {"status":"disabled"}
        if args=={"mode":"preview"}:
            return self.context["genuine_notice_preview"]
        if args!={"mode":"dispatch"} or self.attempted:
            return {"status":"disabled"}
        self.attempted=True
        self.result={"status":"dispatch_unconfirmed"}
        self.result=self.dispatch()
        return {"status":self.result["status"]}


def public_receipt(root,read,fingerprint,text):
    path=root/"state/r4-benefits/benefits.sqlite3"
    with sqlite3.connect(path.as_uri()+"?mode=ro",uri=True,timeout=2) as db:
        row=db.execute("SELECT post FROM forum_publication WHERE fingerprint=? AND status='posted' "
                       "AND shop=? AND round=4 AND thread IS NULL AND content=?",
                       (fingerprint,"outseop-r4",text)).fetchone()
    if row is None or type(row[0]) is not int or row[0]<1:
        return None
    post=row[0]
    values=read(MARKET+"/api/forum",params={"since":post-1,"limit":20})
    matching=[item for item in values if isinstance(item,dict) and item.get("id")==post
              and item.get("author")=="outseop-r4" and item.get("role")=="shop" and item.get("round")==4
              and item.get("thread") is None and item.get("text")==text]
    if len(matching)!=1:
        return None
    return {key:matching[0][key] for key in ("id","ts","round","author","role","thread","text")}


def run(op,root,source,pin,session,allow):
    sys.path[:0]=[str(op/"deploy"),str(op/"kit"),str(root/"codex-r4")]
    import agent_kit as official
    from forum_campaign_operator import verify_kit,make_campaign_mind,BoundedClassModel,active_customer
    sdk_count=verify_kit(op)
    source_hashes=verified_source(source,pin)
    official.mk.LOG_FILE=session/"logs/agent-kit-private.log"
    for key in ("AGENT_LLM_BASE","AGENT_LLM_MODEL","AGENT_LLM_KEY"):
        os.environ.pop(key,None)

    summary={"official_kit_files_verified":sdk_count,"genuine_source_sha256":source_hashes,
             "preview_only":not allow,"wallet_transfer_allowed":False,"native_dispatch_invocations":0,
             "model_calls":0,"actual_production_ledger":True}
    state=root/"state/r4-benefits"
    policy_path=state/POLICY_NAME
    approved_policy=checked_file(policy_path,4096)
    with httpx.Client(timeout=6,follow_redirects=False,trust_env=False) as client:
        def read(url,params=None):
            result=client.get(url,params=params)
            result.raise_for_status()
            return result.json()
        facts=observe(read,approved_policy)
        def execute(mode,token=None):
            verified_source(source,pin)
            ctx={"name":facts["shop"],"market":MARKET,"shop_url":facts["shop_url"],"addresses":{"shop":facts["wallet"]},
                 "tokens":{} if token is None else {"shop":token},"signer":NoWallet()}
            result=official.Toolbox(root,ctx).run(NAME,"call",{"mode":mode},d=source)
            return envelope_only(result)
        with approval(state/APPROVAL_NAME,facts) as set_approval:
            view=execute("preview")
            (session/"native-preview-private.json").write_bytes(encoded(view))
            summary.update(status=view["status"],classic_sdk_call=True)
            if view["status"]!="preview":
                summary["reason"]=view.get("reason","native_preview_unavailable")
                return summary
            summary["preview_lane"]=view["lane"]
            summary["notice_text_sha256"]=digest(view["text"].encode())
            if not allow or view["lane"]!="eligible":
                return summary
            if active_customer(root):
                summary["status"]="customer_active"
                return summary
            import worker_bootstrap
            registered=worker_bootstrap.validated_kit(root)
            if registered.shop_url.rstrip("/")!=facts["shop_url"] or registered.address("shop").lower()!=facts["wallet"]:
                raise ValueError("authenticated shop context differs")
            token=registered.token("shop")

            def dispatch():
                if active_customer(root) or checked_file(policy_path,4096)!=approved_policy:
                    return {"status":"blocked"}
                revised=observe(read,approved_policy)
                fields=("shop","round","wallet","shop_url","card_url","policy_sha256")
                if any(revised[key]!=facts[key] for key in fields):
                    return {"status":"blocked"}
                revised["approved_fingerprint"]=view["fingerprint"]
                set_approval(revised)
                summary["native_dispatch_invocations"]+=1
                result=execute("dispatch",token)
                (session/"native-dispatch-private.json").write_bytes(encoded(result))
                return result

            gate=NoticeGate({"lane":view["lane"],"text":view["text"]},dispatch)
            agent={"llm":{"base":"market"},"max_steps":4,"run_minutes":1,
                   "persona":"outseop-r4의 정확한 포럼 공지 운영 담당자",
                   "goal":"공개 안내 내용과 현재 상태를 확인한다. 지금 공지가 적절하고 eligible이면 제공된 도구의 dispatch를 최대 한 번 선택한다. 공개 메시지나 가격 혹은 혜택을 새로 만들지 않는다. 이외엔 sleep한다."}
            model=BoundedClassModel(official.Model(agent,MARKET,{"tokens":{"shop":token}}),session,seconds=35)
            safe_context={"name":facts["shop"],"market":MARKET,"shop_url":None,"tokens":{},"addresses":{}}
            mind=make_campaign_mind(official,session,agent,model,gate,safe_context)
            try:
                mind.run_once([])
            except Exception as exc:
                (session/"mind-error-private.txt").write_text(type(exc).__name__+": "+str(exc))
                if not gate.attempted:
                    gate.result={"status":"model_unavailable"}
            summary.update(status=gate.result["status"],model_calls=model.calls,entrypoint="official Mind.run_once")
            if gate.result["status"]=="posted":
                try:
                    found=public_receipt(root,read,view["fingerprint"],view["text"])
                except (OSError,ValueError,sqlite3.Error,httpx.HTTPError):
                    found=None
                summary["public_post_verified"]=found is not None
                if found is not None:
                    summary["post_id"]=found["id"]
                    (session/"public-post.json").write_bytes(encoded(found))
            return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operator",type=Path,required=True)
    parser.add_argument("--source",type=Path,required=True)
    parser.add_argument("--forge-sha256",required=True)
    parser.add_argument("--session",type=Path,required=True)
    flags=parser.add_mutually_exclusive_group()
    flags.add_argument("--preview-only",action="store_true")
    flags.add_argument("--allow-one-post",action="store_true")
    args=parser.parse_args()
    op=args.operator.resolve(strict=True)
    root=(op.parent/"round-4").resolve(strict=True)
    source=args.source.resolve(strict=True)
    session=args.session.absolute()
    if session.parent.resolve(strict=True)!=op/"runtime" or not session.name.startswith("first-purchase-bonus-notice-run-"):
        parser.error("fresh direct operator runtime session required")
    os.umask(0o077)
    session.mkdir(mode=0o700)
    (session/"logs").mkdir(mode=0o700)
    fd=os.open(op/"runtime/forum-campaign.lock",os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with (session/"logs/console-private.log").open("x") as log,redirect_stdout(log),redirect_stderr(log):
            result=run(op,root,source,args.forge_sha256,session,args.allow_one_post)
        (session/"summary.json").write_bytes(encoded(result))
        print(json.dumps(result,ensure_ascii=False))
    finally:
        os.close(fd)


if __name__=="__main__":
    main()

