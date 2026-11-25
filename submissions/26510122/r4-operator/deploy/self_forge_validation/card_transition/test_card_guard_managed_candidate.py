import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from card_compact_view import compact_card_candidates
from managed_runtime_card_guard_candidate import card_publisher_allowed


ORIGIN = next(p/"runtime" for p in Path(__file__).resolve().parents if (p/"kit/agent_kit.py").is_file())/"class-rebuild-reach-20261125/tools/publish_shop_info"


class CardBoundary(TestCase):
    def test_guard_registry_accepts_only_exact_new_forge(self):
        self.assertTrue(card_publisher_allowed({"perm":{"write":["card.json"]}}))
        with TemporaryDirectory() as temp:
            path=Path(temp)
            for name in ("logic.py","test.py","permission.yml","forge.json"):
                (path/name).write_bytes((ORIGIN/name).read_bytes())
            perm={"write":["card_handoff_selftest"],"pay_limit":0}
            tool={"dir":path,"perm":perm}
            self.assertTrue(card_publisher_allowed(tool))
            for name in ("wallet","identity","exec","handles","network"):
                self.assertFalse(card_publisher_allowed({**tool,"perm":{**perm,name:["unapproved"]}}))
            self.assertFalse(card_publisher_allowed({**tool,"perm":{**perm,"write":["card_handoff_selftest","card.json"]}}))
            (path/"logic.py").write_text("unexpected")
            self.assertFalse(card_publisher_allowed(tool))

    def test_full_46_row_menu_under_official_limit_without_reordering(self):
        rows=[{"sku":f"G{i:08x}","name":"모의 상품"*30,"category_path":["공개 분류"*30,"하위 분류"],
               "grade":"C","price_credits":999999} for i in range(46,0,-1)]
        result=compact_card_candidates(rows)
        self.assertEqual([r[0] for r in result["candidates"]],[x["sku"] for x in rows])
        self.assertLessEqual(len(json.dumps(result,ensure_ascii=False)),5500)
        self.assertTrue(result["name_and_category_may_be_abbreviated"])
        self.assertTrue(all(r[1].endswith("…") for r in result["candidates"]))

