from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from class_variant_support import NAME, read_intent, reviewed_snapshot, write_snapshot


class VariantTest(TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.operator = Path(temp.name)
        self.runtime = self.operator / "runtime"
        self.source = self.runtime / "class-rebuild-fixture"
        self.tool = self.source / "tools" / NAME
        self.tool.mkdir(parents=True)
        (self.source / ".kit").mkdir()
        for filename in ("logic.py", "test.py", "permission.yml"):
            (self.tool / filename).write_text(filename)
        self.hashes = {p.name: sha256(p.read_bytes()).hexdigest() for p in self.tool.iterdir()}
        self.pin = self.hashes["logic.py"]
        self.write(self.tool / "forge.json", {"tool": NAME, "version": 1, "sha256": self.hashes})
        self.write(self.source / "generation-origin-proof.json", {
            "actual_class_model": True, "official_mind": True, "records": [{
                "tool": NAME, "version": 1, "source_sha256": self.pin,
                "class_generation_matches": [{"official_system_prefix": True, "raw_response_sha256": "1" * 64}],
            }],
        })
        approved = self.source / ".kit" / "reviewed-public-reads.json"
        self.write(approved, {NAME: {"sha256": self.pin, "urls": ["https://market.ourolabs.ai/agent.md"]}})
        approved.chmod(0o600)
        pin = patch("class_variant_support.PIN", self.pin)
        pin.start()
        self.addCleanup(pin.stop)

    def write(self, path, data):
        path.write_text(json.dumps(data))

    def test_original_files_reused_and_namespace_kept_separate(self):
        snapshot = reviewed_snapshot(self.operator, self.source)
        destination = self.runtime / "class-rebuild-other"
        (destination / "tools").mkdir(parents=True)
        (destination / ".kit").mkdir()
        origin = write_snapshot(destination, snapshot)
        for source in self.tool.iterdir():
            self.assertEqual(source.read_bytes(), (destination / "tools" / NAME / source.name).read_bytes())
        self.assertEqual(origin["record_type"], "derived_tool_reuse")
        self.assertFalse((destination / "logs" / "forge.jsonl").exists())

    def test_tampered_and_symlinked_source_rejected(self):
        logic = self.tool / "logic.py"
        logic.write_text("changed")
        with self.assertRaises(ValueError):
            reviewed_snapshot(self.operator, self.source)
        logic.unlink()
        logic.symlink_to(self.tool / "test.py")
        with self.assertRaises(ValueError):
            reviewed_snapshot(self.operator, self.source)

    def test_intent_has_only_two_editable_fields(self):
        path = self.operator / "intent.json"
        self.write(path, {"persona": "valid", "goal": "valid"})
        self.assertEqual(read_intent(path)["goal"], "valid")
        self.write(path, {"persona": "valid", "goal": "valid", "llm": "invalid"})
        with self.assertRaises(ValueError):
            read_intent(path)

