"""Host approval lane for the immutable reviewed card source reader v2."""
from hashlib import sha256
import json
from pathlib import Path
import stat

from card_source_read_lane import READER, PATTERN, credentials, raw_file, safe_directory
from class_host_guards import PUBLIC_URLS, SUMMARY_PIN, SUMMARY_TOOL

PIN="94d8dcc59e5ae905f1c4e8529882374348fae7dfe8a4f39119100a382280f28f"
READER_FILES={
    "logic.py":PIN,
    "test.py":"69399b65932da9839a6fbaa7dc2fae174c0747b1b89845a653bf1e896edf360a",
    "permission.yml":"414440459ef98f70889288d2697aaa0b8cdf346102731c0806a73b5d57ddc037",
}
READER_MANIFEST="2492a73c1dfeca1c2295dd132b25d4dc7912bdb1c379d7b243f1e373bbdea984"
ARCHIVE="apply_staged_card@1"
ARCHIVED_FILES={
    "logic.py":"14143d58859493f56b3b736dab10fe384211d8c0c8b58a1b3db59a50a9d5500f",
    "test.py":"c96e43d06d9d30a2548d35e59a2628d0552b2a36978fba2b8d67d715d5041e55",
    "permission.yml":"a856de475325229ff7e7745d5912c53dbf7e931ed8d7fa1909b751291901b673",
}
ARCHIVE_MANIFEST="f11267a0efd3c9c995083c53515083f858ebdbe8daf222b0b3be3509c5b72e05"
TARGETS={"apply_staged_card","stage_representative_card","refresh_representative_card","publish_shop_info"}
FILES={"logic.py","test.py"}


def load_reviewed_reads(path):
    if not path.exists():
        return {}
    info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise ValueError("reviewed-read manifest must be private")
    records=json.loads(raw_file(path))
    if not isinstance(records,dict) or not set(records)<={"read_market_cards",SUMMARY_TOOL,READER}:
        raise ValueError("unreviewed tool entry")
    if READER in records and records[READER]!={"sha256":PIN}:
        raise ValueError("reviewed reader v2 pin required")
    if SUMMARY_TOOL in records and records[SUMMARY_TOOL]!={"sha256":SUMMARY_PIN}:
        raise ValueError("reviewed summary pin required")
    if "read_market_cards" in records:
        doc=records["read_market_cards"]
        if not isinstance(doc,dict) or set(doc)!={"sha256","urls"} or not set(doc["urls"])<=PUBLIC_URLS:
            raise ValueError("unreviewed public document URL")
    return records


def bundle(directory, name, expected=None, version=None, manifest_pin=None):
    blob=raw_file(directory/"forge.json")
    if manifest_pin and sha256(blob).hexdigest()!=manifest_pin:
        raise ValueError("forge manifest pin changed")
    manifest=json.loads(blob)
    names={"logic.py","test.py","permission.yml"}
    hashes=manifest.get("sha256",{})
    if (manifest.get("tool")!=name or type(manifest.get("version")) is not int
        or manifest["version"]<1 or set(hashes)!=names or (expected is not None and hashes!=expected)
        or (version is not None and manifest["version"]!=version)):
        raise ValueError("unexpected forge manifest")
    payload={file:raw_file(directory/file) for file in names}
    if any(sha256(raw).hexdigest()!=hashes[file] for file,raw in payload.items()):
        raise ValueError("forge source changed")
    return payload


def expected_slice(root,tools,args,needles):
    if not isinstance(args,dict) or set(args)!={"name","file","offset"}:
        raise ValueError("unapproved source arguments")
    name,file,offset=args["name"],args["file"],args["offset"]
    if (not isinstance(name,str) or name not in TARGETS|{ARCHIVE} or not isinstance(file,str)
        or file not in FILES or type(offset) is not int or offset<0):
        raise ValueError("unapproved source arguments")
    reader=tools.get(READER)
    root=safe_directory(root)
    tools_dir=safe_directory(root/"tools")
    directory=safe_directory(tools_dir/READER)
    if (not reader or Path(reader["dir"])!=directory
        or any(reader["perm"].get(k) for k in ("network","wallet","identity","exec","write","handles"))):
        raise ValueError("reader permission mismatch")
    bundle(directory,READER,READER_FILES,2,READER_MANIFEST)
    if name==ARCHIVE:
        # Do not let the tool's alternative fallback path shadow the real archive.
        if (root/".deprecated").exists() or (root/".deprecated").is_symlink():
            raise ValueError("unexpected alternate archive path")
        archived=safe_directory(safe_directory(tools_dir/".deprecated")/ARCHIVE)
        raw=bundle(archived,"apply_staged_card",ARCHIVED_FILES,1,ARCHIVE_MANIFEST)[file]
    else:
        raw=bundle(safe_directory(tools_dir/name),name)[file]
    if len(raw)>256*1024 or any(secret in raw for secret in needles) or PATTERN.search(raw):
        raise ValueError("unsafe source content")
    text=raw.decode("utf-8")
    if offset>len(text):
        raise ValueError("source offset outside file")
    end=min(offset+2000,len(text))
    return {"sha256":sha256(raw).hexdigest(),"offset":offset,"next_offset":end if end<len(text) else None,
            "total_chars":len(text),"source":text[offset:end]}


def checked_read(root,tools,request,needles,invoke):
    denied={"ok":False,"error":"card source read rejected"}
    try:
        expected=expected_slice(root,tools,request,needles)
        actual=invoke()
        if actual!={"ok":True,"result":expected} or expected_slice(root,tools,request,needles)!=expected:
            return denied
        return actual
    except (OSError,KeyError,TypeError,ValueError,AttributeError):
        return denied

