"""Synthetic broker/protocol checks without a production listener or financial executor."""
import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time

CURRENT=Path(__file__).resolve().parent
OP=CURRENT.parents[1]

def run(runtime):
    with tempfile.TemporaryDirectory(prefix="r4-alternatives-host-") as directory:
        overlay=Path(directory)
        for source,target in (
            ("catalogue_protocol.py","public_catalogue_protocol.py"),
            ("catalogue_broker.py","broker_public_catalogue_host_candidate.py"),
            ("catalogue_broker_core.py","catalogue_broker_core.py"),
            ("public_alternatives_host.py","public_alternatives_host.py"),
        ):
            shutil.copyfile(CURRENT/source,overlay/target)
        shutil.copyfile(runtime/"HOST-CONTEXT.json",overlay/"HOST-CONTEXT.json")
        sys.path[:0]=[str(overlay),str(runtime),str(OP.parent/"round-4/codex-r4")]
        try:
            from broker_public_catalogue_host_candidate import Broker,mask
            from public_catalogue_protocol import CatalogueProtocol,CatalogueError
            from public_alternatives_host import ScopedAlternatives
            from public_product_continuity import PublicContinuity
            from durable_public_continuity import DurablePublicContinuity
            from task_state import TaskStateDB
            return exercise(overlay,Broker,CatalogueProtocol,ScopedAlternatives,CatalogueError,mask,PublicContinuity,DurablePublicContinuity,TaskStateDB)
        finally:
            del sys.path[:3]

def exercise(root,Broker,Protocol,ScopedAlternatives,Error,mask,PublicContinuity,DurablePublicContinuity,TaskStateDB):
    raw=b'{"example":"exact immutable bytes"}'
    document={"observed_at":int(time.time())-1,"valid_until":int(time.time())+120}
    digest=sha256(raw).hexdigest()
    row={"sku":"G00000001","name":"채소 반찬","category":"식품","grade":"A",
         "preferred_price":3200,"expires_at":int(time.time())+10000}
    alt={"status":"options","snapshot":digest,**document,"items":[row]}
    reply="확인된 대안입니다. 원래 요청 조건은 확인되지 않았습니다. 채소 반찬 G00000001 A등급 3,200크레딧. 결제서는 발행하지 않았습니다."
    result={"status":"rendered","reply":reply,**document,
            "public_facts":[{"sku":row["sku"],"grade":row["grade"],"preferred_price":row["preferred_price"]}]}
    sidecar=root/"stock-state.json"
    sidecar.write_bytes(b'{"sample":"owned stock sidecar"}')
    sidecar.chmod(0o400)
    protocol=Protocol(mask)

    class Scope:
        prepared=True
        instruction="Existing read-only search"
        stock_state=[]
        clock=staticmethod(time.time)
        def __init__(self,matched,worker):
            self.protocol=protocol
            self._source=(raw,document["observed_at"],document["valid_until"])
            self.matched=matched
            self.alternatives=ScopedAlternatives(self,worker,sidecar)
        def supplier(self):
            return raw,document
        def open(self,text,focus,remaining):
            return {"status":"ready","snapshot":digest,"columns":["sku","grade","name","preferred_price"],
                    "rows":[[row["sku"],row["grade"],row["name"],3200]] if self.matched else [],
                    "common":{},"lookup":{},"catalogue":{"matched_count":self.matched,"source_count":1,
                    "hints":{"preparation":{"fits":[],"requested_sku_missing":False,"constraints_unverified":False}}}}
        def fallback(self,*args):
            raise Error("fallback_not_applicable")
        def render(self,*args):
            raise AssertionError("alternatives must not use ordinary exact render")
        def semantic(self,*args):
            raise AssertionError("alt tool ambiguity in test")

    class FakeModel:
        def __init__(self,action):
            self.action=action
            self.messages=[]
        def complete(self,messages,**kwargs):
            self.messages.append(deepcopy(messages))
            return json.dumps(self.action,ensure_ascii=False)

    selection={"action":"render_public_alternatives","args":{"items":[{"sku":row["sku"],"grade":row["grade"]}]}}
    respond={"action":"respond","args":{"text":"현재 요청 상품을 확인하지 못했습니다."}}
    question="초콜릿 재고와 가격을 알려주세요."

    def run_case(text,action=selection,matched=0,rendered=None,with_feature=True,continuity=None,menu=None):
        requests=[]
        legacy=[]
        remembered=[]
        def worker(*,args,snapshot,stock,timeout):
            assert snapshot==raw and stock==sidecar.read_bytes() and 0<timeout<=5
            requests.append(deepcopy(args))
            if args["op"]=="context":
                return deepcopy(alt if menu is None else menu)
            if rendered is None:
                return deepcopy(result)
            return deepcopy(rendered)
        def execute(args):
            legacy.append(args["action"])
            if args["action"]=="quote_and_send":
                assert args["sku"]==row["sku"] and args["requested_sku"]==row["sku"]
                return {"outcome":"synthetic_quote","reply":"독립 결제경로 테스트입니다."}
            assert args["action"]=="context"
            return {"outcome":"context","inventory":[dict(row,stock_status="available")] }
        scope=Scope(matched,worker)
        if not with_feature:
            scope.alternatives=None
        model=FakeModel(action)
        agent=Broker(execute,model,catalogue=scope,seconds=15,model_seconds=3)
        def remember(facts):
            remembered.append(facts)
            return continuity.remember(task,context,facts) if continuity is not None else True
        answer=agent.handle(text,remember=remember,
                            remembered=continuity.current(task,context) if continuity is not None else None)
        assert len(model.messages)==1
        first=model.messages[0]
        views=[json.loads(item["content"]) for item in first if item["role"]=="user"]
        return answer,requests,legacy,remembered,views

    answer,calls,legacy,remembered,views=run_case(question)
    assert answer["reply"].startswith(reply) and "SKU를 명시" in answer["reply"]
    assert answer["state"]=="input_required"
    assert answer["data"]["reference_only"] is True
    assert answer["data"]["public_facts"]==result["public_facts"]
    assert [call["op"] for call in calls]==["context","render"] and not legacy and remembered==[[]]
    assert all(call["text"]==question for call in calls)
    assert calls[1]["snapshot"]==digest
    assert views[0]["verified_context"]["public_alternatives"]==alt
    assert set(views[0]["verified_context"])=={"public_alternatives"}
    assert set(views[1]["host_readonly_flow"]["allowed_final_actions"])=={"render_public_alternatives","respond"}
    semantic={"action":"search_similar_products","args":{"groups":[{"product_phrase":"초콜릿","queries":["과자"]}]}}
    blocked,calls,legacy,remembered,_=run_case(question,semantic)
    assert [call["op"] for call in calls]==["context"] and not legacy and not remembered
    assert blocked.get("data") is None

    unmatched={"action":"render_public_alternatives","args":{"items":[{"sku":"G00000002","grade":"A"}]}}
    bad,calls,_,_,_=run_case(question,unmatched)
    assert [call["op"] for call in calls]==["context"] and bad["reply"]!=reply

    changed=dict(result,public_facts=[dict(result["public_facts"][0],preferred_price=3201)])
    bad,calls,_,_,_=run_case(question,rendered=changed)
    assert [call["op"] for call in calls]==["context","render"] and bad["reply"]!=reply

    wrong_grade=dict(result,public_facts=[dict(result["public_facts"][0],grade="B")])
    bad,calls,_,remembered,_=run_case(question,rendered=wrong_grade)
    assert [call["op"] for call in calls]==["context","render"] and bad.get("data") is None and not remembered

    unavailable={"status":"unavailable","reason":"selection_unavailable"}
    bad,calls,_,_,_=run_case(question,rendered=unavailable)
    assert [call["op"] for call in calls]==["context","render"] and bad["reply"]!=reply

    for text,matched,feature in (
        ("G00000001 결제서를 보내주세요.",0,True),
        ("초콜릿 재고와 가격을 알려주세요. 대안은 필요 없어요.",0,True),
        (question,1,True),
        (question,0,False),
    ):
        _,calls,_,_,views=run_case(text,respond,matched,with_feature=feature)
        assert not calls
        assert "public_alternatives" not in views[0]["verified_context"]

    _,calls,_,_,views=run_case(question,respond,menu={"status":"unavailable","reason":"no_alternatives"})
    assert [call["op"] for call in calls]==["context"]
    assert "search_similar_products" in views[1]["host_readonly_flow"]["allowed_final_actions"]
    for menu in (dict(alt,snapshot="0"*64),dict(alt,items=[row,dict(row,sku=row["sku"].lower())])):
        try:
            protocol.alternatives_result("context",menu,document["observed_at"],document["valid_until"],digest)
        except Error:
            pass
        else:
            raise AssertionError("snapshot or duplicate must reject")
    task="synthetic-task-00001"
    context="synthetic-context-00001"
    old_fact={"sku":"G00000002","grade":"B","preferred_price":3000}
    database=TaskStateDB(root/"public-hints.sqlite3")
    durable=DurablePublicContinuity(database,PublicContinuity)
    quote={"action":"quote_and_send","args":{"sku":row["sku"],"proposed_price":3200}}
    for memory in (PublicContinuity(),durable):
        assert memory.remember(task,context,[old_fact])
        assert memory.current(task,context)==(old_fact,)
        response,_,legacy,remembered,_=run_case(question,continuity=memory)
        assert response["data"]["reference_only"] is True
        assert not legacy and remembered==[[]] and memory.current(task,context)==()
        for text in ("그 첫번째로 살게요.", "아까 그 상품으로 살게요."):
            _,_,legacy,_,_=run_case(text,quote,continuity=memory)
            assert "quote_and_send" not in legacy
        _,_,legacy,_,_=run_case("G00000001 구매할게요. 결제서를 보내주세요.",quote,continuity=memory)
        assert legacy==["context","quote_and_send"]
    assert DurablePublicContinuity(TaskStateDB(database.path),PublicContinuity).current(task,context)==()
    return {"synthetic_groups_passed":15,"production_modified":False,"actual_model_calls":0,"financial_calls":0}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--runtime",type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(run(args.runtime.resolve(strict=True)),sort_keys=True))

if __name__=="__main__":
    main()
