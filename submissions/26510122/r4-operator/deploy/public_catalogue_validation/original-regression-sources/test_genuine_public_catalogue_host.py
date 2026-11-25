"""Offline synthetic host integration using the sealed native catalogue."""
from importlib import import_module
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time
from unittest import TestCase
from unittest.mock import Mock

from bounded_public_catalogue_host import BoundedPublicCatalogue, instruction_from
from broker_public_catalogue_host_candidate import Broker, mask
from public_catalogue_protocol import CatalogueProtocol
from public_catalogue_request_host import ScopedPublicCatalogue
from public_catalogue_snapshot_host import verify_snapshot

HERE=Path(__file__).resolve().parent
OP=HERE.parents[3]
RELEASE=HERE.parent/"validation/public_catalogue_runtime_v1"


class GenuineCatalogueTests(TestCase):
    def test_117_public_rows_reach_genuine_render_with_no_old_builder(self):
        explicit=os.environ.get("R4_CATALOGUE_TEST_RELEASE")
        release=Path(explicit) if explicit else RELEASE
        if not (release/"MANIFEST.json").is_file():
            self.skipTest("independently pinned catalogue candidate not yet available")
        files=json.loads((release/"MANIFEST.json").read_bytes())["file_sha256"]
        pins={key.removeprefix("catalogue/"):digest for key,digest in files.items() if key.startswith("catalogue/")}
        self.assertFalse(any("builder" in key for key in files))
        kit=OP/"kit"
        sys.path.insert(0,str(kit))
        try:
            official=import_module("agent_kit")
        finally:
            sys.path.pop(0)
        now=int(time.time())
        units=[{"unit_ref":f"{i:032x}","sku":f"G{i:08x}","name":f"일반 가상 식품 {i}",
                "category_path":["식품","모의"],"state":"available","grade":"B",
                "price_credits":43900+i,"standard_fee_credits":None,"expires_at":now+900}
               for i in range(1,118)]
        sample={"schema":"outseop-r4.customer-offers.v1","shop":"outseop-r4","observed_at":now,
                "valid_until":now+150,"units":units}
        raw=(json.dumps(sample,ensure_ascii=False,indent=2)+chr(10)).encode()
        sku=units[-1]["sku"]
        legacy=Mock(return_value={"outcome":"context","inventory":[{"sku":item["sku"]} for item in units[:30]],
                                  "verified_account":False,"redeemable_mileage":0,"wait":None,"prior_offer":None})
        model=Mock()
        seen=[]
        def decide(messages,*,timeout):
            self.assertTrue(0<timeout<=35)
            context=json.loads(messages[-1]["content"])["verified_context"]
            seen.append(context["public_catalogue"])
            self.assertEqual(context["inventory"],[])
            return json.dumps({"action":"render_public_products","args":{"items":[{"sku":sku,"grade":"B"}]}})
        model.complete.side_effect=decide
        with TemporaryDirectory() as folder:
            source=release/"catalogue"
            self.assertIsInstance(instruction_from(source,pins,official),str)
            invoke=BoundedPublicCatalogue(source,kit,Path(folder),pins)
            scoped=ScopedPublicCatalogue(lambda:(raw,verify_snapshot(raw)),invoke,CatalogueProtocol(mask),"catalogue")
            flow=Broker(legacy,model,max_steps=3,seconds=65,model_seconds=35,catalogue=scoped)
            answer=flow.handle(f"{sku} 등급, 가격, 남은 시간 문의만 합니다.")
            self.assertFalse(list(Path(folder).iterdir()))
        self.assertIn(sku,answer["reply"])
        self.assertIn("44,017",answer["reply"])
        self.assertFalse(answer.get("data"))
        legacy.assert_called_once()
        model.complete.assert_called_once()
        self.assertEqual(seen[0]["catalogue"]["source_count"],117)
        self.assertEqual(seen[0]["catalogue"]["returned_count"],1)

