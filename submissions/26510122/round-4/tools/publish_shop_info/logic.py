"""Validate and publish public A2A shop copy. OpenAI Codex GPT-6.2 Sol."""
import fcntl
import json
import os
from pathlib import Path
import re

CARD = Path("card.json")
SHOP = "outseop-r4"
SKILL_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,47}")


def text(value, maximum):
    if (not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum
            or any(ord(char) < 32 and char not in ("\n", "\t") for char in value)):
        raise ValueError("invalid public text")
    return value.strip()


def sequence(value, maximum, minimum=0):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError("public list length is out of bounds")
    return value


def normalize(args):
    if not isinstance(args, dict) or set(args) != {"description", "skills"}:
        raise ValueError("expected description and skills only")
    result = []
    ids = set()
    for item in sequence(args["skills"], 8):
        if (not isinstance(item, dict) or not {"id", "name", "description", "tags"} <= set(item)
                or set(item) - {"id", "name", "description", "tags", "examples"}):
            raise ValueError("unsupported skill fields")
        ident = item["id"]
        if not isinstance(ident, str) or not SKILL_ID.fullmatch(ident) or ident in ids:
            raise ValueError("skill identifiers must be unique lowercase slugs")
        ids.add(ident)
        skill = {"id": ident, "name": text(item["name"], 80), "description": text(item["description"], 500),
                 "tags": [text(tag, 32) for tag in sequence(item["tags"], 8, 1)]}
        if "examples" in item:
            skill["examples"] = [text(example, 220) for example in sequence(item["examples"], 6)]
        result.append(skill)
    return {"description": text(args["description"], 1000), "skills": result}


def run(args, kit):
    try:
        public = normalize(args)
        if kit.name != SHOP or CARD.is_symlink():
            raise ValueError("existing shop identity is required")
        # Only card.json can be written. An advisory lock serializes publishers.
        with CARD.open("r+", encoding="utf-8") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            existing = stream.read(64_001)
            if len(existing)>64_000:
                raise ValueError("existing card is too large")
            card = json.loads(existing)
            if not isinstance(card, dict) or card.get("name") != SHOP:
                raise ValueError("existing card has a different identity")
            updated = json.dumps(dict(card, **public), ensure_ascii=False, indent=2) + "\n"
            if updated != existing:
                stream.seek(0)
                try:
                    stream.write(updated)
                    stream.truncate()
                    stream.flush()
                    os.fsync(stream.fileno())
                except OSError:
                    stream.seek(0)
                    stream.write(existing)
                    stream.truncate()
                    stream.flush()
                    raise
        return {"status": "published", "name": SHOP, "skills": len(public["skills"])}
    except (ValueError, OSError):
        return {"status": "rejected", "reason": "invalid metadata or existing shop card"}

