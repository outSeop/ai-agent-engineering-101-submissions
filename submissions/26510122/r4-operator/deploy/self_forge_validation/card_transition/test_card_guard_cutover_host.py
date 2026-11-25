from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from card_guard_cutover_host import NAME, NEW, OLD, approved_guard_probe, bundle, fence


OP = next(p for p in Path(__file__).resolve().parents if (p/"kit/agent_kit.py").is_file())
PROD = OP.parent/"round-4"
SOURCE = OP/"runtime/class-rebuild-reach-20261125/tools"/NAME


class CutoverTest(TestCase):
    def setUp(self):
        temp=TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.session=self.root/"session"
        self.session.mkdir()
        self.stage=self.root/"production-fixture"
        self.target=self.stage/"tools"/NAME
        self.target.mkdir(parents=True)
        archive=OP/"runtime/card-cutover-live-20261125/legacy-publisher"
        self.old=bundle(archive if archive.is_dir() else PROD/"tools"/NAME,OLD)
        for name,data in self.old.items():
            (self.target/name).write_bytes(data)
        self.new=bundle(SOURCE,NEW)
        (self.stage/"card.json").write_bytes(b'{"name":"outseop-r4"}')
        mock=patch("card_guard_cutover_host.running_tool",return_value=False)
        mock.start()
        self.addCleanup(mock.stop)

    def run_fence(self,probe):
        return fence(self.stage,self.session,self.new,OP/"kit",sleep=lambda _:None,probe=probe)

    def test_real_guard_waits_in_temporary_toolbox(self):
        before=(self.stage/"card.json").read_bytes()
        result=self.run_fence(approved_guard_probe)
        self.assertEqual(result["status"],"fenced")
        self.assertEqual(bundle(self.target,NEW),self.new)
        self.assertEqual(bundle(self.session/"legacy-publisher",OLD),self.old)
        self.assertEqual((self.stage/"card.json").read_bytes(),before)

    def test_probe_failure_rolls_back_exact_bundle(self):
        def fail(*args):
            raise ValueError("fixture probe fault")
        with self.assertRaisesRegex(ValueError,"fixture probe fault"):
            self.run_fence(fail)
        self.assertEqual(bundle(self.target,OLD),self.old)

    def test_autorestore_refused_after_native_progress(self):
        def progress(*args):
            (self.stage/"card_publication/head.json").write_text("{}")
            raise ValueError("fixture state changed")
        with self.assertRaisesRegex(RuntimeError,"automatic restore refused"):
            self.run_fence(progress)
        self.assertEqual(bundle(self.target,NEW),self.new)

