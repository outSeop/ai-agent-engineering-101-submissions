from contextlib import closing
from pathlib import Path
import unittest

from legacy_refund_fixture import existing_refund_case, source_contract


class LegacyFixtureTest(unittest.TestCase):
    def test_schema_and_evidence_match_existing_ledger(self):
        contract = source_contract(Path(__file__).parent)
        with existing_refund_case() as (fixture, case):
            with closing(fixture.open()) as db:
                for name, spec in contract["tables"].items():
                    columns = [dict(r) for r in db.execute(f"PRAGMA table_info({name})")]
                    self.assertEqual(columns, spec["columns"])
                self.assertFalse(db.execute("PRAGMA foreign_key_check").fetchall())
                self.assertEqual(db.execute("SELECT count(*) FROM lot").fetchone()[0], 2)
                self.assertEqual(fixture.sends, 0)
            claim = case["claim"]
            with fixture.patches():
                market = fixture.market()
                with closing(fixture.open()) as db:
                    sale = db.execute("SELECT * FROM sale WHERE id=?", (claim["sale_id"],)).fetchone()
                    verified = fixture.src["refund_cost"](
                        market, sale, claim["incoming"], claim["payer"], claim["fee_payment"],
                    )
                    self.assertEqual(tuple(map(int, (claim["transfer_wei"], claim["fee_wei"], claim["gas_wei"]))),
                                     verified)
                    self.assertEqual(int(claim["wei"]), sum(verified))
        self.assertFalse(case["root"].exists())

