"""Independent compatibility checks for immutable review prototypes."""
from contextlib import closing
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import patch

from fixture import FakeKit
from legacy_refund_fixture import existing_refund_case


ROOT = Path(os.environ["R4_QA_REFUND_TOOLS"]).resolve(strict=True)
PINS = {
    "refund_breakage_proof": "ec2db2c31473675fafde30516ca4ad31cbc1b6f51ac7bd095575e92b883240a2",
    "refund_review_binding": "cc6784360a5b216f4022875ed3ef18e95fedb459a4d070ca9ed8c26be44f0952",
    "refund_review_intake": "e73c626855539015b3a6bb8ede5bc8364c5fc63af655570d337714085264e991",
}


def load(tool, file="logic"):
    path = ROOT / tool / (file + ".py")
    scope = {}
    exec(compile(path.read_bytes(), str(path), "exec"), scope)
    return scope


class ReviewQA(TestCase):
    def test_official_manifest_and_unchanged_candidate_selftests(self):
        for name, pin in PINS.items():
            with self.subTest(tool=name), TemporaryDirectory() as temp:
                manifest = json.loads((ROOT / name / "forge.json").read_text())
                self.assertEqual((manifest["tool"], manifest["version"]), (name, 1))
                self.assertEqual(manifest["sha256"]["logic.py"], pin)
                for file, digest in manifest["sha256"].items():
                    self.assertEqual(sha256((ROOT / name / file).read_bytes()).hexdigest(), digest)
                cwd = Path.cwd()
                try:
                    os.chdir(temp)
                    kit = FakeKit()
                    kit.testing = True
                    load(name, "test")["test"](load(name)["run"], kit)
                finally:
                    os.chdir(cwd)

    def test_intake_is_minimal_but_canonical_breakage_link_fails(self):
        intake = load("refund_review_intake")
        proof = load("refund_breakage_proof")
        binding = load("refund_review_binding")
        with existing_refund_case() as (fixture, case):
            for helper in (intake, proof):
                helper["FIXTURE"] = str(fixture.db_path)
            binding["DB"] = str(fixture.db_path)
            fixture.kit.testing = True
            summary = intake["run"]({}, fixture.kit)
            self.assertEqual(summary["status"], "review_intake")
            row, = summary["cases"]
            self.assertFalse(row["approval_ready"])
            self.assertEqual(row["period"], "within_48_hours")
            for private in (case["customer_right"], case["claim"]["payer"], case["claim"]["incoming"],
                            case["claim"]["sale_id"], case["claim"]["wei"], case["checkout"]["data"]["checkout_jwt"]):
                self.assertNotIn(private, json.dumps(summary))
            args = {"case_id":row["case_id"]}
            with patch("httpx.get", fixture.get):
                # Real server.py uses the historical shop_url, not registration ID.
                self.assertEqual(proof["run"](args, fixture.kit)["status"], "market_breakage_unverified")
                broken = fixture.entries[-1]["data"]
                broken["shop"] = fixture.kit.name
                self.assertEqual(proof["run"](args, fixture.kit)["status"], "market_breakage_confirmed")
            self.assertEqual(binding["run"](dict(args, operation="prepare"), fixture.kit)["status"],
                             "ledger_unverified")
            self.assertEqual(binding["run"](dict(args, operation="record_decision", decision="approved"),
                                            fixture.kit)["status"], "invalid_arguments")
            fixture.kit.testing = False
            self.assertEqual(intake["run"]({}, fixture.kit)["status"], "development_only")
            self.assertEqual(proof["run"](args, fixture.kit)["status"], "development_only")
            self.assertEqual(binding["run"](dict(args, operation="prepare"), fixture.kit)["status"],
                             "development_only")
            with closing(fixture.open()) as db:
                self.assertEqual(db.execute("SELECT status FROM refund").fetchone()[0], "requested")
                self.assertEqual(db.execute("SELECT count(*) FROM lot WHERE revoked IS NOT NULL").fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT count(*) FROM allocation WHERE status='spent'").fetchone()[0], 1)
            self.assertEqual(fixture.sends, 0)


if __name__ == "__main__":
    main()

