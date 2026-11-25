"""Host-only synthetic customer dialogue with genuine read_customer_offers v2."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import secrets
import sys

from customer_offer_auto_pages_factored_candidate import AutoOfferGate
from card_offer_producer_host import acquire, label
from card_source_read_lane import PATTERN
from forum_official_mind_canary import NoWallet

TOOL = "read_customer_offers"
SKU = re.compile(r"G[0-9a-f]{8}")
PIN = {
    "permission.yml":"610de64698b425af551a44488d195d3e7b231ef193866adde446f6e0b9580055",
    "logic.py":"a122aed15c9462dfb6ed2c77665e6fbb82de7720633adb03ccf0ec7b1b4e45ff",
    "test.py":"b35de2a9a624c7ac63f882584f7af35943c548fe1c77cbd5b8e366a4804a9518",
}
QUESTIONS = {
    "food":"지금 살 수 있는 식품을 찾아 주세요. 등급, 상품가와 남은 유통시간을 같이 알려 주세요. 아직 구매하지 않을게요.",
    "grade":"현재 식품 중 C등급은 무엇이고 가격과 남은 유통시간이 어떻게 되나요? 문의만 합니다.",
}


def load_bundle(directory):
    files={name:(directory/name).read_bytes() for name in (*PIN,"forge.json")}
    manifest=json.loads(files["forge.json"])
    if ((manifest.get("tool"),manifest.get("version"),manifest.get("sha256"))!=(TOOL,2,PIN)
        or any(sha256(files[name]).hexdigest()!=digest for name,digest in PIN.items())):
        raise ValueError("unreviewed customer offer source")
    return files


def make_context(offers,catalog,observed):
    salt=secrets.token_bytes(32)
    products={}
    ambiguous=set()
    for row in catalog:
        if not isinstance(row,dict):
            continue
        sku,name,category=(row.get(k) for k in ("sku","name","category"))
        if not isinstance(sku,str) or not SKU.fullmatch(sku) or not label(name) or not isinstance(category,str):
            continue
        path=[part.strip() for part in category.split(">")]
        if not all(label(part) for part in path):
            continue
        value=(name,path)
        if sku in products and products[sku]!=value:
            ambiguous.add(sku)
        products[sku]=value
    units=[]
    for offer in offers:
        sku,grade,price,expiry,unit=(offer.get(k) for k in ("sku","grade","price","expiry","_unit"))
        if (sku not in products or sku in ambiguous or not isinstance(unit,str) or not unit
            or grade not in ("A","B","C") or type(price) is not int or price<1):
            continue
        if expiry is not None and (type(expiry) not in (int,float) or not math.isfinite(expiry) or int(expiry)<=observed):
            continue
        name,path=products[sku]
        reference=sha256(salt+unit.encode()).hexdigest()[:32]
        units.append({"unit_ref":reference,"sku":sku,"name":name,"category_path":path,
                      "state":"available","grade":grade,"price_credits":price,"standard_fee_credits":None,
                      "expires_at":int(expiry) if expiry is not None else None})
    if len(units)>200 or len({r["unit_ref"] for r in units})!=len(units):
        raise ValueError("offer snapshot exceeds schema capacity or has duplicate units")
    return {"schema":"outseop-r4.customer-offers.v1","shop":"outseop-r4",
            "observed_at":observed,"valid_until":observed+150,"units":units}


class OfferGate:
    tools={TOOL:{}}

    def __init__(self,invoke):
        self.invoke=invoke
        self.cursor=None
        self.actions=[]
        self.observed=[]

    def listing(self):
        return ("- read_customer_offers: {op:'context', skus?: [SKU], min_remaining_seconds?: integer}. "
                "If more=true, use {op:'next'}; host passes through the authentic cursor and filters.")

    def forge(self,args):
        return {"error":"disabled"}

    def read(self,name):
        return {"error":"disabled"}

    def call(self,name,args):
        if name!=TOOL or not isinstance(args,dict):
            return {"error":"invalid_arguments"}
        action=args.get("op")
        if action=="next" and args=={"op":"next"} and self.cursor is not None:
            native=self.cursor
        elif action=="context" and set(args)<={"op","skus","min_remaining_seconds"}:
            native=args
        else:
            return {"error":"invalid_arguments"}
        self.cursor=None
        self.actions.append({"tool":TOOL,"op":action})
        response=self.invoke(native)
        if not isinstance(response,dict) or set(response)!={"ok","result"} or response["ok"] is not True:
            return {"error":"offer_lookup_unavailable"}
        result=response["result"]
        if not isinstance(result,dict) or "error" in result:
            return {"error":"offer_lookup_unavailable"}
        rows=result.get("units",[])
        self.cursor=result.get("next_args")
        public=[{k:row[k] for k in ("sku","name","category_path","state","grade","price_credits",
                                       "expires_at","remaining_seconds")} for row in rows]
        self.observed.extend(public)
        return {"as_of":result["as_of"],"total_count":result["total_count"],"items":public,
                "more":self.cursor is not None,"partial_row_unavailable":"row_fragment" in result}


def safe_dialogue(query,gate,answer):
    if (not isinstance(answer,dict) or answer.get("data") is not None or not isinstance(answer.get("reply"),str)
        or len(answer["reply"])>2000 or PATTERN.search(answer["reply"].encode())
        or re.search(r"0x[a-fA-F0-9]{40,}",answer["reply"])):
        return {"status":"no_safe_public_reply","question":query,"tool_calls":gate.actions}
    reply=answer["reply"]
    selected={row["sku"]:row for row in gate.observed if row["sku"] in reply or row["name"] in reply}
    return {"status":"synthetic_dialogue_complete","question":query,"tool_calls":gate.actions,
            "selected_public_products":list(selected.values()),"public_reply":reply}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operator",type=Path,required=True)
    parser.add_argument("--session",type=Path,required=True)
    parser.add_argument("--sources",type=Path)
    parser.add_argument("--question",choices=QUESTIONS,default="food")
    parser.add_argument("--run-class",action="store_true")
    args=parser.parse_args()
    op=args.operator.resolve(strict=True)
    session=args.session.resolve()
    runtime=(op/"runtime").resolve(strict=True)
    if session.parent!=runtime or not session.name.startswith("customer-offer-canary-") or session.exists():
        parser.error("expected fresh isolated customer-offer session")
    origin=runtime/"class-rebuild-customer-context-20261125/tools"/TOOL
    files=load_bundle(args.sources.resolve(strict=True) if args.sources else origin)
    sys.path.insert(0,str(op/"kit"))
    import agent_kit as official
    os.umask(0o077)
    session.mkdir(mode=0o700)
    for folder in ("logs","host_inputs","tools"):
        (session/folder).mkdir(mode=0o700)
    official.mk.LOG_FILE=session/"logs/agent-kit.log"
    with (session/"logs/console-private.log").open("x") as log, redirect_stdout(log), redirect_stderr(log):
        registered,observed,offers,catalog=acquire(op.parent/"round-4")
        view=make_context(offers,catalog,observed)
        raw=json.dumps(view,ensure_ascii=False,separators=(",",":"),allow_nan=False).encode()
        if len(raw)>512*1024:
            raise ValueError("snapshot too large")
        path=session/"host_inputs/customer_offer_context.json"
        path.write_bytes(raw)
        path.chmod(0o400)
        target=session/"tools"/TOOL
        target.mkdir()
        for name,data in files.items():
            (target/name).write_bytes(data)
        result={"status":"prepared","representative_offer_count":len(view["units"])}
        if args.run_class:
            for key in ("AGENT_LLM_BASE","AGENT_LLM_MODEL","AGENT_LLM_KEY"):
                os.environ.pop(key,None)
            ctx={"name":"outseop-r4","market":registered.market,"tokens":{},"addresses":{},"signer":NoWallet()}
            box=official.Toolbox(session,ctx)
            perm=box.tools[TOOL]["perm"]
            if any(perm.get(k) for k in ("wallet","identity","network","write","exec","handles")):
                raise ValueError("unexpected offer reader permissions")

            def invoke(request):
                load_bundle(target)
                if path.read_bytes()!=raw:
                    raise ValueError("trusted offer snapshot changed")
                return box.run(TOOL,"call",request)

            gate=AutoOfferGate(invoke)
            agent={"llm":{"base":"market"},"max_steps":8,"run_minutes":3,
                   "persona":"실제 공개 재고 사실만 안내하는 응대 담당자",
                   "goal":"가상 고객의 식품 문의에 답한다. 표에서 보이는 전체 제안을 검토하고 필요하면 {op:details}로 정확한 명칭을 확인해 "
                          "맞는 품목을 찾고, 확인 불가한 등급/가격/시간은 모른다고 답한다. "
                          "조회한 상품만 간단히 설명하고 구매 동의가 없으므로 결제나 계약을 제안하지 않는다. "
                          "고객 질문에는 reply를 한 번 보내고 sleep한다."}
            model=official.Model(agent,registered.market,{"tokens":{"shop":registered.token("shop")}})
            mind=official.Mind(session,agent,model,gate,ctx,[])
            query=QUESTIONS[args.question]
            event=official.Event("a2a","synthetic-customer",query)
            mind.pending[event.id]=event
            mind.run_once([event])
            result=safe_dialogue(query,gate,event.answer)
    result={**result,"coverage":"legacy representative SKU/grade offers, not physical stock census",
            "pricing_source":"pinned externally authored legacy stock_offers","actual_customers_contacted":False,
            "checkout_verified":False,"experiment":"automatic native pages / factored compact table","official_market_model_called":args.run_class}
    (session/"summary.json").write_text(json.dumps(result,ensure_ascii=False)+"\n")
    print(json.dumps(result,ensure_ascii=False))


if __name__=="__main__":
    main()

