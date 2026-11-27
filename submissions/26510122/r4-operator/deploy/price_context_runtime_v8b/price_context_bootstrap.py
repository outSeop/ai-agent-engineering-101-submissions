"""HOST filesystem binding: isolate the v5 price reader from the live forum publisher.

Runs original pinned entrypoints; never executes the archived forum entrypoint.
The only rebinding is card_offer_producer_host.verify_source's filesystem root.
"""
from pathlib import Path
from hashlib import sha256
import importlib.util
import json
import os
import stat
import sys

HERE = Path(__file__).resolve().parent
OPERATOR = HERE.parent.parent
BASE_SHA = "8b5a25d66a3426cc789f6cd44c7c5e309501aad0ee3489e991452ad803224dd5"
HELPERS = {
    "catalogue": ("public_catalogue_runtime_v8a", "ffa36c8557ecea6f53a7e9ac7271fa598565fd898f1f5d966444bc34a3f808cc", "74cd6baea70015d0950248faddd017821aa0054f93f8073da115e8aa5e629af3"),
    "card": ("native_card_keeper_v1", "2634c1b9fed45b1126941354b0a433babcce3a5916d6968bee2b5bd502839e2a", "b128c9d0851996900734b8a9bdda9256ea41e2f81746658bb01446d4508d6412"),
}

def checked(path):
    path = Path(path)
    before = path.lstat()
    if (path.resolve(strict=True) != path or not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid() or before.st_nlink != 1 or before.st_mode & 0o022):
        raise ValueError("unprotected binding dependency")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        held = os.fstat(fd)
        if (held.st_dev, held.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError("binding dependency changed")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read()
        after = path.lstat()
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError("binding dependency changed during read")
        return raw
    finally:
        os.close(fd)

def verify_package(pin):
    raw = checked(HERE / "MANIFEST.json")
    if sha256(raw).hexdigest() != pin:
        raise ValueError("binding manifest changed")
    files = json.loads(raw)["file_sha256"]
    if "price_context_bootstrap.py" not in files:
        raise ValueError("binding entry missing")
    for name, expected in files.items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or sha256(checked(HERE / relative)).hexdigest() != expected:
            raise ValueError("binding source changed")
    return files

def load_exact(name, path, pin):
    raw = checked(path)
    if sha256(raw).hexdigest() != pin or name in sys.modules:
        raise ValueError("unexpected binding module")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module

def prepare(alias, package_pin):
    files = verify_package(package_pin)
    if alias not in HELPERS:
        raise ValueError("target not allowlisted")
    base = load_exact("_price_context_original_v8a", OPERATOR / "deploy/price_context_runtime_v8a/price_context_bootstrap.py", BASE_SHA)
    if base.OPERATOR != OPERATOR:
        raise ValueError("unexpected operator")
    base.verify_target(alias)
    base.bind_policy()
    release, manifest_pin, helper_pin = HELPERS[alias]
    folder = OPERATOR / "deploy" / release
    raw = checked(folder / "MANIFEST.json")
    if sha256(raw).hexdigest() != manifest_pin:
        raise ValueError("helper manifest changed")
    for name, expected in json.loads(raw)["file_sha256"].items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or sha256(checked(folder / relative)).hexdigest() != expected:
            raise ValueError("helper dependency changed")
    sys.path[:0] = [str(folder), str(OPERATOR / "kit")]
    helper = load_exact("card_offer_producer_host", folder / "card_offer_producer_host.py", helper_pin)
    original = helper.verify_source
    legacy_root = HERE / "legacy_root"
    def bound_source(root):
        if Path(root) != base.REGISTERED:
            raise ValueError("unexpected business root")
        for leaf in ("logic.py", "permission.yml", "test.py", "forge.json"):
            name = "legacy_root/tools/forum_marketing/" + leaf
            if sha256(checked(HERE / name)).hexdigest() != files[name]:
                raise ValueError("archived reader changed")
        return original(legacy_root)
    helper.verify_source = bound_source
    # Source-only verification: does not acquire stock, load tokens, call Model,
    # query the production DB, publish, or invoke any wallet operation.
    bound_source(base.REGISTERED)
    return base, helper

def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-manifest-sha", required=True)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("target", choices=tuple(HELPERS))
    parser.add_argument("original_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    base, helper = prepare(args.target, args.package_manifest_sha)
    forwarded = args.original_args
    if forwarded[:1] == ["--"]:
        forwarded = forwarded[1:]
    result = base.run(args.target, forwarded, check=args.check)
    if args.check:
        result.update(binding="archived-v5-filesystem-root-only", reader_source_unchanged=True,
                      helper_file_sha256=sha256(checked(Path(helper.__file__))).hexdigest())
        print(json.dumps(result))

if __name__ == "__main__":
    main()
