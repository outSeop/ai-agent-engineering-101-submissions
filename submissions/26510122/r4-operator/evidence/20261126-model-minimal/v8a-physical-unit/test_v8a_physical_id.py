"""Synthetic canonical-shaped unit IDs for the actual public sidecar helper."""
import json
from pathlib import Path
import sqlite3
import sys
import unittest
from contextlib import closing

op=Path(__file__).resolve().parents[3]
v8a=op/"deploy/public_catalogue_runtime_v8a"
sys.path.insert(0,str(v8a))
from public_reservation_sidecar import PHYSICAL_UNIT,physical_unit,public_stock_state


class PhysicalIdTest(unittest.TestCase):
    def test_original_dispatcher_grammar(self):
        source=(op.parent/"round-4/codex-r4/dispatcher.py").read_text()
        quote=chr(34)
        self.assertIn("SKU = re.compile(r"+quote+PHYSICAL_UNIT.pattern+quote+")",source)
        self.assertTrue(physical_unit("u-200000000000"))
        self.assertTrue(physical_unit("F00000001"))
        self.assertFalse(physical_unit("u/200000000001"))
        self.assertFalse(physical_unit("u-"+"a"*63))

    def test_reserved_beyond_first_page_and_batch_mirror(self):
        inventory=[{"sku":f"G{i:08x}","unit":f"u-{i:012d}","grade":"C","expires_at":300}
                   for i in range(403)]
        inventory.append({"sku":"G00000200","unit":"F00000001","grade":"A","expires_at":None})
        with closing(sqlite3.connect(":memory:")) as db:
            db.execute("CREATE TABLE sale(unit, status, grade, owner, jwt)")
            for i in (73,402):
                db.execute("INSERT INTO sale VALUES(?,?,?,?,?)",
                           (inventory[i]["unit"],"issued","B","fixture-owner","fixture-private-jwt"))
            rows=public_stock_state(db,inventory,100,preferred_price=lambda row:2178 if row["grade"]=="C" else 4000)
            self.assertEqual(len(rows),404)
            reserved=[row for row in rows if row["stock_status"]=="reserved_pending"]
            self.assertEqual([row["sku"] for row in reserved],[inventory[i]["sku"] for i in (73,402)])
            self.assertTrue(all(row["grade"]=="C" and row["preferred_price"]==2178 for row in reserved))
            self.assertEqual(next(row for row in rows if row["sku"]=="G00000200")["stock_status"],"available")
            encoded=json.dumps(rows)
            self.assertNotIn(inventory[73]["unit"],encoded)
            self.assertNotIn("fixture-private",encoded)

    def test_nonempty_unprojectable_rejected(self):
        with closing(sqlite3.connect(":memory:")) as db:
            db.execute("CREATE TABLE sale(unit,status)")
            row={"sku":"not-a-public-sku","unit":"u-200000000000","grade":"C","expires_at":None}
            with self.assertRaises(ValueError):
                public_stock_state(db,[row],100)
            self.assertEqual(public_stock_state(db,[],100),[])


if __name__=="__main__":
    unittest.main()
