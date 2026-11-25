"""Synthetic host bridge for model judgments, independent of money and refund policy."""
from contextlib import closing
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import tempfile


HEX = re.compile(r"[0-9a-f]{64}", re.ASCII)
REASONS = {
    "early_market_breakage": ("within_48_hours", "market_breakage_confirmed"),
    "paid_no_delivery": ("not_applicable", "irreversible_seller_non_delivery_confirmed"),
}
OUTCOMES = {"approve": "approved", "decline": "declined"}


def project(preparation):
    required = {"status", "case_id", "reason", "period", "evidence"}
    if not isinstance(preparation, dict) or set(preparation) != required:
        raise ValueError("unexpected proof summary fields")
    if preparation["status"] != "ready_for_model_review":
        raise ValueError("case has no verified preparation")
    case_id, reason = preparation["case_id"], preparation["reason"]
    if not isinstance(case_id, str) or not HEX.fullmatch(case_id) or reason not in REASONS:
        raise ValueError("unrecognized case or reason")
    period, proof = REASONS[reason]
    evidence = {"checkout": "verified", "original_transfers": "verified",
                "refund_terms": "verified", "reason": proof}
    if preparation["period"] != period or preparation["evidence"] != evidence:
        raise ValueError("inconsistent proof summary")
    return {"case_id": case_id, "reason": reason, "period": period,
            "checkout_verified": True, "original_transfers_verified": True,
            "refund_terms_verified": True, "reason_verified": True}


def fixture_db(path):
    path = Path(path)
    if path.name != "refund_binding_fixture.sqlite3":
        raise ValueError("only dedicated synthetic fixture allowed")
    if path.is_symlink():
        raise ValueError("symlinked fixture")
    path = path.resolve(strict=True)
    if (path.parent.parent != Path(tempfile.gettempdir()).resolve()
            or not path.parent.name.startswith("r4-refund-model-")
            or path.name != "refund_binding_fixture.sqlite3"):
        raise ValueError("only dedicated synthetic fixture allowed")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
        raise ValueError("unsafe synthetic fixture")
    return path


def prepared_binding(db, case_id):
    row = db.execute("SELECT binding FROM mock_review_preparation WHERE case_id=?", (case_id,)).fetchone()
    if not row or not isinstance(row[0], str) or not HEX.fullmatch(row[0]):
        raise ValueError("fixture preparation is unavailable")
    return row[0]


def reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate model decision field")
        result[key] = value
    return result


def review_fixture(path, preparation, model, official_world):
    """Called only by the trusted harness, never by Mind tools or public A2A."""
    path = fixture_db(path)
    summary = project(preparation)
    case_id = summary["case_id"]
    with closing(sqlite3.connect(path)) as db:
        binding = prepared_binding(db, case_id)
        if db.execute("SELECT 1 FROM mock_host_model_decision WHERE case_id=?", (case_id,)).fetchone():
            raise ValueError("fixture already has a host decision")
    messages = [
        {"role": "system", "content": official_world + "\n"
         "Review one synthetic R4 refund from the verified evidence summary. "
         "Exercise your own judgment. Return one JSON object with the sole key decision, "
         "whose value is approve, decline, or needs_evidence. Do not request private fields or use tools."},
        {"role": "user", "content": json.dumps(summary, ensure_ascii=False, sort_keys=True)},
    ]
    raw = model.complete(messages, max_tokens=250, timeout=180)
    if not isinstance(raw, str) or len(raw) > 2048:
        raise ValueError("invalid model response")
    answer = json.loads(raw, object_pairs_hook=reject_duplicate_keys)
    if not isinstance(answer, dict) or set(answer) != {"decision"} or answer["decision"] not in (
        "approve", "decline", "needs_evidence",
    ):
        raise ValueError("invalid model decision")
    judgment = answer["decision"]
    response_sha = sha256(raw.encode("utf-8")).hexdigest()
    event_id = None
    with closing(sqlite3.connect(path, isolation_level=None)) as db:
        db.execute("BEGIN IMMEDIATE")
        if prepared_binding(db, case_id) != binding:
            raise ValueError("prepared evidence changed during review")
        if judgment in OUTCOMES:
            event_id = sha256(json.dumps(
                ["r4-refund-model-event-v1", case_id, binding, judgment, response_sha, secrets.token_hex(32)],
                separators=(",", ":"),
            ).encode()).hexdigest()
            db.execute("INSERT INTO mock_host_model_decision(case_id,event_id,binding,decision) VALUES(?,?,?,?)",
                       (case_id, event_id, binding, OUTCOMES[judgment]))
        db.commit()
    return {"case_id": case_id, "model_decision": judgment, "preparation_digest": binding,
            "model_response_sha256": response_sha, "host_event_id": event_id}

