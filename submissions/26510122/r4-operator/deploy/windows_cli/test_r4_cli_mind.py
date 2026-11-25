"""Offline checks for the Windows Python bridge. Never launches Codex."""
import json
import unittest

from r4_cli_mind import verified_reply


class BridgeEventTest(unittest.TestCase):
    def events(self, kind="reasoning"):
        return "\n".join(json.dumps(event) for event in [
            {"type":"thread.started"}, {"type":"turn.started"},
            {"type":"item.completed","item":{"type":"agent_message","text":"earlier commentary"}},
            {"type":"item.completed","item":{"type":kind,"text":"private"}},
            {"type":"item.completed","item":{"type":"agent_message","text":"final answer"}},
            {"type":"turn.completed"},
        ])

    def test_reasoning_is_private_and_final_only(self):
        self.assertEqual(verified_reply(self.events(), "final answer"), "final answer")

    def test_nonfinal_output_rejected(self):
        with self.assertRaises(ValueError):
            verified_reply(self.events(), "earlier commentary")

    def assert_rejected(self, kind):
        with self.assertRaises(ValueError):
            verified_reply(self.events(kind), "final answer")

    def test_command_rejected(self):
        self.assert_rejected("command_execution")

    def test_mcp_rejected(self):
        self.assert_rejected("mcp_tool_call")

    def test_search_rejected(self):
        self.assert_rejected("web_search")

    def test_file_change_rejected(self):
        self.assert_rejected("file_change")

    def test_collaboration_rejected(self):
        self.assert_rejected("collab_tool_call")

    def test_unknown_item_rejected(self):
        self.assert_rejected("unknown")


if __name__ == "__main__":
    unittest.main()

