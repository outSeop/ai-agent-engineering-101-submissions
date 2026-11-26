"""Request-bound public stock-state observation derived from the canonical ledger."""
from hashlib import sha256
import json
import math
import os
import re
import stat

from public_catalogue_protocol import sku
from public_catalogue_snapshot_host import CatalogueError

PHYSICAL_UNIT = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")


def physical_unit(value):
    return isinstance(value,str) and PHYSICAL_UNIT.fullmatch(value) is not None


PENDING = frozenset({"issued","cancel_requested","paid"})
CAP = 512 * 1024
SCHEMA = "outseop-r4.public-stock-state.v1"


def public_stock_state(db, inventory, observed, *, preferred_price=lambda unit:None):
    """Only currently offered unit identity and ledger statuses enter this join."""
    physical_ids=sorted({row["unit"] for row in inventory if physical_unit(row.get("unit"))})
    statuses = {}
    for offset in range(0,len(physical_ids),400):
        batch=physical_ids[offset:offset+400]
        bind=",".join("?" for _ in batch)
        for unit,status in db.execute(f"SELECT unit,status FROM sale WHERE unit IN ({bind})",batch):
            statuses.setdefault(unit,set()).add(status)
    rows = {}
    for unit in inventory:
        product, physical, grade, expiry = (unit[k] for k in ("sku","unit","grade","expires_at"))
        if not sku(product) or not physical_unit(physical) or grade not in {"A","B","C"}:
            continue
        if expiry is not None and (type(expiry) not in (int,float) or not math.isfinite(expiry) or int(expiry)<=observed):
            continue
        claims = statuses.get(physical,set())
        state = "available" if not claims else "reserved_pending" if claims <= PENDING else "reconciling"
        key=(product,grade,state)
        end=int(expiry) if expiry is not None else None
        price=preferred_price(unit)
        if type(price) is not int or price<=0:
            price=None
        # Representative stock metadata is informational. Do not mix expiry/price across units.
        if key not in rows or rows[key][0] is not None and (end is None or end>rows[key][0]):
            rows[key]=(end,price)
    if physical_ids and not rows:
        raise ValueError("usable physical inventory has no public stock-state projection")
    return [{"sku":product,"grade":grade,"stock_status":state,"expires_at":end,"preferred_price":price}
            for (product,grade,state),(end,price) in sorted(rows.items())]


def seal(raw, observed, valid, states):
    return {"schema":SCHEMA,"snapshot":sha256(raw).hexdigest(),"observed_at":observed,
            "valid_until":valid,"rows":states}


def read(path, raw, document):
    try:
        parent=path.parent.lstat()
        if (path.parent.resolve(strict=True)!=path.parent or not stat.S_ISDIR(parent.st_mode)
                or parent.st_uid!=os.getuid() or parent.st_mode & 0o022):
            raise CatalogueError("cache_unprotected")
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,"rb") as stream:
            info=os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1 or info.st_mode & 0o022:
                raise CatalogueError("cache_unprotected")
            data=stream.read(CAP+1)
        if len(data)>CAP:
            raise CatalogueError("cache_size")
        value=json.loads(data)
    except CatalogueError:
        raise
    except (OSError,ValueError) as error:
        raise CatalogueError("cache_unavailable") from error
    if (not isinstance(value,dict) or set(value)!={"schema","snapshot","observed_at","valid_until","rows"}
        or value["schema"]!=SCHEMA or value["snapshot"]!=sha256(raw).hexdigest()
        or value["observed_at"]!=document["observed_at"] or value["valid_until"]!=document["valid_until"]
        or not isinstance(value["rows"],list) or len(value["rows"])>5000):
        raise CatalogueError("snapshot_changed")
    for row in value["rows"]:
        if (not isinstance(row,dict) or set(row)!={"sku","grade","stock_status","expires_at","preferred_price"}
            or not sku(row["sku"]) or row["grade"] not in {"A","B","C"}
            or row["stock_status"] not in {"available","reserved_pending","reconciling"}
            or row["preferred_price"] is not None and (type(row["preferred_price"]) is not int or row["preferred_price"]<=0)
            or row["expires_at"] is not None and (type(row["expires_at"]) is not int or row["expires_at"]<=value["observed_at"])):
            raise CatalogueError("cache_schema")
    return value["rows"]
