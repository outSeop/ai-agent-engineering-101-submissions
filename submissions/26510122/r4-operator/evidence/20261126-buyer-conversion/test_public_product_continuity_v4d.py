import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

operator=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(operator.parent/"round-4/codex-r4"))
release=operator/"deploy/public_catalogue_runtime_v4d"
sys.path.insert(0,str(release))
import broker_public_catalogue_host_candidate as broker
from public_product_continuity import PublicContinuity, page_facts

A="Gabcdef01"
B="Gabcdef02"
ROW={"sku":A,"grade":"B","preferred_price":4500,"stock_status":"available"}
MEMORY={"sku":A,"grade":"B","preferred_price":4500}


class Catalogue:
    instruction="test search"
    class protocol:
        @staticmethod
        def search(args,page):
            return args
        @staticmethod
        def page_skus(page):
            return {row[0] for row in page["rows"]}

    def __init__(self, rows):
        self.rows=rows

    def page(self, rows, skus=None):
        return {"snapshot":"a"*64,"columns":["sku","grade","preferred_price"],"common":{},"lookup":{},
                "rows":[[r[k] for k in ("sku","grade","preferred_price")] for r in rows],
                "catalogue":{"source_count":len(self.rows),"matched_count":len(rows),"criteria":{"skus":skus or []}}}

    def open(self,text,focus,remaining):
        return self.page(self.rows)

    def search(self,args,remaining):
        skus=args.get("skus")
        return self.page([r for r in self.rows if ((not skus or r["sku"] in skus)
                         and r["sku"] not in args.get("exclude_skus",[]))],skus)

    def render(self,args,remaining):
        return {"reply":"검증 상품입니다."}


class Tests(unittest.TestCase):
    def test_cache_scope_ttl_and_defensive_copy(self):
        clock=[0]
        cache=PublicContinuity(ttl=10,limit=1,clock=lambda:clock[0])
        t,c,other=("task_123456789012","context_123456789","context_987654321")
        self.assertTrue(cache.remember(t,c,[dict(MEMORY,private="no")]))
        self.assertIsNone(cache.current(t,other))
        value=cache.current(t,c)
        self.assertEqual(value,(MEMORY,))
        value[0]["sku"]=B
        self.assertEqual(cache.current(t,c),(MEMORY,))
        clock[0]=10
        self.assertIsNone(cache.current(t,c))

    def path(self,text,moves,*,rows=None,remembered=None,remember=None,transport_id=None,trace=None,commits=None,catalogue=None):
        rows=[ROW] if rows is None else rows
        plan=iter(moves+[{"action":"respond","args":{"text":"조건을 더 확인해 주세요."}}]*6)
        requests=[]
        received=[]
        def complete(messages,**kwargs):
            received.append(messages[-1]["content"])
            return json.dumps(next(plan))
        def execute(args):
            requests.append(args)
            if args["action"]=="context":
                return {"outcome":"context","inventory":rows,"prior_offer":None,"wait":None}
            if commits is not None and args["action"]=="quote_and_send":
                if args["commit"] in commits:
                    return {"outcome":"already_dispatched","reply":"이미 처리했습니다."}
                commits.add(args["commit"])
            return {"reply":"fixture signed","data":{"checkout_jwt":"fixture"},"state":"completed"}
        path=broker.Broker(execute,SimpleNamespace(complete=complete),trace=trace,catalogue=catalogue or Catalogue(rows),max_steps=4)
        answer=path.handle(text,transport_id=transport_id,remembered=remembered,remember=remember)
        return answer,requests,received

    def test_render_keeps_task_open_then_named_checkout(self):
        kept=[]
        answer,_,_=self.path(A+" 가격 알려 주세요", [{"action":"render_public_products","args":{"items":[{"sku":A,"grade":"B"}]}}],
                             remember=lambda facts:kept.extend(facts) or True)
        self.assertEqual(answer["state"],"input_required")
        self.assertEqual(kept,[MEMORY])
        move={"action":"quote_and_send","args":{"sku":A,"proposed_price":4500}}
        answer,reqs,_=self.path("그 상품 결제서를 보내 주세요", [move], remembered=kept)
        self.assertIn("checkout_jwt",answer["data"])
        self.assertEqual(reqs[-1]["sku"],A)
        self.assertNotIn("right",reqs[-1])

    def test_refusal_for_wrong_sku_stale_or_non_product_cap(self):
        move={"action":"quote_and_send","args":{"sku":B,"proposed_price":4500}}
        a,reqs,_=self.path(A+" 결제권 주세요",[move], remembered=[MEMORY])
        self.assertEqual(len(reqs),1)
        move["args"]["sku"]=A
        for text,rows,hints in [
            ("그 상품 결제서 보내 주세요",[dict(ROW,preferred_price=4900)],[MEMORY]),
            ("그 상품 결제서 보내 주세요",[ROW],[MEMORY,dict(MEMORY,sku=B)]),
            ("그 상품 결제서 보내 주세요",[ROW],None),
            (A+" A등급이면 결제서 보내 주세요",[ROW],None),
            (A+" 총액 4,500원 이하면 결제서 보내 주세요",[ROW],None),
            (A+" 결제서 보내 주세요?",[ROW],None),
        ]:
            with self.subTest(text=text):
                _,reqs,_=self.path(text,[move],rows=rows,remembered=hints)
                self.assertEqual(len(reqs),1)

    def test_signed_inventory_or_product_price_only(self):
        for text in [A+" 결제권 주세요", A+" 재고 있으면 결제서 보내 주세요",
                     A+" 4,500원 이하면 결제서 보내 주세요",
                     "옥수수술빵4팩 "+A+" 서명 결제서 주세요",
                     A+" checkout_jwt 보내 주세요"]:
            self.assertTrue(broker.consents(text,{},broker.stated_prices(text)[0]),text)

    def test_attribute_followup_refreshes_known_product(self):
        text=("도정일과 소비기한/보관기한, 지금 실제 재고인지 알려 주세요. "
              "구매한다면 최종 결제액이 표시된 유효한 서명 checkout을 먼저 보내 주세요.")
        move={"action":"quote_and_send","args":{"sku":A,"proposed_price":4500}}
        answer,reqs,_=self.path(text,[move],remembered=[MEMORY])
        self.assertEqual(reqs[0]["requested_sku"],A)
        self.assertIn("checkout_jwt",answer["data"])
        other,reqs,_=self.path(text,[move],remembered=[MEMORY,dict(MEMORY,sku=B)])
        self.assertNotIn("data",other)
        self.assertEqual(len(reqs),1)

    def test_unimplemented_conditions_remain_closed(self):
        for text in ("A급이고 1,000크레딧이면 구매할게요",
                     "소비기한 24시간 이상이고 1,000크레딧이면 구매할게요",
                     "총 1,000크레딧 이하면 구매할게요",
                     "정품이면 1,000크레딧에 구매할게요"):
            self.assertFalse(broker.consents(text,{},broker.stated_prices(text)[0]),text)

    def test_withdrawal_negation_and_example_block_executor(self):
        move={"action":"quote_and_send","args":{"sku":A,"proposed_price":4500}}
        for text in [A+" 결제서 보내 주세요. 아니 취소합니다",
                     A+" 결제서 보내지 마세요",
                     A+" 결제서 발급하지 말아 주세요",
                     A+" 결제서 보내 주세요라고 입력하면 되나요?",
                     A+" 결제서 보내 주세요? 아직 구매하지 않겠습니다",
                     A+" 48시간 이상 소비기한이면 4,500원에 구매할게요",
                     A+" 가스비 포함 총 4,500원이면 결제서 보내 주세요"]:
            with self.subTest(text=text):
                _,reqs,_=self.path(text,[move],remembered=[MEMORY])
                self.assertEqual(len(reqs),1)

    def test_explicit_target_overrides_same_task_hint(self):
        row=dict(ROW,sku=B)
        move={"action":"quote_and_send","args":{"sku":B,"proposed_price":4500}}
        answer,reqs,_=self.path(B+" 결제서 보내 주세요",[move],rows=[row],remembered=[MEMORY])
        self.assertIn("checkout_jwt",answer["data"])
        self.assertEqual(reqs[-1]["sku"],B)
        self.assertEqual(reqs[-1]["requested_sku"],B)

    def test_explicit_checkout_without_target_blocks_model_selected_product(self):
        move={"action":"quote_and_send","args":{"sku":A,"proposed_price":4500}}
        text="재고가 있으면 5,000 크레딧 이내에 서명된 결제권을 보내 주세요"
        self.assertTrue(broker.consents(text,{},broker.stated_prices(text)[0]))
        result,reqs,seen=self.path(text,[move])
        self.assertEqual(len(reqs),1)
        self.assertNotIn("data",result)
        self.assertTrue(any("customer_product_target_required" in m for m in seen))

    def test_transport_repeat_does_not_replay_signed_data(self):
        commits=set()
        move={"action":"quote_and_send","args":{"sku":A,"proposed_price":4500}}
        text=A+" 결제서 보내 주세요"
        args={"transport_id":"m-123456789012345678","commits":commits}
        first,r1,_=self.path(text,[move],**args)
        second,r2,_=self.path(text,[move],**args)
        self.assertIn("checkout_jwt",first["data"])
        self.assertNotIn("data",second)
        self.assertEqual(r1[-1]["commit"],r2[-1]["commit"])
        self.assertEqual(len(commits),1)

    def test_continuity_trace_counts_only(self):
        trace=[]
        observer=SimpleNamespace(add=lambda ref,role,payload,review:trace.append((role,payload)))
        self.path("그 상품이 아직 재고인지 알려 주세요",[{"action":"respond","args":{"text":"확인 중입니다."}}],
                  remembered=[MEMORY],trace=observer)
        facts=[data for role,data in trace if role=="public_continuity"]
        self.assertEqual(facts,[{"public_hint_count":1,"used_as_focus":True,"current_explicit_target":False}])

    def test_disallowed_alternative_stays_nonbinding(self):
        row=dict(ROW,sku=B)
        moves=[{"action":"search_products","args":{"skus":[A]}},
               {"action":"search_products","args":{"exclude_skus":[A]}},
               {"action":"render_public_products","args":{"items":[{"sku":B,"grade":"B"}]}}]
        for text in [A+" 알레르기 성분이 없는 대안만 알려주세요", A+" 이 상품만, 대안은 필요 없어요"]:
            answer,reqs,_=self.path(text,moves,rows=[row])
            self.assertNotIn("다른 상품입니다",answer["reply"])
            self.assertNotIn("data",answer)
            self.assertEqual(len(reqs),1)

    def test_cross_page_alternatives_preserve_order_and_refuse_ambiguous_purchase(self):
        alternate=dict(ROW,sku=B,grade="A")
        missing="G00000000"
        class Paged(Catalogue):
            def open(self,text,focus,remaining):
                return self.page([])
        catalogue=Paged([ROW,alternate])
        kept=[]
        moves=[{"action":"search_products","args":{"skus":[missing]}},
               {"action":"search_products","args":{"skus":[A]}},
               {"action":"search_products","args":{"skus":[B]}},
               {"action":"render_public_products","args":{"items":[{"sku":B,"grade":"A"},{"sku":A,"grade":"B"}]}}]
        result,reqs,_=self.path(missing+" 재고와 대안을 알려주세요",moves,
                               catalogue=catalogue,remember=lambda facts:kept.extend(facts) or True)
        self.assertEqual(result["state"],"input_required")
        self.assertEqual(kept,[dict(MEMORY,sku=B,grade="A"),MEMORY])
        self.assertEqual(len(reqs),1)
        move={"action":"quote_and_send","args":{"sku":A,"proposed_price":4500}}
        answer,reqs,_=self.path("그거 구매할게요",[move],remembered=kept)
        self.assertNotIn("data",answer)
        self.assertEqual(len(reqs),1)

    def test_page_join_rejects_snapshot_or_price_disagreement(self):
        cat=Catalogue([ROW])
        selection=[{"sku":A,"grade":"B"}]
        first=cat.open("",[],60)
        same=cat.open("",[],60)
        self.assertEqual(page_facts([first,same],selection),[MEMORY])
        different=cat.page([dict(ROW,preferred_price=4501)])
        self.assertEqual(page_facts([first,different],selection),[])
        same["snapshot"]="b"*64
        self.assertEqual(page_facts([first,same],selection),[])

    def test_exact_missing_can_render_verified_alternative(self):
        other=dict(ROW,sku=B)
        moves=[{"action":"search_products","args":{"skus":[A]}},
               {"action":"search_products","args":{"exclude_skus":[A]}},
               {"action":"render_public_products","args":{"items":[{"sku":B,"grade":"B"}]}}]
        answer,reqs,_=self.path(A+" 재고와 대안 주세요",moves,rows=[other])
        self.assertIn(A,answer["reply"])
        self.assertIn("다른 상품",answer["reply"])
        self.assertEqual(len(reqs),1)


if __name__=="__main__":
    unittest.main()
