"""Host-only source pagination checks for one previously reviewed forged reader."""
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat

READER = "read_card_tool_source"
PIN = "ad0ad20cbacea6b3383447cb531346f6036ade6d1043534a5ee627f43443baaf"
READER_FILES = {
    "logic.py": PIN,
    "test.py": "58ed90979bc22f5dc7374238e4677ac6cc22f942c940bdbef5cb3971d0b98cc3",
    "permission.yml": "1743be76d79b8469fd2291c735e17e8ca578fe9a7b9fe76ddacc62a20cf4f100",
}
TARGETS = {"apply_staged_card", "stage_representative_card", "publish_shop_info"}
FILES = {"logic.py", "test.py"}
PATTERN = re.compile(rb"(?i)eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{12,}|(?:sk-(?:proj-)?|ghp_|github_pat_|xoxb-)[A-Za-z0-9_-]{18,}|Bearer\s+[A-Za-z0-9_-]{24,}|BEGIN [A-Z ]*PRIVATE KEY")


def credentials(operator):
    production = operator.parent / "round-4"
    paths = (production/"shop_wallet.key", production/"buyer_wallet.key", production/".kit/worker-token",
             Path.home()/".config/ourolabs-market/owner-code")
    needles = set()
    for path in paths:
        value=path.read_bytes().strip()
        if len(value)<8:
            raise ValueError("credential self-exclusion prerequisite failed")
        needles.add(value)
        for chunk in re.findall(rb"(?:0x)?[A-Fa-f0-9]{64}",value):
            needles.update((chunk,chunk.removeprefix(b"0x"),chunk.lower(),chunk.upper()))
    return frozenset(needles)


def safe_directory(path):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise ValueError("untrusted source directory")
    return path


def raw_file(path):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,"rb") as stream:
        info=os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1
            or info.st_mode & 0o022 or info.st_size>1024*1024):
            raise ValueError("untrusted source file")
        raw=stream.read(1024*1024+1)
    if len(raw)>1024*1024:
        raise ValueError("untrusted source size")
    return raw


def expected_slice(root, tools, args, needles):
    if not isinstance(args,dict) or set(args)!={"name","file","offset"}:
        raise ValueError("unknown reader arguments")
    name, filename, offset = args["name"],args["file"],args["offset"]
    if (not isinstance(name,str) or name not in TARGETS or not isinstance(filename,str)
        or filename not in FILES or type(offset) is not int or offset<0):
        raise ValueError("invalid reader arguments")
    reader = tools.get(READER)
    if not reader or any(reader["perm"].get(k) for k in ("network","wallet","identity","exec","write")):
        raise ValueError("unsafe reader permissions")
    path=safe_directory(safe_directory(root)/"tools")
    directory=safe_directory(path/READER)
    if Path(reader["dir"])!=directory:
        raise ValueError("unexpected reader directory")
    for file,digest in READER_FILES.items():
        if sha256(raw_file(directory/file)).hexdigest()!=digest:
            raise ValueError("reader source changed")
    target=safe_directory(path/name)
    raw=raw_file(target/filename)
    manifest=json.loads(raw_file(target/"forge.json"))
    digest=sha256(raw).hexdigest()
    if manifest.get("tool")!=name or manifest.get("sha256",{}).get(filename)!=digest:
        raise ValueError("tool source does not match forge")
    if any(needle in raw for needle in needles) or PATTERN.search(raw):
        raise ValueError("tool source sensitive pattern")
    source=raw.decode("utf-8")
    if offset>len(source):
        raise ValueError("source offset outside file")
    end=min(offset+2000,len(source))
    return {"sha256":digest,"offset":offset,"next_offset":end if end<len(source) else None,
            "total_chars":len(source),"source":source[offset:end]}


def checked_read(root,tools,request,needles,invoke):
    rejected={"ok":False,"error":"card source read rejected"}
    try:
        expected=expected_slice(root,tools,request,needles)
        output=invoke()
        if output!={"ok":True,"result":expected}:
            return rejected
        if expected_slice(root,tools,request,needles)!=expected:
            return rejected
        return output
    except (OSError,KeyError,TypeError,ValueError,AttributeError):
        return rejected

