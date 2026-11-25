from copy import deepcopy
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from unittest import TestCase

from card_apply_authority_host import StageOrigin, normalized_fresh, save_view, sha
from card_apply_v2_inputs import NATIVE, make_authority
from card_offer_producer_host import produce_view


OP = next(p for p in Path(__file__).resolve().parents if (p/"kit/agent_kit.py").is_file())
SOURCE = OP/"runtime/class-rebuild-reach-20261125"


class V2AuthorityTest(TestCase):
    def test_generated_stage_and_apply_on_temporary_card(self):
        origin_now=int(time.time())
        policies={"mileage":"모의 마일리지 설명","wait":"모의 대기 혜택","refund":"모의 환불 심사"}
        original=json.dumps({"name":"outseop-r4","description":"intro\nold block\nretained purchase",
                             "skills":[{"id":"stock"},{"id":"repeat-benefits",
                                       "description":" ".join((policies["mileage"],policies["wait"]))},
                                       {"id":"refund-review","description":policies["refund"]}]},
                            ensure_ascii=False).encode()
        view=produce_view(original,"old block",
                          [{"sku":"G01234567","grade":"C","price":5100,"expiry":None}],
                          [{"sku":"G01234567","name":"모의 상품","category":"식품>과일"}],origin_now)
        old=json.dumps(view,ensure_ascii=False).encode()
        cwd=Path.cwd()
        with TemporaryDirectory() as temp:
            try:
                os.chdir(temp)
                for path in ("host_inputs","card_update_stage","card_publication"):
                    Path(path).mkdir(mode=0o700)
                Path("card_publication/lock").touch(mode=0o600)
                Path("card.json").write_bytes(original)
                Path("host_inputs/card_offer_context.json").write_bytes(old)
                for dependency in NATIVE.values():
                    path=Path(dependency["location"])/"logic.py"
                    path.parent.mkdir(parents=True)
                    data=(SOURCE/path).read_bytes()
                    self.assertEqual(sha(data),dependency["logic_sha256"])
                    path.write_bytes(data)
                stage={}
                exec(Path(NATIVE["stage_representative_card_v1"]["location"]+"/logic.py").read_bytes(),stage)
                skus=["G01234567"]
                start=time.time_ns()
                answer=stage["run"]({"op":"stage","skus":skus,"view_sha256":sha(old)},None)
                origin=StageOrigin.capture(Path("card_update_stage"),answer,old,
                                           NATIVE["stage_representative_card_v1"]["logic_sha256"],start,skus)
                later=origin.mtime_ns//10**9+1
                new=deepcopy(view)
                new["observed_at"]=later
                new["valid_until"]+=1
                new["offers"][0]["valid_until"]+=1
                fresh=json.dumps(normalized_fresh(origin,old,new,original,later*10**9),ensure_ascii=False).encode()
                self.assertRaises(ValueError,make_authority,origin,old,fresh,original,
                                  dict(policies,refund="description-only wording"),None,later)
                authority=make_authority(origin,old,fresh,original,policies,None,later)
                save_view(Path("host_inputs/card_offer_original"),old)
                save_view(Path("host_inputs/card_offer_fresh"),fresh)
                Path("host_inputs/card_publication_authority.json").write_text(json.dumps(authority))
                apply={}
                exec(Path(NATIVE["apply_staged_card_v2"]["location"]+"/logic.py").read_bytes(),apply)
                apply["now"]=lambda:later
                result=apply["run"]({"op":"apply","record_id":origin.record_id},None)
                self.assertEqual(result["status"],"applied",result)
                self.assertEqual(result["card_sha256"],authority["after_sha256"])
            finally:
                os.chdir(cwd)

