import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time
from unittest import TestCase
from unittest.mock import Mock

from customer_offer_mind_canary import TOOL, OfferGate, load_bundle, make_context, safe_dialogue

OP=next(p for p in Path(__file__).resolve().parents if (p/"kit/agent_kit.py").exists())
sys.path.insert(0,str(OP/"kit"))
import agent_kit


class CustomerOfferCanaryTest(TestCase):
    def test_real_generated_pagination_through_official_mind_mock_model(self):
        source=load_bundle(OP/"evidence/20261125-customer-offers/sources-v2/tools"/TOOL)
        scope={}
        exec(compile(source["logic.py"],"<pinned reader>","exec"),scope)
        offers=[{"sku":f"G{i:08x}","_unit":f"private-unit-{i}","grade":"C","price":7000+i,"expiry":int(time.time())+600}
                for i in range(1,47)]
        catalog=[{"sku":r["sku"],"name":f"모의 식품 {i}","category":"식품>과일"} for i,r in enumerate(offers,1)]
        view=make_context(offers,catalog,int(time.time()))
        self.assertEqual(len(view["units"]),46)
        self.assertEqual(view["valid_until"]-view["observed_at"],150)
        self.assertNotIn("private-unit",json.dumps(view))
        old=Path.cwd()
        with TemporaryDirectory() as temp:
            try:
                os.chdir(temp)
                Path("host_inputs").mkdir()
                Path("logs").mkdir()
                Path("host_inputs/customer_offer_context.json").write_text(json.dumps(view))
                calls=[]
                def invoke(args):
                    result=scope["run"](args,None)
                    calls.append((args.copy(),result))
                    return {"ok":True,"result":result}
                gate=OfferGate(invoke)
                model=Mock()
                event=agent_kit.Event("a2a","synthetic-customer","식품 등급과 가격을 알려 주세요")
                model.complete.side_effect=[json.dumps(move) for move in [
                    {"action":TOOL,"args":{"op":"context","min_remaining_seconds":100}},
                    {"action":TOOL,"args":{"op":"next"}},
                    {"action":"reply","args":{"to":event.id,"text":"G00000001 모의 식품 1은 C등급이며 7,001 크레딧입니다."}},
                    {"action":"sleep","args":{"seconds":30}},
                ]]
                mind=agent_kit.Mind(Path(temp),{"max_steps":5},model,gate,{"name":"outseop-r4","market":"fixture"},[])
                mind.pending[event.id]=event
                mind.run_once([event])
                self.assertEqual(calls[1][0],calls[0][1]["next_args"])
                self.assertEqual(calls[1][0]["min_remaining_seconds"],100)
                report=safe_dialogue(event.text,gate,event.answer)
                self.assertEqual(report["status"],"synthetic_dialogue_complete")
                self.assertEqual(report["selected_public_products"][0]["sku"],"G00000001")
                self.assertNotIn("unit_ref",json.dumps(report))
            finally:
                os.chdir(old)

    def test_extra_args_and_sensitive_reply_rejected(self):
        gate=OfferGate(lambda _:None)
        self.assertEqual(gate.call(TOOL,{"op":"next","offset":40}),{"error":"invalid_arguments"})
        self.assertEqual(gate.call(TOOL,{"op":"context","path":"private"}),{"error":"invalid_arguments"})
        self.assertEqual(safe_dialogue("test",gate,{"reply":"0x"+"a"*40})["status"],"no_safe_public_reply")
        self.assertEqual(safe_dialogue("test",gate,{"reply":"test","data":{"wallet":"private"}})["status"],
                         "no_safe_public_reply")

