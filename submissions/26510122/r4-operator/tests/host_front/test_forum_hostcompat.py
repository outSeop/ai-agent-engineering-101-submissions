"""Original SDK app assembly with exact legacy/new forum tools in isolated workspaces."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import tempfile

import catalogue_asgi_support as support

LEAVES = ("forge.json", "logic.py", "permission.yml", "test.py")


def populate(original, destination):
    destination.mkdir()
    record = json.loads((original / "forge.json").read_bytes())
    for name in LEAVES:
        body = (original / name).read_bytes()
        if name != "forge.json" and sha256(body).hexdigest() != record["sha256"][name]:
            raise ValueError("fixture tool differs from its source receipt")
        support.fixed(destination / name, body)


def check(operator, runtime, frontdir, runner, edge, config, build, version, problem=None):
    import agent_kit as official

    class NoModel:
        def complete(self, *args, **kwargs):
            raise AssertionError("no inference in startup verification")

    class NoWallet:
        def grant(self, *args, **kwargs):
            raise AssertionError("no signing in startup verification")

    with tempfile.TemporaryDirectory(prefix="fixture-forum-hostcompat-", dir=operator / "runtime") as directory:
        root = Path(directory)
        tools = root / "tools"
        tools.mkdir()
        for name in ("a2a_info", "shop_info", "publish_shop_info"):
            populate(operator.parent / "round-4/tools" / name, tools / name)
        forum = tools / "forum_marketing"
        source = (operator / "deploy/forum_demand_native_v9/tools/forum_marketing"
                  if version == 9 else runtime / "forum_marketing")
        populate(source, forum)
        support.fixed(root / "agent.json", support.encode({"llm": {"base": "market"}, "goal": "synthetic startup fixture"}))

        def drift_logic():
            target = forum / "logic.py"
            target.chmod(0o600)
            target.write_bytes(target.read_bytes() + bytes((10,)) + b"# isolated tamper")
            target.chmod(0o400)

        if problem == "early_hash":
            drift_logic()

        def toolbox_factory(parent, isolated, ctx):
            if problem == "early_hash":
                raise AssertionError("cold mismatch must reject before SDK could omit the tool")
            box = parent(isolated, ctx)
            if box.tools["forum_marketing"]["version"] != version:
                raise AssertionError("unmodified original Toolbox did not load the genuine tool")
            if problem == "hash":
                drift_logic()
            elif problem == "network":
                box.tools["forum_marketing"]["perm"]["network"].append("extra.invalid")
            elif problem == "directory":
                box.tools["forum_marketing"]["dir"] = runtime / "forum_marketing"
            elif problem == "card":
                box.tools["publish_shop_info"]["perm"]["network"] = ["extra.invalid"]
            return box

        context = {"market": "https://market.ourolabs.ai", "name": "outseop-r4",
                   "shop_url": "https://fixture.invalid", "tokens": {}, "addresses": {}, "signer": NoWallet()}
        official.mk.LOG_FILE = root / "original-sdk.log"
        try:
            app = runner.assemble(official, operator, runtime, build["runtime_manifest_sha256"], context, NoModel(),
                                  options_override={}, toolbox_factory=toolbox_factory, _front=edge,
                                  config=config, isolated_root=root)
        except RuntimeError as error:
            expected = {
                "card": "unexpected card publication permissions",
                "directory": "forum tool outside the configured agent root",
                "hash": "native tool source drift",
                "early_hash": "native tool source drift",
                "network": "forum toolbox metadata differs from the pinned genuine tool",
            }.get(problem)
            if expected is None or str(error) != expected:
                raise
            return True
        if problem is not None:
            raise AssertionError(f"startup accepted invalid {problem} fixture")
        if not callable(app):
            raise AssertionError("official SDK ASGI application missing")
        return True


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("--operator", type=Path, required=True)
    cli.add_argument("--build-receipt", type=Path, required=True)
    cli.add_argument("--build-sha256", required=True)
    args = cli.parse_args()
    operator = args.operator.resolve(strict=True)
    build, runtime, frontdir, runner, edge, config = support.verify_build(
        operator, args.build_receipt.resolve(strict=True), args.build_sha256, expected_semantic=19)
    cases = {}
    for name, version, problem in (
        ("legacy_pub9_sdk_assembly", 9, None),
        ("pinned_pub15_sdk_assembly", 15, None),
        ("active_pub15_hash_drift_denied", 15, "hash"),
        ("cold_pub15_hash_drift_denied_before_toolbox", 15, "early_hash"),
        ("loaded_foreign_network_denied", 15, "network"),
        ("active_tool_directory_mismatch_denied", 15, "directory"),
        ("card_guard_remains_required", 15, "card"),
    ):
        cases[name] = check(operator, runtime, frontdir, runner, edge, config, build, version, problem)
    print(json.dumps({"cases": cases, "sdk_assemblies": len(cases), "inference_calls": 0, "signing_calls": 0,
                      "listener_started": False, "production_modified": False}, sort_keys=True))


if __name__ == "__main__":
    main()
