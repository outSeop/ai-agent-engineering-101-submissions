import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from unittest import TestCase

from customer_offer_auto_pages import AutoOfferGate, TOOL
from customer_offer_mind_canary import load_bundle


OP=next(p for p in Path(__file__).resolve().parents if (p/"kit/agent_kit.py").exists())


class AutoPages(TestCase):
    def setUp(self):
        temp=TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        cwd=Path.cwd()
        self.addCleanup(os.chdir,cwd)
        os.chdir(temp.name)
        Path("host_inputs").mkdir()
        bundle=load_bundle(OP/"evidence/20261125-customer-offers/sources-v2/tools"/TOOL)
        self.scope={}
        exec(compile(bundle["logic.py"],"<pinned offer v2>","exec"),self.scope)
        self.now=int(time.time())
        self.calls=[]

    def make(self,n):
        rows=[{"unit_ref":f"private-{i}","sku":f"G{i:08x}","name":f"fixture name {i}",
               "category_path":["식품","과일"],"state":"available","grade":"A","price_credits":7000+i,
               "standard_fee_credits":None,"expires_at":self.now+600} for i in range(1,n+1)]
        return {"schema":"outseop-r4.customer-offers.v1","shop":"outseop-r4","observed_at":self.now,
                "valid_until":self.now+150,"units":rows}

    def install(self,view):
        Path("host_inputs/customer_offer_context.json").write_text(json.dumps(view,ensure_ascii=False))

    def invoke(self,args):
        result=self.scope["run"](args,None)
        self.calls.append((args,result))
        return {"ok":True,"result":result}

    def test_keeps_all_46_rows_in_original_order_and_filters(self):
        data=self.make(46)
        self.install(data)
        gate=AutoOfferGate(self.invoke)
        outcome=gate.call(TOOL,{"op":"context","min_remaining_seconds":100})
        self.assertEqual([row[0] for row in outcome["rows"]],[row["sku"] for row in data["units"]])
        self.assertEqual(outcome["total_count"],46)
        self.assertLessEqual(len(json.dumps(outcome,ensure_ascii=False)),5500)
        self.assertGreater(len(self.calls),1)
        for current,previous in zip(self.calls[1:],self.calls):
            self.assertEqual(current[0],previous[1]["next_args"])
            self.assertEqual(current[0]["min_remaining_seconds"],100)
        detail=gate.call(TOOL,{"op":"details","skus":[data["units"][0]["sku"]]})
        self.assertEqual(detail["items"][0]["name"],data["units"][0]["name"])
        self.assertNotIn("unit_ref",json.dumps(detail))

    def test_large_row_fragments_reassembled_but_oversize_detail_refused(self):
        data=self.make(1)
        data["units"][0]["name"]="가"*5800
        self.install(data)
        gate=AutoOfferGate(self.invoke)
        result=gate.call(TOOL,{"op":"context"})
        self.assertEqual(len(result["rows"]),1)
        self.assertTrue(any("row_fragment" in page for _,page in self.calls))
        self.assertEqual(gate.observed[0]["name"],data["units"][0]["name"])
        self.assertEqual(gate.call(TOOL,{"op":"details","skus":[data["units"][0]["sku"]]}),
                         {"error":"full_details_exceed_observation_limit"})

    def test_200_rows_are_not_silently_truncated(self):
        self.install(self.make(200))
        gate=AutoOfferGate(self.invoke)
        result=gate.call(TOOL,{"op":"context"})
        self.assertEqual(result,{"error":"full_offer_table_exceeds_observation_limit","total_count":200})
        self.assertFalse(gate.observed)

    def test_rejects_native_snapshot_change_and_filter_tampering(self):
        data=self.make(46)
        self.install(data)
        def stale(args):
            result=self.invoke(args)
            if len(self.calls)==2:
                result["result"]={"error":"snapshot_changed"}
            return result
        gate=AutoOfferGate(stale)
        self.assertEqual(gate.call(TOOL,{"op":"context"}),{"error":"offer_pages_unavailable"})
        self.assertFalse(gate.observed)
        def broken(args):
            result=self.invoke(args)
            result["result"]["next_args"].pop("min_remaining_seconds")
            return result
        gate=AutoOfferGate(broken)
        self.assertEqual(gate.call(TOOL,{"op":"context","min_remaining_seconds":100}),
                         {"error":"offer_pages_unavailable"})

