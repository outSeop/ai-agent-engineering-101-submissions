from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from class_host_guards import SUMMARY_TOOL, reviewed_call, safe_reviewed_result


class SummaryLane(TestCase):
    def test_args_and_source_are_pinned(self):
        with TemporaryDirectory() as temp:
            directory = Path(temp)
            path = directory / "logic.py"
            path.write_bytes(b"fixture source")
            digest = sha256(path.read_bytes()).hexdigest()
            tools = {SUMMARY_TOOL: {"dir": directory, "perm": {"network": ["market.ourolabs.ai"]}}}
            approvals = {SUMMARY_TOOL: {"sha256": digest}}
            with patch("class_host_guards.SUMMARY_PIN", digest):
                for args in ({}, {"window_seconds": 60}, {"window_seconds": 86400}):
                    self.assertTrue(reviewed_call(tools, approvals, SUMMARY_TOOL, args))
                for args in ({"window_seconds": True}, {"window_seconds": 59},
                             {"window_seconds": 86401}, {"url": "unexpected"}, {"other": 1}):
                    self.assertFalse(reviewed_call(tools, approvals, SUMMARY_TOOL, args))
                path.write_bytes(b"changed")
                self.assertFalse(reviewed_call(tools, approvals, SUMMARY_TOOL, {}))

    def test_output_is_strictly_projected(self):
        expected = {"ok": True, "result": {
            "mode": "public_market_sample", "requested_time": {"start": 20, "end": 90},
            "sample_time": None, "coverage": "partial", "sealed_count": 0, "unclassified_count": 0,
            "by_sku": [{"sku": "G0000001a", "category": "팬", "name": "프라이팬 × 2", "count": 3}],
            "by_category": {"팬": 3},
        }}
        self.assertEqual(safe_reviewed_result(SUMMARY_TOOL, expected), expected)
        safe_error = {"ok":True, "result":{"error":"public_http_error", "status":502}}
        self.assertEqual(safe_reviewed_result(SUMMARY_TOOL, safe_error), safe_error)
        for location, extra in (
            ("envelope", {"printed": "private ledger"}), ("envelope", {"trace": "private tx"}),
            ("result", {"wallet": "private"}), ("row", {"buyer": "private"}),
            ("row", {"amount": 25}), ("result", {"requested_time":{"start":float("inf"), "end":90}}),
            ("row", {"count":True}), ("result", {"error":"unknown error: private"}),
        ):
            altered = deepcopy(expected)
            dest = {"envelope": altered, "result": altered["result"], "row": altered["result"]["by_sku"][0]}
            dest[location].update(extra)
            with self.subTest(location=location, extra=extra):
                self.assertEqual(safe_reviewed_result(SUMMARY_TOOL, altered),
                                 {"ok":False, "error":"public summary response rejected"})

