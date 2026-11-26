import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

release=Path(__file__).resolve().parents[3]/"deploy/public_catalogue_runtime_v8"
sys.path.insert(0,str(release))
from public_reservation_sidecar import public_stock_state, read, seal
from public_catalogue_snapshot_host import CatalogueError
from broker_public_catalogue_host_candidate import Broker

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

    def path(self, text, moves, *, missing=False, fallback=False, exact=False, remember=None):
        page={"snapshot":"a"*64,"rows":[[ALT,"B",4400]],"columns":["sku","grade","preferred_price"],
              "common":{},"lookup":{},"catalogue":{"source_count":1,"matched_count":1,"hints":{
                  "preparation":{"fits":[{"sku":ALT,"grade":"B","kind":"category_alternative"}],
                                 "requested_sku_missing":missing,"constraints_unverified":False}}}}
        if exact:
            page["rows"][0][0]=SKU
            page["catalogue"]["hints"]["preparation"]["fits"][0].update(sku=SKU,kind="exact_sku")
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

    def test_public_fast_path_denies_financial_actions_even_if_model_asks(self):
        moves=[{"action":"quote_and_send","args":{"sku":SKU,"proposed_price":4400}},
               {"action":"respond","args":{"text":"공개 재고만 조회했습니다."}}]
        result,actions,seen=self.path(SKU+" 재고 알려주세요",moves)
        self.assertEqual(actions,["prepare","prepared_fallback"])
        self.assertNotIn("data",result)


if __name__=="__main__":
    unittest.main()
