from pathlib import Path
import json
import os
from shutil import copytree, copy2
from subprocess import run
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase

HERE = Path(__file__).resolve().parent
OP = HERE.parents[3]
LIVE = OP.parent / "round-4"
STAGE = HERE.parent / "validation"
V3 = os.environ.get("R4_TEST_CATALOGUE_RELEASE", "public_catalogue_runtime_v1")


class LauncherValidation(TestCase):
    def test_real_cli_check_default_opt_in_and_tamper(self):
        if not (STAGE/V3/"MANIFEST.json").is_file():
            self.skipTest("independently pinned catalogue not yet available")
        with TemporaryDirectory() as temp:
            parent = Path(temp)
            op, root = parent / "r4-operator", parent / "round-4"
            (op / "deploy").mkdir(parents=True)
            (op / "sources").mkdir()
            (root / "tools").mkdir(parents=True)
            copytree(OP / "kit", op / "kit", ignore=lambda _, names:[n for n in names if n.startswith("__")])
            copy2(OP / "sources/upstream.json", op / "sources/upstream.json")
            copytree(LIVE / "codex-r4", root / "codex-r4", ignore=lambda _, names:[n for n in names if not n.endswith(".py")])
            (root / "agent.json").write_text('{"llm":{"base":"market"}}')
            for name in ("a2a_info","shop_info","stock_procurement","forum_marketing","publish_shop_info"):
                for leaf in ("forge.json","logic.py","test.py","permission.yml"):
                    dest=root/"tools"/name/leaf
                    dest.parent.mkdir(exist_ok=True)
                    copy2(LIVE/"tools"/name/leaf,dest)
            launcher=root/"codex-r4/managed_launcher.py"
            copy2(STAGE/(V3+"-launcher.py"),launcher)
            copytree(STAGE/V3,op/"deploy"/V3)
            cmd=[sys.executable,str(launcher),"check","--operator-dir",str(op),"--agent-root",str(root),
                 "--enable-procurement"]
            clean={k:v for k,v in os.environ.items() if not k.startswith("R4_")}
            def check(*opts):
                return run(cmd+list(opts),capture_output=True,text=True,env=clean,timeout=15)
            for opts, expected in (((),False),(("--enable-public-catalogue",),True)):
                checked=check(*opts)
                self.assertEqual(checked.returncode,0,checked.stderr)
                result=json.loads(checked.stdout.strip().splitlines()[-1])
                self.assertFalse(result["joined_or_started"])
                self.assertEqual(result["public_catalogue"],expected)
                self.assertEqual(result["official_kit_files_verified"],7)
            self.assertFalse((root/"state").exists())
            pin=op/"deploy"/V3/"catalogue"/"logic.py"
            pin.chmod(0o600)
            pin.write_bytes(pin.read_bytes()+b"\n")
            rejected=check("--enable-public-catalogue")
            self.assertNotEqual(rejected.returncode,0)
            self.assertIn("artifact changed",rejected.stderr)

