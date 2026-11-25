"""Launch the immutable official kit under the Round 4 execution boundary."""
import argparse
import hashlib
import json
import os
import stat
from pathlib import Path
import sys

import httpx

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


def install(official, *, enable_stock=False, stock_lines=10, native_factory=None, public_options=None, catalogue_options=None):
    from managed_runtime import managed_classes
    if catalogue_options is not None:
        import broker_public_catalogue_host_candidate as catalogue_broker
        import managed_runtime_public_catalogue_host_candidate as catalogue_managed
        catalogue_managed.Broker = catalogue_broker.Broker
        toolbox, mind, app = catalogue_managed.managed_classes(
            official,enable_stock=enable_stock,stock_lines=stock_lines,**catalogue_options)
    elif public_options is not None:
        import broker_public_response_host_candidate as public_broker
        import managed_runtime_public_response_host_candidate as public_managed
        public_managed.Broker = public_broker.Broker
        toolbox, mind, app = public_managed.managed_classes(
            official,enable_stock=enable_stock,stock_lines=stock_lines,**public_options)
    elif native_factory is None:
        toolbox, mind, app = managed_classes(official,enable_stock=enable_stock,stock_lines=stock_lines)
    else:
        toolbox, mind, app = managed_classes(official,enable_stock=enable_stock,stock_lines=stock_lines,
                                             native_customer_context_factory=native_factory)
    official.Toolbox = toolbox
    official.Mind = mind
    official.agent_app = app


NATIVE_MANIFEST_SHA="f4b12edb4f7ba76e9690c71a146a49651dd05105e9887393c52b9c700361af11"
MANAGED_NATIVE_SHA="7504c9ed720d7b9a62bb36ddf34044bd0ce8b07625f15c04a94dc255284ff4d8"


def protected_native(path):
    info=path.lstat()
    if (path.resolve()!=path or not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid()
        or info.st_nlink!=1 or info.st_mode & 0o022):
        raise RuntimeError("unprotected native context artifact")
    return path.read_bytes()


def load_native_factory(operator,root):
    if root!=operator.parent/"round-4":
        raise RuntimeError("native customer context must use the registered shop root")
    freeze=operator/"deploy/native_customer_context_runtime_v2"
    meta=protected_native(freeze/"MANIFEST.json")
    if hashlib.sha256(meta).hexdigest()!=NATIVE_MANIFEST_SHA:
        raise RuntimeError("frozen native context manifest changed")
    for name,digest in json.loads(meta)["file_sha256"].items():
        relative=Path(name)
        if relative.is_absolute() or ".." in relative.parts or hashlib.sha256(
            protected_native(freeze/relative)).hexdigest()!=digest:
            raise RuntimeError("frozen native context file changed")
    managed=protected_native(root/"codex-r4/managed_runtime.py")
    if hashlib.sha256(managed).hexdigest()!=MANAGED_NATIVE_SHA:
        raise RuntimeError("installed runtime lacks the reviewed customer hook")
    sys.path.insert(0,str(freeze))
    import native_context_runtime
    return native_context_runtime.factory(operator,freeze)


PUBLIC_REPLY_MANIFEST_SHA="9840b80ee4dcc2e6a02dca5142445e874c83d93d14f50f78e1fbb0b61c1188dc"
PUBLIC_REPLY_RELEASE="public_product_reply_runtime_v4b"


def load_public_options(operator,root,official,*,check):
    if root!=operator.parent/"round-4":
        raise RuntimeError("public response must use the registered shop root")
    freeze=operator/"deploy"/PUBLIC_REPLY_RELEASE
    release_info=freeze.lstat()
    if (freeze.resolve()!=freeze or not stat.S_ISDIR(release_info.st_mode)
        or release_info.st_uid!=os.getuid() or release_info.st_mode & 0o022):
        raise RuntimeError("unprotected public response package")
    raw=protected_native(freeze/"MANIFEST.json")
    if hashlib.sha256(raw).hexdigest()!=PUBLIC_REPLY_MANIFEST_SHA:
        raise RuntimeError("public reply release manifest changed")
    manifest=json.loads(raw)
    files=manifest["file_sha256"]
    if manifest["renderer_version"]!=2 and not (check and PUBLIC_REPLY_RELEASE.endswith("-v1-test")):
        raise RuntimeError("public reply release requires reviewed renderer v2")
    for name,digest in files.items():
        relative=Path(name)
        if relative.is_absolute() or ".." in relative.parts or hashlib.sha256(
                protected_native(freeze/relative)).hexdigest()!=digest:
            raise RuntimeError("public reply package artifact changed")
    current=protected_native(root/"codex-r4/managed_runtime.py")
    if hashlib.sha256(current).hexdigest()!=MANAGED_NATIVE_SHA:
        raise RuntimeError("public reply host boundary baseline changed")
    sys.path.insert(0,str(freeze))
    from public_response_composition_candidate import managed_options
    pins={name.removeprefix("renderer/"):pin for name,pin in files.items() if name.startswith("renderer/")}
    return managed_options(operator,freeze,official,pins,check=check)


CATALOGUE_RELEASE="public_catalogue_runtime_v3d"
CATALOGUE_MANIFEST_SHA="818e94a3c7c845ed7b3b93afe41c0883e6eecda24b0b0bf960f5d87dc1efa094"


def load_catalogue_options(operator,root,official,*,check):
    if root!=operator.parent/"round-4":
        raise RuntimeError("public catalogue must use the registered shop root")
    freeze=operator/"deploy"/CATALOGUE_RELEASE
    release_info=freeze.lstat()
    if (freeze.resolve()!=freeze or not stat.S_ISDIR(release_info.st_mode)
        or release_info.st_uid!=os.getuid() or release_info.st_mode & 0o022):
        raise RuntimeError("unprotected public catalogue package")
    raw=protected_native(freeze/"MANIFEST.json")
    if hashlib.sha256(raw).hexdigest()!=CATALOGUE_MANIFEST_SHA:
        raise RuntimeError("public catalogue release manifest changed")
    manifest=json.loads(raw)
    files=manifest["file_sha256"]
    for name,digest in files.items():
        relative=Path(name)
        if relative.is_absolute() or ".." in relative.parts or hashlib.sha256(
                protected_native(freeze/relative)).hexdigest()!=digest:
            raise RuntimeError("public catalogue package artifact changed")
    current=protected_native(root/"codex-r4/managed_runtime.py")
    if hashlib.sha256(current).hexdigest()!=MANAGED_NATIVE_SHA:
        raise RuntimeError("public catalogue host boundary baseline changed")
    sys.path.insert(0,str(freeze))
    from public_catalogue_composition_candidate import managed_options
    pins={name.removeprefix("catalogue/"):pin for name,pin in files.items() if name.startswith("catalogue/")}
    return managed_options(operator,freeze,official,pins,check=check)


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
    parser.add_argument("--enable-procurement", action="store_true")
    parser.add_argument("--procurement-lines", type=int, choices=range(1,11), default=10)
    parser.add_argument("--enable-native-customer-context", action="store_true")
    parser.add_argument("--enable-public-product-reply", action="store_true")
    parser.add_argument("--enable-public-catalogue",action="store_true")
    args = parser.parse_args()
    catalogue_env=os.environ.get("R4_ENABLE_PUBLIC_CATALOGUE","0")
    if catalogue_env not in ("0","1"):
        parser.error("invalid public catalogue opt-in")
    public_env=os.environ.get("R4_ENABLE_PUBLIC_PRODUCT_REPLY","0")
    if public_env not in ("0","1"):
        parser.error("invalid public product reply opt-in")
    native_env=os.environ.get("R4_ENABLE_NATIVE_CUSTOMER_CONTEXT","0")
    if native_env not in ("0","1"):
        parser.error("invalid native customer context opt-in")
    operator = args.operator_dir.resolve(strict=True)
    root = args.agent_root.resolve(strict=True)
    verify_kit(operator)
    config = json.loads((root / "agent.json").read_text(encoding="utf-8"))
    if config.get("llm") != {"base": "market"}:
        parser.error("the managed runtime uses the existing class market model only")
    sys.path.insert(0, str(operator / "kit"))
    import agent_kit as official

    native_enabled=args.enable_native_customer_context or native_env=="1"
    public_enabled=args.enable_public_product_reply or public_env=="1"
    catalogue_enabled=args.enable_public_catalogue or catalogue_env=="1"
    catalogue_options=load_catalogue_options(operator,root,official,check=args.action=="check") if catalogue_enabled else None
    public_options=load_public_options(operator,root,official,check=args.action=="check") if public_enabled and not catalogue_enabled else None
    native=load_native_factory(operator,root) if native_enabled and not public_enabled and not catalogue_enabled else None
    install(official,enable_stock=args.enable_procurement,stock_lines=args.procurement_lines,
            native_factory=native,public_options=public_options,catalogue_options=catalogue_options)
    if args.action == "check":
        # Loading and checking provenance does not construct a signer or join.
        toolbox = official.Toolbox(root, {"tokens": {}, "addresses": {}})
        toolbox.validate()
        print(json.dumps({"official_kit_files_verified": 7, "a2a": "a2a_info",
                          "class_model": "market", "model_tools": ["shop_info"], "background_procurement": args.enable_procurement,
                          "native_customer_context":(native_enabled or public_enabled) and not catalogue_enabled,
                          "public_product_reply":public_enabled and not catalogue_enabled,"public_catalogue":catalogue_enabled,"joined_or_started": False}, ensure_ascii=False))
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

