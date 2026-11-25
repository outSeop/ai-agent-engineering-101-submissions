"""Offline manifest and behavioral QA for two immutable classroom-kit prototypes."""
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


SOURCE = Path(os.environ["R4_QA_REFUND_TOOLS"]).resolve(strict=True)
PIN = {
    "refund_verified": (5, "8cb8fb7f7c4f70b53d0de18fcade056a5e36e2e9f64080de75d930ef918a59c3"),
    "refund_reconcile": (1, "0d9739cffdda24c658e58345e21dcaa107ac0a8d905cbd7cb3e5ce857999ce3a"),
}


def load(tool, filename):
    path = SOURCE / tool / (filename + ".py")
    spec = importlib.util.spec_from_file_location(tool + "_" + filename, path)
    module = importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    return module


class QA(TestCase):
    def test_manifests_exact(self):
        for tool, (version, digest) in PIN.items():
            manifest = json.loads((SOURCE / tool / "forge.json").read_text())
            self.assertEqual((manifest["tool"], manifest["version"]), (tool, version))
            self.assertEqual(manifest["sha256"]["logic.py"], digest)
            for name, expected in manifest["sha256"].items():
                self.assertEqual(sha256((SOURCE / tool / name).read_bytes()).hexdigest(), expected)

    def test_unchanged_selftests(self):
        for tool in PIN:
            with self.subTest(tool=tool), TemporaryDirectory() as temp:
                cwd = Path.cwd()
                try:
                    os.chdir(temp)
                    load(tool, "test").test(load(tool, "logic").run, None)
                finally:
                    os.chdir(cwd)

    def test_legacy_state_refused_without_change(self):
        for tool in PIN:
            with self.subTest(tool=tool), existing_refund_case() as (fixture, case):
                candidate = load(tool, "logic")
                candidate.DB = str(fixture.db_path)
                args = {"original_tx": case["claim"]["incoming"]}
                fixture.kit.testing = False
                self.assertEqual(candidate.run(args, fixture.kit)["reason"], "development_only")
                fixture.kit.testing = True
                with fixture.patches():
                    self.assertEqual(candidate.run(args, fixture.kit)["reason"], "refund_state_unavailable")
                with closing(sqlite3.connect(fixture.db_path)) as db:
                    self.assertEqual(db.execute("SELECT status FROM refund").fetchone(), ("requested",))
                    self.assertEqual(db.execute("PRAGMA user_version").fetchone(), (0,))
                    self.assertFalse(db.execute("PRAGMA foreign_key_check").fetchall())
                self.assertEqual(fixture.sends, 0)

    def test_both_reconcile_exact_same_development_attempt(self):
        for tool in PIN:
            for status in ("attempted", "uncertain"):
                with self.subTest(tool=tool, status=status), existing_refund_case() as (fixture, case):
                    self.check_recovery(tool, status, fixture, case)

    def check_recovery(self, tool, status, fixture, case):
        candidate = load(tool, "logic")
        fixture.kit.testing = True
        claim = case["claim"]
        payer, original, amount = claim["payer"], claim["incoming"], int(claim["wei"])
        seller = fixture.kit.address("shop").lower()
        marker = "0x" + sha256(("round4-refund:" + original).encode("ascii")).hexdigest()
        outgoing = fixture.transfer(seller, payer, amount, marker)
        receipt = fixture.receipts[outgoing]
        receipt.update({"from": seller, "to": payer})
        order = dict(shop=fixture.kit.name, seller=seller, buyer=payer,
                     approved_wei=amount, decision="approved", approval_ref="fixture", review_ref="fixture")
        candidate.DB = str(case["root"] / "compat-dev.sqlite3")
        with closing(sqlite3.connect(candidate.DB)) as db:
            db.executescript("""
                PRAGMA user_version=1;
                CREATE TABLE orders (original_tx TEXT PRIMARY KEY, evidence TEXT);
                CREATE TABLE refunds (original_tx TEXT PRIMARY KEY, status TEXT, recipient TEXT,
                    amount_wei TEXT, marker TEXT, refund_tx TEXT UNIQUE);
            """)
            db.execute("INSERT INTO orders VALUES(?,?)", (original, json.dumps(order)))
            db.execute("INSERT INTO refunds VALUES(?,?,?,?,?,NULL)", (original, status, payer, str(amount), marker))
            db.commit()
        base = {"original_tx": original}
        if tool == "refund_verified":
            base["operation"] = "reconcile"

        def mock_post(url, *, json, **kwargs):
            if json["method"] == "eth_chainId":
                return fixture.response(url, {"id": 1, "result": hex(450815)})
            return fixture.post(url, json=json, **kwargs)

        def state():
            with closing(sqlite3.connect(candidate.DB)) as db:
                return db.execute("SELECT status,refund_tx FROM refunds").fetchone()

        with patch.object(candidate.httpx, "get", fixture.get), patch.object(candidate.httpx, "post", mock_post):
            self.assertEqual(candidate.run(base, fixture.kit)["reason"], "refund_transaction_hash_required")
            missing = "0x" + "9" * 64
            self.assertEqual(candidate.run(dict(base, refund_tx=missing), fixture.kit)["status"], "no_change")
            for obj, key, value in ((receipt, "status", "0x0"), (receipt, "blockNumber", "0x1"),
                                    (receipt, "to", "0x" + "a" * 40),
                                    (fixture.txs[outgoing], "input", "0x" + "b" * 64)):
                saved = obj[key]
                obj[key] = value
                self.assertEqual(candidate.run(dict(base, refund_tx=outgoing), fixture.kit)["status"], "no_change")
                self.assertEqual(state(), (status, None))
                obj[key] = saved
            self.assertEqual(candidate.run(dict(base, refund_tx=outgoing), fixture.kit)["status"], "completed")
            self.assertEqual(candidate.run(base, fixture.kit)["status"], "completed")
            self.assertEqual(candidate.run(dict(base, refund_tx=missing), fixture.kit)["reason"],
                             "recorded_refund_hash_mismatch")
        self.assertEqual(state(), ("completed", outgoing))
        self.assertEqual(fixture.sends, 0)


if __name__ == "__main__":
    main()

