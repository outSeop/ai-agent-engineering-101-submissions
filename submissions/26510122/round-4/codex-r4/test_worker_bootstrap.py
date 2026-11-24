"""Worker lifecycle, exact party and private token fixture checks."""
from contextlib import redirect_stdout
import io
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase, main
from unittest.mock import patch

import httpx

import worker_bootstrap as boot
from dispatcher import MARKET, SHOP, Unavailable


SECRET = "fixture-token-never-for-output"
URL = "https://outseop-r4.example.invalid"


class Bootstrap(TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix="r4-worker-")
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name)
        self.card = {"name": SHOP, "roles": ["shop"], "wallets": {"shop": boot.EXPECTED_WALLET},
                     "supportedInterfaces": [{"url": URL + "/", "protocolBinding": "JSONRPC"}]}
        self.registry = {"round": 4, "shops": [{"name": SHOP, "pubkey": boot.EXPECTED_WALLET, "url": URL}],
                         "agents": [{"name": SHOP, "roles": ["shop"], "card": URL + "/.well-known/agent-card.json"}]}
        self.fetches = []

    def get(self, url, headers=None, **kwargs):
        self.fetches.append(url)
        body = self.card if url == boot.LOCAL_CARD else self.registry
        if url == MARKET + "/api/inventory":
            self.assertEqual(headers, {"authorization": f"Bearer {SECRET}"})
            body = {"round": 4, "wallet": boot.EXPECTED_WALLET, "units": []}
        return httpx.Response(200, request=httpx.Request("GET", url), json=body)

    def test_main_exports_exact_token_atomically_and_reuses_official_join(self):
        calls = []
        class OfficialFixtureMarket:
            def join(self, role, name, key, url, tries):
                calls.append((role, name, key.address, url, tries))
                return {"name": name, "role": role, "round": 4, "token": SECRET}
        derived = boot.market_class(OfficialFixtureMarket, self.path)()
        wallet = SimpleNamespace(address=boot.EXPECTED_WALLET)
        output = io.StringIO()
        with patch.object(httpx, "get", self.get), redirect_stdout(output):
            with self.assertRaises(Unavailable):
                derived.join("shop", "new-party", wallet, URL)
            with self.assertRaises(Unavailable):
                derived.join("shop", SHOP, SimpleNamespace(address="0x" + "1"*40), URL)
            self.registry["agents"] = []
            with self.assertRaises(Unavailable):
                derived.join("shop", SHOP, wallet, URL)
            self.registry["agents"] = [{"name": SHOP, "roles": ["shop"], "card": URL + "/.well-known/agent-card.json"}]
            self.assertEqual(derived.join("shop", SHOP, wallet, URL)["token"], SECRET)
        self.assertEqual(calls, [("shop", SHOP, boot.EXPECTED_WALLET, URL, 1)])
        path = boot.token_file(self.path)
        self.assertEqual(path.read_text().strip(), SECRET)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
        boot.export_token(self.path, "updated-fixture-token")
        self.assertEqual(path.read_text().strip(), "updated-fixture-token")
        self.assertNotIn(SECRET, output.getvalue())

    def test_inactive_main_does_not_touch_network_or_credentials(self):
        with patch.object(boot, "active", return_value=False), patch.object(httpx, "get", self.get):
            with self.assertRaises(Unavailable):
                boot.prepare(self.path, attempts=1)
        self.assertEqual(self.fetches, [])
        self.assertFalse(boot.token_file(self.path).exists())

    def test_local_card_and_live_registry_and_authenticated_inventory_match(self):
        boot.export_token(self.path, SECRET)
        with patch.object(boot, "active", return_value=True), patch.object(httpx, "get", self.get):
            self.assertEqual(boot.prepare(self.path, attempts=1).shop_url, URL)
        self.assertEqual(self.fetches, [boot.LOCAL_CARD, MARKET + "/api/shops", MARKET + "/api/inventory"])

    def test_local_or_registry_mismatch_rejected_without_token_use(self):
        with patch.object(boot, "active", return_value=True), patch.object(httpx, "get", self.get):
            for field, value in (("name", "other-party"), ("wallets", {"shop": "0x" + "1"*40}),
                                 ("supportedInterfaces", [{"url": "http://127.0.0.1:18805/", "protocolBinding": "JSONRPC"}])):
                original = self.card[field]
                self.card[field] = value
                with self.assertRaises(Unavailable):
                    boot.prepare(self.path, attempts=1)
                self.card[field] = original
            self.registry["shops"][0]["url"] = "https://different.example.invalid"
            with self.assertRaises(Unavailable):
                boot.prepare(self.path, attempts=1)
        self.assertNotIn(MARKET + "/api/inventory", self.fetches)

    def test_token_permissions_required_and_symlink_not_followed(self):
        boot.export_token(self.path, SECRET)
        path = boot.token_file(self.path)
        path.chmod(0o644)
        with patch.object(boot, "active", return_value=True), patch.object(httpx, "get", self.get):
            with self.assertRaises(Unavailable):
                boot.prepare(self.path, attempts=1)
        self.assertNotIn(MARKET + "/api/inventory", self.fetches)
        real = self.path / "other"
        real.write_text("protected unrelated value")
        path.unlink()
        path.symlink_to(real)
        boot.export_token(self.path, SECRET)
        self.assertFalse(path.is_symlink())
        self.assertEqual(real.read_text(), "protected unrelated value")

    def test_market_failure_has_bounded_retries_and_no_body_in_output(self):
        def fail(url, **_):
            self.fetches.append(url)
            return httpx.Response(503, request=httpx.Request("GET", url), text=SECRET)
        out = io.StringIO()
        with patch.object(boot, "active", return_value=True), patch.object(httpx, "get", fail), \
             redirect_stdout(out):
            with self.assertRaisesRegex(Unavailable, "not ready"):
                boot.prepare(self.path, attempts=2, interval=0)
        self.assertEqual(len(self.fetches), 2)
        self.assertNotIn(SECRET, out.getvalue())


if __name__ == "__main__":
    main(verbosity=2)

