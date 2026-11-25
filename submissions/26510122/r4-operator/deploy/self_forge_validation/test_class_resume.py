import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from run_class_rebuild_resume import isolate_root


class ResumeTests(TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.operator = Path(tmp.name)
        self.runtime = self.operator / "runtime"
        self.runtime.mkdir()
        self.root = self.runtime / "class-rebuild-fixture"
        self.agent = {"llm": {"base": "market"}, "persona": "initial", "goal": "initial", "run_minutes": 8}

    def initial(self):
        root, lock, _ = isolate_root(self.operator, self.root, False, self.agent)
        os.close(lock)
        (root / "agent.json").write_text(json.dumps(self.agent))
        (root / "logs" / "agent-kit.log").touch()
        return root

    def test_reuse_preserves_prior_evidence_and_locks_session(self):
        root = self.initial()
        private = root / "logs" / "console-private.log"
        private.touch(mode=0o600)
        private.write_text("fixture previous log")
        _, lock, _ = isolate_root(self.operator, root, True, self.agent)
        try:
            self.assertEqual(private.read_text(), "fixture previous log")
            with self.assertRaises(BlockingIOError):
                isolate_root(self.operator, root, True, self.agent)
        finally:
            os.close(lock)

    def test_refuses_production_or_symlink(self):
        root = self.initial()
        (root / "tools" / "bad").symlink_to(self.operator)
        with self.assertRaises(ValueError):
            isolate_root(self.operator, root, True, self.agent)
        with self.assertRaises(ValueError):
            isolate_root(self.operator, self.operator / "round-4", True, self.agent)

    def test_refuses_changed_agent(self):
        self.initial()
        with self.assertRaises(ValueError):
            isolate_root(self.operator, self.root, True, {"llm": {"base": "other"}})


    def test_steering_preserves_exact_settings(self):
        root = self.initial()
        config = root / "agent.json"
        steered = dict(self.agent, persona="updated persona", goal="updated goal")
        config.write_text(json.dumps(steered))
        _, lock, actual = isolate_root(self.operator, root, True, self.agent)
        try:
            self.assertEqual(actual, steered)
        finally:
            os.close(lock)
        for altered in (
            dict(steered, llm={"base": "other"}),
            dict(steered, run_minutes=30),
            dict(steered, extra_setting="invalid"),
            dict(steered, goal=" "),
            dict(steered, persona="a" * 16385),
        ):
            with self.subTest(settings=list(altered)):
                config.write_text(json.dumps(altered))
                with self.assertRaises(ValueError):
                    isolate_root(self.operator, root, True, self.agent)
