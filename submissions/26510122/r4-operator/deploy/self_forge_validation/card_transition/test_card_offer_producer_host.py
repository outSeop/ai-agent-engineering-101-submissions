from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from unittest import TestCase

from card_offer_producer_host import CardGate, TOOL, load_bundle, produce_view


ORIGIN = next(p/"runtime" for p in Path(__file__).resolve().parents if (p/"kit/agent_kit.py").is_file()) / "class-rebuild-reach-20261125/tools" / TOOL


class CardOfferTest(TestCase):
    def setUp(self):
        self.raw = json.dumps({"name":"outseop-r4","description":"old section\n\nretained policy",
                               "skills":[{},{},{}]}).encode()
        self.offers = [
            {"sku":"G01234567","name":"older name","grade":"C","price":550,"expiry":None,"cost":4},
            {"sku":"G01234568","name":"older name","grade":"A","price":560,"expiry":None,"wallet":"test-private"},
        ]
        self.catalog = [
            {"sku":"G01234567","name":"모의 식품","category":"식품>과일"},
            {"sku":"G01234568","name":"모의 의류","category":"의류>상의"},
        ]

    def test_project_cross_category_and_omit_private_fields(self):
        view = produce_view(self.raw,"old section",self.offers,self.catalog,int(time.time()))
        self.assertEqual([row["category_path"] for row in view["offers"]],[["식품","과일"],["의류","상의"]])
        self.assertNotIn("cost",json.dumps(view))
        self.assertNotIn("test-private",json.dumps(view))
        for row in view["offers"]:
            self.assertIsNone(row["standard_fee_credits"])

    def test_unreviewed_section_and_ambiguous_sku(self):
        with self.assertRaises(ValueError):
            produce_view(self.raw,"absent",self.offers,self.catalog,int(time.time()))
        extra = [dict(self.offers[0],grade="B")]
        view = produce_view(self.raw,"old section",self.offers+extra,self.catalog,int(time.time()))
        self.assertEqual([row["sku"] for row in view["offers"]],["G01234568"])

    def test_unchanged_genuine_stage_persists_only_to_fixture(self):
        scope = {}
        policy = load_bundle(ORIGIN)
        exec(compile(policy["logic.py"],"<pinned card v1>","exec"),scope)
        view = produce_view(self.raw,"old section",self.offers,self.catalog,int(time.time()))
        encoded = json.dumps(view,ensure_ascii=False).encode()
        gate = CardGate(lambda args:{"ok":True,"result":scope["run"](args,None)},view,sha256(encoded).hexdigest())
        old = Path.cwd()
        with TemporaryDirectory() as temp:
            try:
                os.chdir(temp)
                Path("card.json").write_bytes(self.raw)
                Path("host_inputs").mkdir(mode=0o700)
                Path("host_inputs/card_offer_context.json").write_bytes(encoded)
                Path("card_update_stage").mkdir(mode=0o700)
                self.assertEqual(gate.call(TOOL,{"op":"compare"})["status"],"ready")
                self.assertEqual(gate.call(TOOL,{"op":"stage","skus":["G01234567"],
                                                "view_sha256":"fabricated"})["status"],"invalid_selection")
                result = gate.call(TOOL,{"op":"stage","skus":["G01234568","G01234567"]})
                self.assertEqual(result["status"],"staged")
                record = json.loads(next(Path("card_update_stage").glob("*.json")).read_bytes())
                self.assertEqual(record["skus"],["G01234568","G01234567"])
                self.assertEqual(Path("card.json").read_bytes(),self.raw)
            finally:
                os.chdir(old)

