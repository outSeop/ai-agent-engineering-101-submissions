"""Load a bounded, fresh local public catalogue snapshot for one request."""
import json
import os
import stat
from time import time

MAX_INPUT = 2 * 1024 * 1024
MAX_ROWS = 5000
SNAPSHOT_KEYS = {"schema", "shop", "observed_at", "valid_until", "units"}


class CatalogueError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def verify_snapshot(raw, clock=time):
    if not 0 < len(raw) <= MAX_INPUT:
        raise CatalogueError("cache_size")
    try:
        value = json.loads(raw)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise CatalogueError("cache_schema") from exc
    if (not isinstance(value,dict) or set(value) != SNAPSHOT_KEYS
            or value["schema"] != "outseop-r4.customer-offers.v1" or value["shop"] != "outseop-r4"
            or type(value["observed_at"]) is not int or type(value["valid_until"]) is not int
            or not isinstance(value["units"], list)):
        raise CatalogueError("cache_schema")
    if len(value["units"]) > MAX_ROWS:
        raise CatalogueError("cache_capacity")
    if not value["observed_at"] <= clock() < value["valid_until"] <= value["observed_at"] + 150:
        raise CatalogueError("cache_stale")
    return value


def read_snapshot(path, clock=time):
    try:
        if path.parent.resolve(strict=True) != path.parent:
            raise CatalogueError("cache_unprotected")
        parent = path.parent.lstat()
        if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid() or parent.st_mode & 0o022:
            raise CatalogueError("cache_unprotected")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            item = os.fstat(stream.fileno())
            if (not stat.S_ISREG(item.st_mode) or item.st_uid != os.getuid()
                    or item.st_nlink != 1 or item.st_mode & 0o022):
                raise CatalogueError("cache_unprotected")
            if item.st_size > MAX_INPUT:
                raise CatalogueError("cache_size")
            raw = stream.read(MAX_INPUT + 1)
    except FileNotFoundError as exc:
        raise CatalogueError("cache_missing") from exc
    except OSError as exc:
        raise CatalogueError("cache_unprotected") from exc
    return raw, verify_snapshot(raw, clock)



def atomic(path,data):
    from pathlib import Path
    from tempfile import mkstemp

    fd, temporary = mkstemp(dir=path.parent,prefix=".pending-")
    try:
        with os.fdopen(fd,"wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary,0o400)
        os.replace(temporary,path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def verified_freeze(freeze,pin):
    from hashlib import sha256
    from pathlib import Path
    from card_source_read_lane import raw_file,safe_directory

    safe_directory(freeze)
    raw=raw_file(freeze/"MANIFEST.json")
    if sha256(raw).hexdigest()!=pin:
        raise CatalogueError("package_manifest_drift")
    meta=json.loads(raw)
    for name,digest in meta["file_sha256"].items():
        relative=Path(name)
        path=freeze/relative
        if relative.is_absolute() or ".." in relative.parts or path.resolve()!=path:
            raise CatalogueError("package_path_unprotected")
        if sha256(raw_file(path)).hexdigest()!=digest:
            raise CatalogueError("package_artifact_drift")
    return meta
