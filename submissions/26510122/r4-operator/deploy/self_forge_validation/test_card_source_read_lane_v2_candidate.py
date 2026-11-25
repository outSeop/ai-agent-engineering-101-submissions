import json
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock

from card_source_read_lane_v2_candidate import ARCHIVE, PIN, READER, checked_read, expected_slice, load_reviewed_reads

OP=next(p for p in Path(__file__).resolve().parents if (p/"kit/agent_kit.py").is_file())
ORIGIN=OP/"runtime/class-rebuild-reach-20261125/tools"


class ReaderV2(TestCase):
    def setUp(self):
        tmp=TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.tools_dir=self.root/"tools"
        self.tools_dir.mkdir()
        for name in (READER,"stage_representative_card"):
            shutil.copytree(ORIGIN/name,self.tools_dir/name)
        (self.tools_dir/".deprecated").mkdir()
        shutil.copytree(ORIGIN/".deprecated"/ARCHIVE,self.tools_dir/".deprecated"/ARCHIVE)
        self.reader={READER:{"dir":self.tools_dir/READER,"perm":{}}}

    def args(self,name,offset=0):
        return {"name":name,"file":"logic.py","offset":offset}

    def deny_before_call(self,args):
        call=Mock()
        self.assertEqual(checked_read(self.root,self.reader,args,(),call)["ok"],False)
        call.assert_not_called()

    def test_pinned_active_and_archive_with_exact_unicode_slice(self):
        for label in ("stage_representative_card",ARCHIVE):
            args=self.args(label,2000)
            result=expected_slice(self.root,self.reader,args,())
            self.assertEqual((result["offset"],result["next_offset"],len(result["source"])),(2000,4000,2000))
            self.assertEqual(checked_read(self.root,self.reader,args,(),lambda:{"ok":True,"result":result})["ok"],True)
            corrupted={**result,"total_chars":100}
            self.assertFalse(checked_read(self.root,self.reader,args,(),lambda:{"ok":True,"result":corrupted})["ok"])

    def test_manifest_middle_file_or_ambiguous_archive_fails_closed(self):
        path=self.tools_dir/".deprecated"/ARCHIVE/"test.py"
        path.write_text("tampered")
        self.deny_before_call(self.args(ARCHIVE))
        path=self.tools_dir/"stage_representative_card/test.py"
        duplicate=self.root/"same-content.py"
        duplicate.write_bytes(path.read_bytes())
        path.unlink()
        os.link(duplicate,path)
        self.deny_before_call(self.args("stage_representative_card"))

    def test_reader_permissions_manifest_and_unapproved_names(self):
        manifest=self.root/"review.json"
        manifest.write_text(json.dumps({READER:{"sha256":PIN}}))
        manifest.chmod(0o600)
        self.assertEqual(load_reviewed_reads(manifest)[READER]["sha256"],PIN)
        self.deny_before_call(self.args("notes.md"))
        self.deny_before_call({**self.args(ARCHIVE),"wallet":"guessed"})
        self.reader[READER]["perm"]={"write":["file"]}
        self.deny_before_call(self.args(ARCHIVE))
        self.reader[READER]["perm"]={}
        (self.root/".deprecated").mkdir()
        self.deny_before_call(self.args(ARCHIVE))

