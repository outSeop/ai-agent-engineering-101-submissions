"""Launch the immutable official kit under the Round 4 execution boundary."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

import httpx

from managed_runtime import managed_classes
from worker_bootstrap import market_class, registered_party
from dispatcher import Unavailable


SHOP = "outseop-r4"
MARKET = "https://market.ourolabs.ai"


def verify_kit(operator):
    metadata = json.loads((operator / "sources/upstream.json").read_text(encoding="utf-8"))
    expected = {entry["name"]: entry["upstream_git_blob_sha"] for entry in metadata["files"]}
    if len(expected) != 7:
        raise RuntimeError("official kit manifest must contain seven inputs")
    for name, sha in expected.items():
        item = (operator / "kit" / name).read_bytes()
        digest = hashlib.sha1(b"blob " + str(len(item)).encode() + b"\0" + item).hexdigest()
        if digest != sha:
            raise RuntimeError("official kit integrity mismatch: " + name)


def install(official):
    toolbox, mind, app = managed_classes(official)
    official.Toolbox = toolbox
    official.Mind = mind
    official.agent_app = app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["check", "run"])
    parser.add_argument("--operator-dir", type=Path, required=True)
    parser.add_argument("--agent-root", type=Path, required=True)
    access = parser.add_mutually_exclusive_group()
    access.add_argument("--public-url")
    access.add_argument("--tunnel", action="store_true")
    parser.add_argument("--port", type=int)
    parser.add_argument("--owner-file", type=Path)
    args = parser.parse_args()
    operator = args.operator_dir.resolve(strict=True)
    root = args.agent_root.resolve(strict=True)
    verify_kit(operator)
    config = json.loads((root / "agent.json").read_text(encoding="utf-8"))
    if config.get("llm") != {"base": "market"}:
        parser.error("the managed runtime uses the existing class market model only")
    sys.path.insert(0, str(operator / "kit"))
    import agent_kit as official

    install(official)
    if args.action == "check":
        # Loading and checking provenance does not construct a signer or join.
        toolbox = official.Toolbox(root, {"tokens": {}, "addresses": {}})
        toolbox.validate()
        print(json.dumps({"official_kit_files_verified": 7, "a2a": "a2a_info",
                          "class_model": "market", "model_tools": ["shop_info"],
                          "joined_or_started": False}, ensure_ascii=False))
        return
    if not args.owner_file or not (args.public_url or args.tunnel):
        parser.error("approved launch requires --owner-file and --public-url or --tunnel")
    if args.public_url and not args.public_url.startswith("https://"):
        parser.error("the registered endpoint must use HTTPS")
    if not all((root / f"{role}_wallet.key").is_file() for role in ("shop", "buyer")):
        parser.error("existing wallet files are required")
    try:
        registered_party()
    except (Unavailable, httpx.HTTPError, OSError, ValueError, TypeError, AttributeError):
        parser.error("could not verify that the registered Round 4 shop still exists")
    official.mk.Market = market_class(official.mk.Market, root)
    owner = args.owner_file.read_text(encoding="utf-8").strip()
    if not owner:
        parser.error("owner file is empty")
    os.umask(0o077)
    os.environ.pop("MARKET_OWNER", None)
    os.environ["AGENT_LLM_BASE"] = "market"
    os.environ.pop("AGENT_LLM_KEY", None)
    os.environ.pop("AGENT_LLM_MODEL", None)
    official.cmd_run(argparse.Namespace(dir=str(root), market=MARKET, name=SHOP, owner=owner, port=args.port,
                                        public_url=args.public_url, tunnel=args.tunnel, buyer_only=False,
                                        with_buyer=False, app=None))


if __name__ == "__main__":
    main()

