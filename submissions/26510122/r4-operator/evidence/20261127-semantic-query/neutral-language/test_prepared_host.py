import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

operator=Path(__file__).resolve().parents[3]
release=operator/"deploy/public_catalogue_runtime_semantic_v4"
sys.path[:0]=[str(release),str(operator/"kit"),str(operator.parent/"round-4/codex-r4")]
from public_reservation_sidecar import public_stock_state, read, seal
from public_catalogue_snapshot_host import CatalogueError
from broker_public_catalogue_host_candidate import Broker, mask as broker_mask

SKU="G00000001"
ALT="G00000002"
OTHER="G00000003"
UNIT="F00000001"


class TestPreparedHost(unittest.TestCase):
    def test_canonical_unit_join_current_grade_and_no_private_columns(self):
        db=sqlite3.connect(":memory:")
        db.execute("CREATE TABLE sale(unit,status,grade,owner,jwt)")
        db.execute("INSERT INTO sale VALUES (?,?,?,?,?)",(UNIT,"issued","B","private-owner","private-jwt"))
        db.execute("INSERT INTO sale VALUES (?,?,?,?,?)",("F00000004","missing","A","other","private-jwt"))
        states=public_stock_state(db,[{"sku":SKU,"unit":UNIT,"grade":"C","expires_at":300},
                                     {"sku":SKU,"unit":"F00000002","grade":"B","expires_at":None},
                                     {"sku":OTHER,"unit":"F00000004","grade":"C","expires_at":None}],100,preferred_price=lambda row:4400 if row["unit"]==UNIT else None)
        self.assertEqual(states,[{"sku":SKU,"grade":"B","stock_status":"available","expires_at":None,"preferred_price":None},
                                 {"sku":SKU,"grade":"C","stock_status":"reserved_pending","expires_at":300,"preferred_price":4400},
                                 {"sku":OTHER,"grade":"C","stock_status":"reconciling","expires_at":None,"preferred_price":None}])
        self.assertNotIn("private",json.dumps(states))
        self.assertNotIn(UNIT,json.dumps(states))

    def test_sidecar_exact_raw_cache_digest(self):
        with TemporaryDirectory() as temp:
            path=Path(temp)/"stock-state.json"
            body={"observed_at":100,"valid_until":250}
            data=b'{"public":"snapshot"}'
            rows=[{"sku":SKU,"grade":"C","stock_status":"reserved_pending","expires_at":300,"preferred_price":4400}]
            path.write_text(json.dumps(seal(data,100,250,rows)))
            self.assertEqual(read(path,data,body),rows)
            with self.assertRaises(CatalogueError):
                read(path,data+b" ",body)

    def path(self, text, moves, *, missing=False, fallback=False, exact=False, remember=None, semantic=False):
        page={"snapshot":"a"*64,"rows":[[ALT,"B",4400]],"columns":["sku","grade","preferred_price"],
              "common":{},"lookup":{},"catalogue":{"source_count":1,"matched_count":1,"hints":{
                  "preparation":{"fits":[{"sku":ALT,"grade":"B","kind":"category_alternative"}],
                                 "requested_sku_missing":missing,"constraints_unverified":False}}}}
        if exact:
            page["rows"][0][0]=SKU
            page["catalogue"]["hints"]["preparation"]["fits"][0].update(sku=SKU,kind="exact_sku")
        if semantic:
            page["rows"].clear()
            page["catalogue"]["hints"]["preparation"]["fits"].clear()
            page["catalogue"]["hints"]["preparation"]["constraints_unverified"]=True
        stock=[{"sku":SKU,"grade":"C","stock_status":"reserved_pending","expires_at":None,"preferred_price":4400}]
        observed=[]
        actions=[]
        class Catalog:
            prepared=True
            stock_state=stock
            protocol=SimpleNamespace(page_skus=lambda data:{r[0] for r in data["rows"]})
            instruction="not for prepared"
            def open(self,*args): actions.append("prepare"); return page
            def search(self,*args): raise AssertionError("serial search must never execute")
            def render(self,*args): actions.append("render"); return {"reply":"검증된 공개 재고입니다."}
            def fallback(self,*args): actions.append("prepared_fallback"); return {"reply":"확인된 재고가 있습니다."}
            def semantic(self,text,args,remaining):
                actions.append(("semantic",text,args))
                return {"reply":"유사어로 찾은 후보입니다. 같은 상품이라고 확인하지 못했습니다."}
        def execute(args):
            actions.append(args["action"])
            self.assertEqual(args["action"],"context")
            return {"outcome":"context","inventory":[]}
        choices=iter(moves)
        def model(messages,**kwargs):
            observed.append([dict(message) for message in messages])
            if fallback:
                raise RuntimeError("model unavailable")
            result=next(choices)
            return result if isinstance(result,str) else json.dumps(result)
        response=Broker(execute,SimpleNamespace(complete=model),catalogue=Catalog(),max_steps=2).handle(text,remember=remember)
        return response,actions,observed

    def test_structured_sku_zero_model_verified_render(self):
        kept=[]
        result,actions,seen=self.path("재고 "+SKU,[],exact=True,remember=lambda rows:kept.extend(rows) or True)
        self.assertEqual(actions,["prepare","render"])
        self.assertEqual(seen,[])
        self.assertEqual(result["state"],"input_required")
        self.assertEqual(kept,[{"sku":SKU,"grade":"B","preferred_price":4400}])

    def test_one_model_choice_with_verified_alternative(self):
        result,actions,seen=self.path(SKU+" 재고와 쌀 대안을 알려주세요",
                                      [{"action":"render_public_products","args":{"items":[{"sku":ALT,"grade":"B"}]}}],
                                      missing=True)
        self.assertEqual(actions,["prepare","render"])
        self.assertEqual(len(seen),1)
        self.assertIn(SKU,result["reply"])
        self.assertIn("다른 상품",result["reply"])

    def test_one_decision_no_serial_search_and_no_unbound_checkout(self):
        result,actions,seen=self.path("재고가 있으면 서명 결제권을 보내 주세요",[
            {"action":"search_products","args":{"q":"쌀"}},
            {"action":"quote_and_send","args":{"sku":ALT,"proposed_price":4400}},
        ])
        self.assertEqual(actions,["context","prepare"])
        self.assertEqual(len(seen),1)
        self.assertNotIn("data",result)

    def test_readonly_timeout_fallback_only(self):
        result,actions,seen=self.path("쌀 재고 알려주세요",[],fallback=True)
        self.assertEqual(actions,["prepare","prepared_fallback"])
        self.assertEqual(len(seen),1)
        self.assertNotIn("data",result)
        result,actions,seen=self.path(SKU+" 결제권을 보내 주세요",[],fallback=True)
        self.assertEqual(actions,["context","prepare"])
        self.assertNotIn("data",result)

    def test_invalid_json_public_single_decision_and_genuine_fallback(self):
        result,actions,seen=self.path("쌀 가격 알려주세요",["malformed",{"action":"respond","args":{"text":"불필요한 재시도"}}])
        self.assertEqual(actions,["prepare","prepared_fallback"])
        self.assertEqual(len(seen),1)
        meta=json.loads(seen[0][-1]["content"])["host_readonly_flow"]
        self.assertTrue(meta["final_decision"])
        self.assertEqual(meta["remaining_decisions_including_this_one"],1)
        self.assertIn("최대 3개",seen[0][0]["content"])
        self.assertNotIn("data",result)

    def test_protected_invalid_json_never_retries_or_falls_back(self):
        result,actions,seen=self.path(SKU+" 결제권을 보내 주세요",["malformed"])
        self.assertEqual(actions,["context","prepare"])
        self.assertEqual(len(seen),1)
        meta=json.loads(seen[0][-1]["content"])["host_prepared_decision"]
        self.assertTrue(meta["final_decision"])
        self.assertEqual(meta["max_render_items"],3)
        self.assertNotIn("data",result)

    def test_semantic_one_terminal_model_uses_original_text_and_queries(self):
        text="밀크 가격 알려 주세요"
        move={"action":"search_similar_products","args":{"product_phrase":"밀크","queries":["우유"]}}
        result,actions,seen=self.path(text,[move],semantic=True)
        self.assertEqual(actions,["prepare",("semantic",text,{"product_phrase":"밀크","queries":["우유"]})])
        self.assertEqual(len(seen),1)
        self.assertIn("유사어",result["reply"])
        self.assertNotIn("data",result)

    def test_semantic_unavailable_on_bound_or_financial_request(self):
        move={"action":"search_similar_products","args":{"product_phrase":"밀크","queries":["우유"]}}
        for text in [SKU+" 재고 알려 주세요",SKU+" 결제권 보내 주세요",
                     "밀크만, 대안은 필요 없어요", "밀크 가격 알려주세요. 우선 결제서 보내주세요."]:
            with self.subTest(text=text):
                result,actions,seen=self.path(text,[move],semantic=True)
                self.assertEqual(len(seen),1)
                self.assertFalse(any(isinstance(action,tuple) for action in actions))
                self.assertNotIn("data",result)

    def test_product_phrase_boundary_keeps_global_request_text(self):
        from public_catalogue_protocol import CatalogueProtocol
        protocol=CatalogueProtocol(broker_mask)
        raw="밀크 500ml 가격 알려 주세요. 아직 결제하지 않을게요."
        args={"product_phrase":"밀크","queries":["우유"]}
        self.assertEqual(protocol.semantic(raw,args),{"text":raw,**args})
        for malformed in [{"product_phrase":"소이밀크","queries":["두유"]},
                          {"product_phrase":"밀크","queries":["우유"],"price":1},
                          {"queries":["우유"]}]:
            with self.assertRaises(CatalogueError):
                protocol.semantic(raw,malformed)
        with self.assertRaises(CatalogueError):
            protocol.semantic("밀크와 밀크 가격",args)

    def test_public_fast_path_denies_financial_actions_even_if_model_asks(self):
        moves=[{"action":"quote_and_send","args":{"sku":SKU,"proposed_price":4400}},
               {"action":"respond","args":{"text":"공개 재고만 조회했습니다."}}]
        result,actions,seen=self.path(SKU+" 재고 알려주세요",moves)
        self.assertEqual(actions,["prepare","prepared_fallback"])
        self.assertNotIn("data",result)


if __name__=="__main__":
    unittest.main()
