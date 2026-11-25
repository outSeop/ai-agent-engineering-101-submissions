import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from rejected_forge_resume_memory import PROVIDER, REJECTION, extract, load_private


class MemoryTest(TestCase):
    def inputs(self,provider=PROVIDER,warning=REJECTION,title="apply_staged_card",logic="mock logic"):
        response=json.dumps({"thought":"private thought","action":"forge_tool",
                             "args":{"name":title,"logic":logic,"test":"mock test","permission":{}}})
        initial=[{"role":"system","content":"official world prefix"}]
        follow=initial+[{"role":"assistant","content":response},{"role":"user","content":"Observation: "+warning}]
        return b"\n".join(json.dumps(record).encode() for record in (
            {"model_provider":provider,"messages":initial,"response":response},
            {"model_provider":provider,"messages":follow,"response":"{}"},
        ))

    def test_only_expected_args_and_error_retained(self):
        message,meta=extract(self.inputs(),"official world",json.loads,())
        self.assertNotIn("thought",message)
        self.assertEqual(json.loads(message)["official_rejection"],REJECTION)
        self.assertEqual(meta["provider"],PROVIDER)
        self.assertEqual(set(json.loads(message)),{"tool_args","official_rejection"})

    def test_wrong_provider_tool_prefix_and_rejection_refused(self):
        for args in ({"provider":"market-class"},{"warning":"other error"},{"title":"other_tool"}):
            with self.subTest(args=args),self.assertRaises(ValueError):
                extract(self.inputs(**args),"official world",json.loads,())
        with self.assertRaises(ValueError):
            extract(self.inputs(),"different",json.loads,())

    def test_missing_matching_earlier_response_and_secret_refused(self):
        with self.assertRaises(ValueError):
            extract(self.inputs().splitlines()[1],"official world",json.loads,())
        with self.assertRaises(ValueError):
            extract(self.inputs(logic="private token"),"official world",json.loads,(b"private token",))

    def test_symlink_hardlink_and_nonprivate_file_refused(self):
        with TemporaryDirectory() as temp:
            root=Path(temp)
            directory=root/".kit"
            directory.mkdir(mode=0o700)
            path=directory/"model-calls-private.jsonl"
            elsewhere=root/"other"
            elsewhere.write_bytes(self.inputs())
            elsewhere.chmod(0o600)
            path.symlink_to(elsewhere)
            with self.assertRaises(OSError):
                load_private(root)
            path.unlink()
            os.link(elsewhere,path)
            with self.assertRaises(ValueError):
                load_private(root)
            path.unlink()
            path.write_bytes(self.inputs())
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                load_private(root)
            path.chmod(0o600)
            self.assertEqual(load_private(root),self.inputs())

