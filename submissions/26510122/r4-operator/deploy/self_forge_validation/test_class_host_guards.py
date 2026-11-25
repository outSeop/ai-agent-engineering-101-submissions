from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from class_host_guards import OfflineForgeSubprocess, PUBLIC_SITE, reviewed_call


class GuardTests(TestCase):
    def test_source_and_exact_url_and_policy_are_required(self):
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            source = directory / "logic.py"
            source.write_bytes(b"sample")
            url = PUBLIC_SITE + "/entities/bank/.well-known/agent-card.json"
            tool = "read_market_cards"
            permissions = {"network": ["market.ourolabs.ai"]}
            tools = {tool: {"dir": directory, "perm": permissions}}
            approvals = {tool: {"sha256": sha256(b"sample").hexdigest(), "urls": [url]}}
            self.assertTrue(reviewed_call(tools, approvals, tool, {"url": url}))
            self.assertFalse(reviewed_call(tools, approvals, tool, {"url": url + "?wallet=fixture"}))
            self.assertFalse(reviewed_call(tools, approvals, tool, {"url": PUBLIC_SITE + "/api/ledger"}))
            self.assertFalse(reviewed_call(tools, approvals, "forged_poster", {"url": url}))
            permissions["wallet"] = ["pay"]
            self.assertFalse(reviewed_call(tools, approvals, tool, {"url": url}))
            del permissions["wallet"]
            source.write_bytes(b"changed")
            self.assertFalse(reviewed_call(tools, approvals, tool, {"url": url}))

    def test_only_test_uses_namespace_and_unexpected_command_rejected(self):
        with patch("class_host_guards.subprocess.run") as spawn:
            command = ["/python", "-I", "/kit/forge_runner.py", "/root/candidate", "test"]
            OfflineForgeSubprocess.run(command, timeout=10)
            spawn.assert_called_once_with(["/usr/bin/unshare", "-Urn", "--", *command], timeout=10)
            spawn.reset_mock()
            with self.assertRaises(ValueError):
                OfflineForgeSubprocess.run(["/bin/sh", "-c", "fixture"])
            spawn.assert_not_called()

