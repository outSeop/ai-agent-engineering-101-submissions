"""Transport exact paired public snapshots to the reviewed native alternatives tool."""
from contextlib import redirect_stderr, redirect_stdout
from hashlib import sha256
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from bounded_public_catalogue_host import verified_catalogue
from card_source_read_lane import raw_file, safe_directory
from public_catalogue_snapshot_host import CatalogueError

TOOL = "public_alternatives"
LIMIT = 2 * 1024 * 1024
LEAVES = {"logic.py", "test.py", "permission.yml", "forge.json"}
CAPABILITIES = ("wallet", "identity", "network", "write", "exec", "handles", "pay_limit")


def native_files(source, pins, official):
    safe_directory(source)
    if set(pins) != LEAVES:
        raise ValueError("alternative source pins are incomplete")
    blobs = {name: raw_file(source / name) for name in LEAVES}
    if any(sha256(data).hexdigest() != pins[name] for name, data in blobs.items()):
        raise ValueError("alternative source mismatch")
    forge = json.loads(blobs["forge.json"])
    if (forge.get("tool") != TOOL or type(forge.get("version")) is not int
            or forge.get("sha256") != {name: digest for name, digest in pins.items() if name != "forge.json"}):
        raise ValueError("alternative forge receipt mismatch")
    metadata = official.forge_runner.parse_permission(blobs["permission.yml"].decode())
    permission = metadata.get("permission", {})
    if not isinstance(permission, dict) or any(permission.get(key) for key in CAPABILITIES):
        raise ValueError("alternative native tool must be read-only")
    return blobs


def stock_bytes(path):
    parent = safe_directory(path.parent)
    directory = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1
                    or info.st_mode & 0o022 or not 0 < info.st_size <= LIMIT):
                raise ValueError("untrusted stock state")
            raw = stream.read(LIMIT + 1)
            updated = os.fstat(stream.fileno())
            if (len(raw) != info.st_size or info.st_size != updated.st_size
                    or info.st_mtime_ns != updated.st_mtime_ns or info.st_ctime_ns != updated.st_ctime_ns):
                raise ValueError("stock state changed during read")
            return raw
    finally:
        os.close(directory)


class BoundedAlternatives:
    def __init__(self, catalogue, catalogue_pins, source, pins, kit, scratch):
        self.catalogue = catalogue
        self.catalogue_pins = dict(catalogue_pins)
        self.source = source
        self.pins = dict(pins)
        self.kit = kit
        self.scratch = safe_directory(scratch)

    def verify(self, official):
        verified_catalogue(self.catalogue, self.catalogue_pins)
        native_files(self.source, self.pins, official)

    def __call__(self, *, args, snapshot, stock, timeout):
        if (not 0 < timeout <= 5 or type(snapshot) is not bytes or not 0 < len(snapshot) <= LIMIT
                or type(stock) is not bytes or not 0 < len(stock) <= LIMIT):
            raise ValueError("invalid alternative worker input")
        header = json.dumps({"args": args, "snapshot_length": len(snapshot)}, ensure_ascii=False,
                            allow_nan=False, separators=(",", ":")).encode()
        if len(header) > 8192:
            raise ValueError("alternative request exceeds header budget")
        payload = header + b"\n" + snapshot + stock
        env = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "TMPDIR") if key in os.environ}
        env["PYTHONIOENCODING"] = "utf-8"
        with TemporaryDirectory(prefix="r4-alternatives-", dir=self.scratch) as temporary:
            command = [sys.executable, "-I", "-B", str(Path(__file__).resolve()), str(self.catalogue),
                       json.dumps(self.catalogue_pins), str(self.source), json.dumps(self.pins),
                       str(self.kit), temporary]
            child = subprocess.Popen(command, cwd=temporary, env=env, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
            try:
                output, _ = child.communicate(payload, timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.communicate()
                raise ValueError("alternative worker deadline exceeded") from None
        if child.returncode or not 0 < len(output) <= 32768:
            raise ValueError("alternative worker unavailable")
        return json.loads(output)


class ScopedAlternatives:
    def __init__(self, catalogue, worker, stock_path):
        self.catalogue = catalogue
        self.worker = worker
        self.stock_path = stock_path
        self.menu = None
        self.text = None

    def open(self, text, remaining):
        if self.menu is not None:
            raise CatalogueError("action_rejected")
        request = self.catalogue.protocol.alternatives_request(text)
        self.menu = self._invoke(request, remaining)
        self.text = text
        return self.menu

    def render(self, text, args, remaining):
        if self.menu is None or text != self.text:
            raise CatalogueError("action_rejected")
        request = self.catalogue.protocol.alternatives_request(text, args=args, menu=self.menu)
        result = self._invoke(request, remaining)
        if "public_facts" in result:
            offered = {(item["sku"].upper(), item["grade"]): item["preferred_price"] for item in self.menu["items"]}
            selected = {(item["sku"].upper(), item["grade"]) for item in request["items"]}
            verified = {(item["sku"].upper(), item["grade"]): item["preferred_price"] for item in result["public_facts"]}
            if (set(verified) != selected or len(verified) != len(result["public_facts"])
                    or any(offered[key] != verified[key] for key in selected)):
                raise CatalogueError("alternatives_failed")
        return result

    def _invoke(self, request, remaining):
        bound = self.catalogue._source
        if bound is None:
            raise CatalogueError("cache_missing")
        raw, observed, valid = bound
        if not observed <= self.catalogue.clock() < valid:
            raise CatalogueError("cache_stale")
        timeout = min(5, remaining, valid - self.catalogue.clock())
        if timeout <= 0:
            raise CatalogueError("flow_deadline")
        try:
            newest, _ = self.catalogue.supplier()
            if newest != raw:
                raise CatalogueError("snapshot_changed")
            stock = stock_bytes(self.stock_path)
            response = self.worker(args=request, snapshot=raw, stock=stock, timeout=timeout)
            if not observed <= self.catalogue.clock() < valid:
                raise CatalogueError("cache_stale")
            return self.catalogue.protocol.alternatives_result(request["op"], response, observed, valid,
                                                              sha256(raw).hexdigest())
        except CatalogueError:
            raise
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
            raise CatalogueError("alternatives_failed") from error


def main():
    catalogue, source, kit, root = (Path(sys.argv[i]).resolve(strict=True) for i in (1, 3, 5, 6))
    catalogue_pins, pins = (json.loads(sys.argv[i]) for i in (2, 4))
    sys.path[:0] = [str(Path(__file__).resolve().parent), str(kit)]
    import agent_kit as official

    class NoWallet:
        def grant(self, name, permission, timeout):
            if any(permission.get(key) for key in CAPABILITIES):
                raise ValueError("unexpected alternatives capability")
            return None

    header = sys.stdin.buffer.readline(8193)
    if not header.endswith(b"\n") or len(header) > 8193:
        return 2
    frame = json.loads(header)
    args, length = frame["args"], frame["snapshot_length"]
    if type(length) is not int or not 0 < length <= LIMIT or args.get("op") not in {"context", "render"}:
        return 2
    snapshot = sys.stdin.buffer.read(length)
    stock = sys.stdin.buffer.read(LIMIT + 1)
    if len(snapshot) != length or not 0 < len(stock) <= LIMIT:
        return 2
    os.umask(0o077)
    inputs = root / "host_inputs"
    inputs.mkdir(mode=0o700)
    for name, raw in (("customer_offer_context.json", snapshot), ("stock-state.json", stock)):
        path = inputs / name
        path.write_bytes(raw)
        path.chmod(0o400)
    for name, files in (("public_catalogue", verified_catalogue(catalogue, catalogue_pins)),
                        (TOOL, native_files(source, pins, official))):
        target = root / "tools" / name
        target.mkdir(mode=0o700, parents=True)
        for leaf, raw in files.items():
            path = target / leaf
            path.write_bytes(raw)
            path.chmod(0o400)
    context = {"name": "outseop-r4", "market": "https://example.invalid", "tokens": {},
               "addresses": {}, "signer": NoWallet()}
    official.mk.LOG_FILE = None
    with open(os.devnull, "w") as sink, redirect_stdout(sink), redirect_stderr(sink):
        result = official.Toolbox(root, context).run(TOOL, "call", args)
    if not isinstance(result, dict) or set(result) != {"ok", "result"} or result["ok"] is not True:
        return 2
    encoded = json.dumps(result["result"], ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    if len(encoded) > 32768:
        return 2
    sys.stdout.buffer.write(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
