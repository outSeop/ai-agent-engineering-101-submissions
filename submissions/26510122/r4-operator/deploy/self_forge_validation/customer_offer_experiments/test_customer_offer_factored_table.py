import json
import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase

from customer_offer_auto_pages_factored_candidate import AutoOfferGate
from customer_offer_factored_table import table
from customer_offer_mind_canary import TOOL, load_bundle

OP=next(p for p in Path(__file__).resolve().parents if (p/"kit/agent_kit.py").exists())


def decode(result):
    return [
        result["constant_columns"]|{key:result["lookup"][key][index] if key in result["lookup"] else index
                                   for key,index in zip(result["columns"],row)}
        for row in result["rows"]
    ]


class Factored(TestCase):
    def test_synthetic_70_snapshot_through_genuine_page_calls_simulated_clock(self):
        now=int(time.time())
        units=[{"sku":f"G{i:08x}","name":"정확한 식품 이름 한 가지 "+str(i),"unit_ref":str(i),
                "category_path":["식품","모의"],"state":"available","grade":"C",
                "price_credits":5000+i,"expires_at":now+500+i%5,"standard_fee_credits":None}
               for i in range(70)]
        document={"schema":"outseop-r4.customer-offers.v1","shop":"outseop-r4","observed_at":now,
                  "valid_until":now+150,"units":units}
        observed=document["observed_at"]
        stamp=observed
        scope={}
        bundle=load_bundle(OP/"evidence/20261125-customer-offers/sources-v2/tools"/TOOL)
        exec(bundle["logic.py"],scope)
        scope["time"]=SimpleNamespace(time_ns=lambda:stamp*1000000000)
        def invoke(args):
            nonlocal stamp
            result=scope["run"](args,None)
            if "error" in result:
                self.fail(result["error"])
            stamp+=1
            return {"ok":True,"result":result}
        old=Path.cwd()
        with TemporaryDirectory() as temp:
            try:
                os.chdir(temp)
                Path("host_inputs").mkdir()
                Path("host_inputs/customer_offer_context.json").write_text(json.dumps(document))
                gate=AutoOfferGate(invoke,clock=lambda:stamp)
                result=gate.call(TOOL,{"op":"context"})
            finally:
                os.chdir(old)
        self.assertEqual(result.get("status"),"ready",result.get("error"))
        self.assertLessEqual(len(json.dumps(result,ensure_ascii=False)),5500)
        self.assertGreater(gate.actions[0]["native_page_count"],1)
        rows=decode(result)
        self.assertEqual([row["sku"] for row in rows],[row["sku"] for row in document["units"]])
        for projected,raw in zip(rows,gate.observed):
            self.assertEqual(projected["category_root"],raw["category_path"][0])
            self.assertTrue(projected["name_preview"].startswith(raw["name"][:12]))
            for key in ("state","grade","price_credits","expires_at","remaining_seconds","as_of"):
                self.assertEqual(projected[key],raw[key])

    def test_200_over_limit_is_explicit_no_partial(self):
        rows=[{"sku":f"G{i:08x}","name":"supremely long fixture item name",
               "category_path":["식품","example"],"state":"available","grade":"C","price_credits":100000+i,
               "expires_at":80000+i,"remaining_seconds":600+i,"as_of":79400} for i in range(200)]
        self.assertEqual(table(rows,79400,200),
                         {"error":"full_offer_table_exceeds_observation_limit","total_count":200})

