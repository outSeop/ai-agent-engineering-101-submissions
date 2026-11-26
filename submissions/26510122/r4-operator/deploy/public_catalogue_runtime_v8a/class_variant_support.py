"""Host-only intent and reviewed read-tool reuse for official Mind variants."""
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat

from class_host_guards import PUBLIC_URLS, load_reviewed_reads


NAME = "read_market_cards"
PIN = "7ef1d976ce10bd8d1543a8329c0d575685652031608c540a006ed3b6b3a6b423"
FILES = ("logic.py", "test.py", "permission.yml")


def owned(path, kind):
    info = path.lstat()
    if not kind(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise ValueError("unsafe variant input path")
    if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
        raise ValueError("hardlinked variant input")
    return path


def read_intent(path):
    entry = json.loads(owned(path, stat.S_ISREG).read_text(encoding="utf-8"))
    if not isinstance(entry, dict) or set(entry) != {"persona", "goal"}:
        raise ValueError("intent requires exactly persona and goal")
    if any(not isinstance(value, str) or not value.strip() or len(value) > 16384
           for value in entry.values()):
        raise ValueError("intent values must be nonempty bounded strings")
    return entry


def reviewed_snapshot(operator, source):
    runtime = (operator / "runtime").resolve(strict=True)
    if (source.is_symlink() or source.absolute().parent != runtime
            or not source.name.startswith("class-rebuild-")):
        raise ValueError("invalid origin session")
    source = owned(source, stat.S_ISDIR)
    tools = owned(source / "tools", stat.S_ISDIR)
    tool = owned(tools / NAME, stat.S_ISDIR)
    proof_bytes = owned(source / "generation-origin-proof.json", stat.S_ISREG).read_bytes()
    proof = json.loads(proof_bytes)
    if proof.get("actual_class_model") is not True or proof.get("official_mind") is not True:
        raise ValueError("missing class-model provenance")
    matches = [
        match
        for row in proof.get("records", [])
        if (row.get("tool"), row.get("version"), row.get("source_sha256")) == (NAME, 1, PIN)
        for match in row.get("class_generation_matches", [])
        if match.get("official_system_prefix") is True
        and re.fullmatch(r"[0-9a-f]{64}", match.get("raw_response_sha256", ""))
    ]
    if not matches:
        raise ValueError("origin does not establish generation of the reviewed tool")
    bundle = {name: owned(tool / name, stat.S_ISREG).read_bytes() for name in (*FILES, "forge.json")}
    manifest = json.loads(bundle["forge.json"])
    hashes = {name: sha256(bundle[name]).hexdigest() for name in FILES}
    if ((manifest.get("tool"), manifest.get("version")) != (NAME, 1)
        or manifest.get("sha256") != hashes or hashes["logic.py"] != PIN):
        raise ValueError("reviewed tool bytes differ from its original forge")
    owned(source / ".kit", stat.S_ISDIR)
    approval_path = owned(source / ".kit" / "reviewed-public-reads.json", stat.S_ISREG)
    approvals = load_reviewed_reads(approval_path)
    if approvals[NAME]["sha256"] != PIN or not set(approvals[NAME]["urls"]) <= PUBLIC_URLS:
        raise ValueError("origin approval does not match reviewed source")
    return bundle, approvals, {
        "record_type": "derived_tool_reuse",
        "origin_session": source.name,
        "origin_model_provider": "market-class",
        "origin_proof_sha256": sha256(proof_bytes).hexdigest(),
        "tool": NAME, "version": 1, "sha256": hashes,
    }


def write_snapshot(root, snapshot):
    bundle, approvals, origin = snapshot
    target = root / "tools" / NAME
    target.mkdir(mode=0o700)
    for name, contents in bundle.items():
        with (target / name).open("xb") as stream:
            stream.write(contents)
    for path, contents in (
        (root / ".kit" / "reviewed-public-reads.json", approvals),
        (root / "reuse-origin.json", origin),
    ):
        with path.open("x", encoding="utf-8") as stream:
            json.dump(contents, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    return origin

