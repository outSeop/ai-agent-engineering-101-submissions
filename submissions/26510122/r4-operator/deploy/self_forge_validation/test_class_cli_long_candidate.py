from pathlib import Path
import sys
from unittest import TestCase
from unittest.mock import patch

import httpx
from class_cli_transport_long_candidate import complete_cli
from serve_class_cli_long_candidate import serve

KIT = Path(__file__).resolve().parents[2] / "kit"
sys.path.insert(0,str(KIT))
import cli_model


class LongBridgeTests(TestCase):
    def test_original_handler_reused_with_loopback_bind_and_310_seconds(self):
        original = cli_model.TIMEOUT
        self.addCleanup(setattr,cli_model,"TIMEOUT",original)
        with patch.object(cli_model.http.server,"ThreadingHTTPServer") as server, patch("sys.argv",sys.argv[:]):
            serve(KIT,"fixture-python fixture.py")
        self.assertEqual(cli_model.TIMEOUT,310)
        server.assert_called_once_with(("127.0.0.1",19001),cli_model.Handler)
        server.return_value.serve_forever.assert_called_once_with()
        self.assertEqual(cli_model.ARGS.cmd,"fixture-python fixture.py")

    @patch("class_cli_transport_long_candidate.httpx.Client")
    def test_default_315_fixed_loopback_no_proxy_no_redirect(self,factory):
        http = factory.return_value.__enter__.return_value
        http.post.return_value.json.return_value = {"choices":[{"message":{"content":"fixture"}}]}
        self.assertEqual(complete_cli([]),"fixture")
        factory.assert_called_once_with(trust_env=False,follow_redirects=False,
                                        timeout=httpx.Timeout(315,connect=4))
        self.assertEqual(http.post.call_args.args,("http://127.0.0.1:19001/v1/chat/completions",))

