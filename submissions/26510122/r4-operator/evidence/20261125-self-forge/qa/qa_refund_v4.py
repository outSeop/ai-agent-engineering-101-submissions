"""Offline QA for immutable official refund_verified v4."""
from contextlib import closing
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import patch

from legacy_refund_fixture import existing_refund_case


CANDIDATE = Path(os.environ["R4_QA_REFUND_CANDIDATE"]).resolve(strict=True)
PIN = "e7df56f3d4b7901babe9787599b8d4148a201e31118879eab87515f9c5234362"


def load(name):
    spec = importlib.util.spec_from_file_location("refund_v4_" + name, CANDIDATE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    exec(compile((CANDIDATE / (name + ".py")).read_bytes(), spec.origin, "exec"), module.__dict__)
    return module


class QA(TestCase):
    def test_manifest_is_exact_official_v4(self):
        manifest = json.loads((CANDIDATE / "forge.json").read_text())
        self.assertEqual(manifest["tool"], "refund_verified")
        self.assertEqual(manifest["version"], 4)
        self.assertEqual(manifest["sha256"]["logic.py"], PIN)
        for name, expected in manifest["sha256"].items():
            self.assertEqual(sha256((CANDIDATE / name).read_bytes()).hexdigest(), expected)

    def test_candidate_selftest_rerun_without_real_network(self):
        cwd = Path.cwd()
        with TemporaryDirectory() as temp:
            try:
                os.chdir(temp)
                load("test").test(load("logic").run, None)
            finally:
                os.chdir(cwd)

    def test_receipt_requires_exact_outgoing_broadcast_properties(self):
        with existing_refund_case() as (fixture, case):
            candidate = load("logic")
            claim = case["claim"]
            payer = claim["payer"]
            sender = fixture.kit.address("shop").lower()
            marker = claim["marker"]
            amount = int(claim["wei"])
            outgoing = fixture.transfer(sender, payer, amount, marker)
            receipt = fixture.receipts[outgoing]
            receipt.update({"from": sender, "to": payer})
            tx = fixture.txs[outgoing]
            with patch.object(candidate.httpx, "post", fixture.post):
                self.assertGreater(candidate.transfer(outgoing, sender, payer, amount, marker), 0)
                for target, key, bad in (
                    (receipt, "status", "0x0"), (receipt, "blockHash", "0x" + "a" * 64),
                    (receipt, "to", "0x" + "f" * 40), (tx, "value", hex(amount + 1)),
                    (tx, "input", "0x" + "b" * 64),
                ):
                    with self.subTest(field=key):
                        original = target[key]
                        target[key] = bad
                        try:
                            with self.assertRaises(candidate.Refusal):
                                candidate.transfer(outgoing, sender, payer, amount, marker)
                        finally:
                            target[key] = original

    def test_legacy_requested_case_cannot_be_processed_by_candidate(self):
        with existing_refund_case() as (fixture, case):
            module = load("logic")
            claim = case["claim"]
            args = {"original_tx": claim["incoming"]}
            fixture.kit.testing = False
            self.assertEqual(module.run(args, fixture.kit)["reason"], "development_only")
            fixture.kit.testing = True
            module.DB = str(fixture.db_path)
            with fixture.patches():
                result = module.run(args, fixture.kit)
            self.assertEqual(result["reason"], "refund_state_unavailable")
            with closing(sqlite3.connect(fixture.db_path)) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone(), (0,))
                self.assertEqual(db.execute("SELECT status FROM refund").fetchone(), ("requested",))
                self.assertFalse(db.execute("PRAGMA foreign_key_check").fetchall())
            self.assertEqual(fixture.sends, 0)


if __name__ == "__main__":
    main()

