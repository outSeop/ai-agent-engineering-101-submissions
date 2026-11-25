import json
from pathlib import Path
from unittest import TestCase

from customer_offer_auto_pages_indexed import indexed_table

OP=next(p for p in Path(__file__).resolve().parents if (p/"kit/agent_kit.py").exists())


class IndexedTable(TestCase):
    def verify(self,rows,budget=5500):
        result=indexed_table(rows,rows[0]["as_of"],len(rows))
        self.assertEqual(result["status"],"ready")
        self.assertLessEqual(len(json.dumps(result,ensure_ascii=False)),budget)
        self.assertEqual(result["total_count"],len(rows))
        self.assertEqual(len(result["rows"]),len(rows))
        groups=result["lookup"]
        for display,original in zip(result["rows"],rows):
            self.assertEqual((display[0],groups["c"][display[2]],groups["s"][display[3]],
                              display[4],display[5],groups["e"][display[6]],
                              groups["r"][display[7]],groups["t"][display[8]]),
                             (original["sku"],original["category_path"][0],original["state"],
                              original["grade"],original["price_credits"],original["expires_at"],
                              original["remaining_seconds"],original["as_of"]))
            self.assertTrue(display[1].startswith(original["name"][:12]))

    def test_synthetic_distinct_time_state_and_200_row_capacity_refusal(self):
        rows=[{"sku":f"G{i:08x}","name":"정확한 상품 이름 일부를 표시합니다",
               "category_path":["식품" if i%2 else "생활용품","example"],"state":"reserved" if i%2 else "available",
               "grade":"C","price_credits":100000+i,"expires_at":None if i%2 else 80000,
               "remaining_seconds":None if i%2 else 600-i%7,"as_of":79400+i%7} for i in range(200)]
        self.verify(rows[:67])
        self.assertEqual(indexed_table(rows,79400,200),{"error":"full_offer_table_exceeds_observation_limit","total_count":200})

