import json
from unittest import TestCase

from successful_forge_resume_memory import extract, hash_bytes, PROVIDER


class SuccessMemory(TestCase):
    def sample(self, verdict="passed", provider=PROVIDER, logic="logic", version=2):
        request=json.dumps({"action":"forge_tool","thought":"secret thought",
                            "args":{"name":"apply_staged_card","logic":logic,"test":"test"}})
        root=[{"role":"system","content":"world prefix"}]
        post=root+[{"role":"assistant","content":request},{"role":"user","content":
            "Observation: "+json.dumps({"test":verdict,"tool":"apply_staged_card","version":version})}]
        return b"\n".join(json.dumps(entry).encode() for entry in (
            {"model_provider":provider,"messages":root,"response":request},
            {"model_provider":provider,"messages":post,"response":"{}"},
        ))

    def pin(self, logic="logic"):
        return {"version":2,"sha256":{"logic.py":hash_bytes(logic.encode()),"test.py":hash_bytes(b"test")}}

    def test_one_exact_success_and_no_thought(self):
        memory,meta=extract(self.sample(),"world",json.loads,(),self.pin())
        self.assertNotIn("secret thought",memory)
        self.assertEqual(meta["version"],2)
        self.assertEqual(json.loads(memory)["official_forge"]["test"],"passed")

    def test_refuses_error_wrong_provider_version_source_and_exact_secret(self):
        for setting in ({"verdict":"failed"},{"provider":"market-class"},{"logic":"wrong"},{"version":1}):
            with self.subTest(setting=setting),self.assertRaises(ValueError):
                extract(self.sample(**setting),"world",json.loads,(),self.pin())
        with self.assertRaises(ValueError):
            extract(self.sample(),"world",json.loads,(b"logic",),self.pin())

