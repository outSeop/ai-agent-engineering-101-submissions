"""Windows stdin/stdout bridge for official cli_model.py, with fail-closed event validation."""
import json
from hashlib import sha256
import os
from pathlib import Path
import subprocess
import sys
import tempfile

BINARY = Path(r"C:\Users\108\AppData\Local\OpenAI\Codex\bin\c38161ad8494f88c\codex.exe")


def verified_reply(events, last):
    completed = []
    turn_completed = False
    for line in events.splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        kind = event["type"]
        if kind == "turn.completed":
            turn_completed = True
        elif kind in {"item.started", "item.updated", "item.completed"}:
            item = event["item"]
            if item["type"] not in {"agent_message", "reasoning"}:
                raise ValueError("forbidden tool event")
            if kind == "item.completed" and item["type"] == "agent_message":
                completed.append(item["text"].strip())
        elif kind not in {"thread.started", "turn.started"}:
            raise ValueError("unsupported event")
    reply = last.strip()
    if not turn_completed or not reply or not completed or completed[-1] != reply:
        raise ValueError("missing verified final reply")
    return reply


def workdir():
    path = Path(tempfile.mkdtemp(prefix="r4-cli-mind-"))
    system = Path(os.environ["SystemRoot"]) / "System32"
    who = subprocess.check_output([str(system / "whoami.exe"), "/user", "/fo", "csv", "/nh"])
    import csv
    sid = next(csv.reader(who.decode("ascii", "replace").splitlines()))[-1]
    if not sid.startswith("S-1-"):
        raise ValueError("unexpected user identity")
    subprocess.run(
        [str(system / "icacls.exe"), str(path), "/inheritance:r", "/grant:r", f"*{sid}:(OI)(CI)F"],
        check=True, capture_output=True, timeout=5,
    )
    return path


def main():
    text = sys.stdin.buffer.read(500001)
    if not text.strip() or len(text) > 500000:
        raise ValueError("invalid prompt")
    text.decode("utf-8", "strict")
    path = workdir()
    last = path / "last.txt"
    command = [
        str(BINARY), "exec", "--skip-git-repo-check", "--ignore-user-config", "--ephemeral",
        "-s", "read-only", "-m", "gpt-6.2-sol", "-c", "model_reasoning_effort=high",
        "--color", "never", "--json", "-o", str(last), "-",
    ]
    metadata = {"requested_model": "gpt-6.2-sol", "upstream_reported_model": None,
                "cli_returncode": None, "tool_event_count": None, "reply_sha256": None,
                "error_type": None, "reasoning_effort": "high", "cli_timeout_seconds": 300}
    try:
        result = subprocess.run(
            command, cwd=path, capture_output=True, timeout=300,
            input=text + b"\nReturn the next assistant message only. Do not call tools, run commands, or read files.",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        metadata["cli_returncode"] = result.returncode
        (path / "events.jsonl").write_bytes(result.stdout)
        events = result.stdout.decode("utf-8")
        items = [json.loads(line).get("item") for line in events.splitlines() if line.strip()]
        metadata["tool_event_count"] = sum(
            isinstance(item, dict) and item.get("type") not in {"agent_message", "reasoning"}
            for item in items
        )
        if result.returncode:
            raise ValueError("completion failed")
        reply = verified_reply(events, last.read_text(encoding="utf-8"))
        metadata["reply_sha256"] = sha256(reply.encode("utf-8")).hexdigest()
    except Exception as error:
        metadata["error_type"] = type(error).__name__
        if isinstance(error, subprocess.TimeoutExpired) and error.stdout:
            (path / "events.jsonl").write_bytes(error.stdout)
        raise
    finally:
        (path / "metadata.json").write_text(json.dumps(metadata) + "\n", encoding="utf-8")
    sys.stdout.buffer.write((reply + "\n").encode("utf-8"))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.stderr.write("Isolated Codex CLI completion failed.\n")
        sys.exit(1)

