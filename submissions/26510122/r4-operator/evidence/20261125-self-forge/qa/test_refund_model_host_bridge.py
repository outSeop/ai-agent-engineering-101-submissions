from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock

from refund_model_host_bridge import review_fixture


class BridgeTest(TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix="r4-refund-model-")
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "refund_binding_fixture.sqlite3"
        self.case = "a" * 64
        self.binding = "b" * 64
        self.summary = {"status":"ready_for_model_review", "case_id":self.case,
                        "reason":"early_market_breakage", "period":"within_48_hours",
                        "evidence":{"checkout":"verified", "original_transfers":"verified",
                                    "refund_terms":"verified", "reason":"market_breakage_confirmed"}}
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript("""
                CREATE TABLE mock_review_preparation(case_id TEXT PRIMARY KEY,binding TEXT NOT NULL);
                CREATE TABLE mock_host_model_decision(case_id TEXT PRIMARY KEY,event_id TEXT UNIQUE NOT NULL,
                    binding TEXT NOT NULL,decision TEXT NOT NULL);
            """)
            db.execute("INSERT INTO mock_review_preparation VALUES (?,?)", (self.case,self.binding))

    def events(self):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute("SELECT * FROM mock_host_model_decision").fetchall()

    def test_writes_only_bound_verified_decision(self):
        model = Mock()
        model.complete.return_value = '{"decision":"approve"}'
        outcome = review_fixture(self.path, self.summary, model, "official test prefix")
        messages = model.complete.call_args.args[0]
        self.assertTrue(messages[0]["content"].startswith("official test prefix"))
        self.assertEqual(set(json.loads(messages[1]["content"])), {
            "case_id","reason","period","checkout_verified","original_transfers_verified",
            "refund_terms_verified","reason_verified",
        })
        self.assertEqual(self.events(), [(self.case,outcome["host_event_id"],self.binding,"approved")])
        with self.assertRaises(ValueError):
            review_fixture(self.path, self.summary, model, "official test prefix")

    def test_needs_evidence_never_creates_approval(self):
        model = Mock()
        model.complete.return_value = '{"decision":"needs_evidence"}'
        self.assertIsNone(review_fixture(self.path,self.summary,model,"test")["host_event_id"])
        self.assertEqual(self.events(), [])

    def test_decline_records_a_nonpayment_decision(self):
        model = Mock()
        model.complete.return_value = '{"decision":"decline"}'
        self.assertEqual(review_fixture(self.path,self.summary,model,"test")["model_decision"],"decline")
        self.assertEqual(self.events()[0][-1],"declined")

    def test_rejects_extra_fields_duplicate_response_and_stale_preparation(self):
        model = Mock()
        with self.assertRaises(ValueError):
            review_fixture(self.path,dict(self.summary, wallet="dummy"),model,"test")
        model.complete.assert_not_called()
        model.complete.return_value = '{"decision":"decline","decision":"approve"}'
        with self.assertRaises(ValueError):
            review_fixture(self.path,self.summary,model,"test")

        def changed(*args, **kwargs):
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute("UPDATE mock_review_preparation SET binding=?", ("c"*64,))
            return '{"decision":"approve"}'
        model.complete.side_effect = changed
        with self.assertRaises(ValueError):
            review_fixture(self.path,self.summary,model,"test")
        self.assertEqual(self.events(), [])

    def test_rejects_any_other_db_path_before_completion(self):
        model = Mock()
        with self.assertRaises(ValueError):
            review_fixture(self.path.parent / "alternate.sqlite3", self.summary, model, "test")
        model.complete.assert_not_called()

