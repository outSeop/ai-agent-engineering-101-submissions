"""Host guards for the isolated official classroom runner."""
from hashlib import sha256
import json
import math
import re
from pathlib import Path
import stat
import subprocess

from card_source_read_lane import READER as CARD_SOURCE_READER, PIN as CARD_SOURCE_PIN


SUMMARY_TOOL = "summarize_public_settlements"
SUMMARY_PIN = "5f8641150e3cb9dfc27d6d8d78e791eb02d88ad60c39ba94a8416ba22cb50846"
SUMMARY_FIELDS = {
    "mode", "requested_time", "sample_time", "coverage", "by_sku",
    "by_category", "sealed_count", "unclassified_count",
}
SUMMARY_ERRORS = {"invalid_window_seconds", "public_http_error", "public_request_failed", "invalid_public_data"}

PUBLIC_SITE = "https://market.ourolabs.ai"
ENTITY_IDS = ("orders", "clearing", "wholesale", "forum", "board", "bank", "model")
PUBLIC_URLS = frozenset(
    PUBLIC_SITE + path for path in (
        "/.well-known/agent-card.json", "/agent.md", "/ROUND4.md", "/rules", "/api/chain",
        *(f"/entities/{entity}/.well-known/agent-card.json" for entity in ENTITY_IDS),
    )
)


def load_reviewed_reads(path):
    if not path.exists():
        return {}
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise ValueError("reviewed-read manifest must be a private regular file")
    metadata = json.loads(path.read_text())
    if not isinstance(metadata, dict) or not set(metadata) <= {"read_market_cards", SUMMARY_TOOL, CARD_SOURCE_READER}:
        raise ValueError("unknown reviewed tool")
    if "read_market_cards" in metadata:
        record = metadata["read_market_cards"]
        if set(record) != {"sha256", "urls"} or not set(record["urls"]) <= PUBLIC_URLS:
            raise ValueError("unsafe reviewed URL list")
    if SUMMARY_TOOL in metadata and metadata[SUMMARY_TOOL] != {"sha256": SUMMARY_PIN}:
        raise ValueError("public summary does not match approved SHA")
    if CARD_SOURCE_READER in metadata and metadata[CARD_SOURCE_READER] != {"sha256": CARD_SOURCE_PIN}:
        raise ValueError("card source reader does not match approved SHA")
    return metadata


def reviewed_call(tools, approvals, name, args):
    if name not in {"read_market_cards", SUMMARY_TOOL}:
        return False
    tool = tools.get(name)
    review = approvals.get(name)
    if not tool or not review or not isinstance(args, dict):
        return False
    if name == "read_market_cards":
        if set(args) != {"url"}:
            return False
        url = args["url"]
        if not isinstance(url, str) or url not in PUBLIC_URLS or url not in review["urls"]:
            return False
    else:
        if review != {"sha256": SUMMARY_PIN} or not set(args) <= {"window_seconds"}:
            return False
        duration = args.get("window_seconds", 3600)
        if type(duration) is not int or not 60 <= duration <= 86400:
            return False
    perm = tool.get("perm", {})
    if (set(perm.get("network") or []) != {"market.ourolabs.ai"}
            or any(perm.get(key) for key in ("wallet", "identity", "write", "exec"))):
        return False
    source = Path(tool["dir"]) / "logic.py"
    if source.is_symlink():
        return False
    return sha256(source.read_bytes()).hexdigest() == review["sha256"]


def valid_time(value):
    if not isinstance(value, dict) or set(value) != {"start", "end"}:
        return False
    start, end = value["start"], value["end"]
    return all(type(x) in (int, float) and 0 <= x <= 2**53 and math.isfinite(x)
               for x in (start, end)) and start <= end


def valid_count(value):
    return type(value) is int and 0 <= value <= 2**53


def public_label(value):
    return isinstance(value, str) and 0 < len(value) <= 512 and value.isprintable()


def safe_reviewed_result(name, envelope):
    if name != SUMMARY_TOOL:
        return envelope
    blocked = {"ok": False, "error": "public summary response rejected"}
    if not isinstance(envelope, dict) or set(envelope) != {"ok", "result"} or envelope["ok"] is not True:
        return blocked
    result = envelope["result"]
    if not isinstance(result, dict):
        return blocked
    if set(result) in ({"error"}, {"error", "status"}):
        error = result["error"]
        if (isinstance(error, str) and error in SUMMARY_ERRORS
                and ("status" not in result or
                     (error == "public_http_error" and type(result["status"]) is int and 400 <= result["status"] <= 599))):
            return envelope
        return blocked
    if (set(result) != SUMMARY_FIELDS or result["mode"] != "public_market_sample"
            or result["coverage"] not in ("boundaries_observed", "partial")
            or not valid_time(result["requested_time"])
            or (result["sample_time"] is not None and not valid_time(result["sample_time"]))
            or not valid_count(result["sealed_count"]) or not valid_count(result["unclassified_count"])):
        return blocked
    rows, categories = result["by_sku"], result["by_category"]
    if (not isinstance(rows, list) or len(rows) > 6000 or not isinstance(categories, dict)
            or len(categories) > 6000
            or not all(public_label(key) and valid_count(count) for key, count in categories.items())):
        return blocked
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {"sku", "name", "category", "count"}
                or not isinstance(row["sku"], str) or not re.fullmatch(r"[FG][0-9a-fA-F]{8}", row["sku"])
                or not public_label(row["name"]) or not public_label(row["category"])
                or not valid_count(row["count"])):
            return blocked
    return envelope


class OfflineForgeSubprocess:
    """Prefix only the official subprocess runner's test mode. Never fall back."""

    TimeoutExpired = subprocess.TimeoutExpired

    @staticmethod
    def run(argv, **kwargs):
        if len(argv) != 5 or argv[1] != "-I" or Path(argv[2]).name != "forge_runner.py":
            raise ValueError("unexpected official tool runner invocation")
        if argv[-1] == "test":
            argv = ["/usr/bin/unshare", "-Urn", "--", *argv]
        elif argv[-1] != "call":
            raise ValueError("unexpected official tool runner mode")
        return subprocess.run(argv, **kwargs)

