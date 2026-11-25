"""Run reconciliation for the existing shop using the main process's protected token."""
import argparse
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import time
from urllib.parse import urlsplit

import httpx

import dispatcher as shop
from refund_admin import OperatorKit, worker


MAIN = "ourolabs-market-r4.service"
LOCAL_CARD = "http://127.0.0.1:18805/.well-known/agent-card.json"
EXPECTED_WALLET = "0x5fdc134d790efb72df1bbb922f2b49fcade349c6"


def token_file(root):
    return root / ".kit" / "worker-token"


def export_token(root, token):
    if not isinstance(token, str) or not 16 <= len(token) <= 1024 or not token.isascii() or not token.isprintable():
        raise shop.Unavailable("invalid worker credential")
    target = token_file(root)
    folder = target.parent
    folder.mkdir(mode=0o700, exist_ok=True)
    info = folder.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise shop.Unavailable("invalid private credential directory")
    folder.chmod(0o700)
    fd, temporary = tempfile.mkstemp(dir=folder, prefix=".worker-token-")
    try:
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(token + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def market_class(original, root):
    class ExportingMarket(original):
        def join(self, role, name, key, url=None, tries=6):
            if role != "shop" or name != shop.SHOP or shop.address(key.address) != EXPECTED_WALLET:
                raise shop.Unavailable("unexpected managed shop wallet or identity")
            # Recheck the public registry immediately before the official POST.
            # The market does not offer an atomic existing-only join.
            registered_party()
            result = super().join(role, name, key, url, tries=1)
            if result.get("name") != shop.SHOP or result.get("role") != "shop" or result.get("round") != 4:
                raise shop.Unavailable("market returned an unexpected party")
            try:
                export_token(root, result.get("token"))
            except (shop.Unavailable, OSError):
                # Export failure does not discard the main party's valid token.
                print("R4 worker credential export unavailable", flush=True)
            return result
    return ExportingMarket


def active():
    result = subprocess.run(["systemctl", "--user", "is-active", "--quiet", MAIN],
                            timeout=3, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return result.returncode == 0


def get(url):
    response = httpx.get(url, timeout=4, trust_env=False, follow_redirects=False)
    response.raise_for_status()
    return response.json()


def registered_party():
    registry = get(shop.MARKET + "/api/agents")
    rows = [row for row in registry.get("agents", []) if row.get("name") == shop.SHOP]
    if (registry.get("round") != 4 or len(rows) != 1 or "shop" not in rows[0].get("roles", [])
            or not str(rows[0].get("card") or "").startswith("https://")):
        raise shop.Unavailable("no existing Round 4 shop registration")
    return rows[0]


def card_url(card):
    if card.get("name") != shop.SHOP or "shop" not in card.get("roles", []):
        raise shop.Unavailable("local card does not represent the existing shop")
    if shop.address(card.get("wallets", {}).get("shop")) != EXPECTED_WALLET:
        raise shop.Unavailable("local card shop wallet does not match")
    interfaces = card.get("supportedInterfaces", [])
    if len(interfaces) != 1 or interfaces[0].get("protocolBinding") != "JSONRPC":
        raise shop.Unavailable("local card interface differs")
    url = interfaces[0].get("url", "").rstrip("/")
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.query or parts.fragment:
        raise shop.Unavailable("local card has no validated HTTPS interface")
    return url


def validated_kit(root):
    if not active():
        raise shop.Unavailable("main R4 service is inactive")
    url = card_url(get(LOCAL_CARD))
    registry = get(shop.MARKET + "/api/shops")
    matches = [row for row in registry.get("shops", []) if row.get("name") == shop.SHOP]
    if (registry.get("round") != 4 or len(matches) != 1
            or matches[0].get("url", "").rstrip("/") != url
            or shop.address(matches[0].get("pubkey")) != EXPECTED_WALLET):
        raise shop.Unavailable("market registration does not match local card and wallet")
    path = token_file(root)
    owner = os.getuid()
    info = path.lstat()
    parent = path.parent.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != owner or stat.S_IMODE(info.st_mode) != 0o600
            or not stat.S_ISDIR(parent.st_mode) or parent.st_uid != owner or stat.S_IMODE(parent.st_mode) != 0o700):
        raise shop.Unavailable("private worker credential is unavailable")
    kit = OperatorKit(url, EXPECTED_WALLET, path)
    shop.Market(kit).inventory()
    if not active():
        raise shop.Unavailable("main R4 service stopped during validation")
    return kit


def prepare(root, attempts=12, interval=4):
    for count in range(attempts):
        if not active():
            raise shop.Unavailable("main R4 service is inactive")
        try:
            return validated_kit(root)
        except (shop.Unavailable, OSError, httpx.HTTPError, ValueError, AttributeError, TypeError, KeyError):
            if count + 1 < attempts:
                time.sleep(interval)
    raise shop.Unavailable("R4 main card, registration, or credential was not ready")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        root = args.agent_root.resolve(strict=True)
        kit = prepare(root)
        db = shop.open_db(root / shop.DB, EXPECTED_WALLET)
        try:
            worker(db, kit, 10)
        finally:
            db.close()
    except KeyboardInterrupt:
        return
    except (shop.Unavailable, OSError, subprocess.SubprocessError):
        parser.exit(2, "R4 queue and settlement worker could not validate the running shop\n")


if __name__ == "__main__":
    main()

