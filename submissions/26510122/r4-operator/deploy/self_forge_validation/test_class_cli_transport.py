import unittest
from unittest.mock import patch

import httpx
from class_cli_transport import complete_cli


class CliTransportTest(unittest.TestCase):
    @patch("class_cli_transport.httpx.Client")
    def test_long_timeout_fixed_loopback_and_no_redirect(self, factory):
        client = factory.return_value.__enter__.return_value
        client.post.return_value.json.return_value = {
            "choices": [{"message": {"content": "fixture reply"}}],
        }
        messages = [{"role": "user", "content": "fixture"}]
        self.assertEqual(complete_cli(messages), "fixture reply")
        factory.assert_called_once_with(
            trust_env=False, follow_redirects=False, timeout=httpx.Timeout(175, connect=4),
        )
        client.post.assert_called_once_with("http://127.0.0.1:19001/v1/chat/completions",
                                            json={"messages": messages, "model": "cli", "max_tokens": 4000})

    @patch("class_cli_transport.httpx.Client")
    def test_empty_reply_fails(self, factory):
        factory.return_value.__enter__.return_value.post.return_value.json.return_value = {
            "choices": [{"message": {"content": " "}}],
        }
        with self.assertRaises(ValueError):
            complete_cli([])

