"""Extract a single rejected, unexecuted apply proposal from the current private session."""
from hashlib import sha256
import json
import os
from pathlib import Path
import stat

from card_source_read_lane import PATTERN, credentials


PROVIDER="codex-cli-gpt-6.2-sol"
REJECTION="error: logic must be Python source that defines run(args, kit)"
FIELDS={"name","logic","test","description","permission"}


def hash_bytes(value):
    return sha256(value).hexdigest()


def load_private(root):
    root=Path(root)
    directory=root/".kit"
    if any(path.resolve(strict=True)!=path or path.stat().st_uid!=os.getuid()
           or not stat.S_ISDIR(path.stat().st_mode) or path.stat().st_mode & 0o077
           for path in (root,directory)):
        raise ValueError("unsafe proposal history directory")
    fd=os.open(directory/"model-calls-private.jsonl",os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,"rb") as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1 or stat.S_IMODE(info.st_mode)!=0o600:
            raise ValueError("unsafe proposal history file")
        if info.st_size>32*1024*1024:
            raise ValueError("proposal history exceeds size limit")
        return stream.read(32*1024*1024+1)


def extract(raw, world, parse, needles):
    seen=set()
    match=None
    for line in raw.splitlines():
        entry=json.loads(line)
        if entry.get("model_provider")!=PROVIDER:
            continue
        messages=entry.get("messages")
        if not messages or messages[0].get("role")!="system" or not messages[0].get("content","").startswith(world):
            continue
        for previous,observed in zip(messages,messages[1:]):
            if previous.get("role")!="assistant" or observed.get("role")!="user":
                continue
            request=previous.get("content")
            outcome=observed.get("content")
            if (not isinstance(request,str) or request not in seen or not isinstance(outcome,str)
                    or outcome.split("\n",1)[0]!="Observation: "+REJECTION):
                continue
            action=parse(request)
            if not isinstance(action,dict) or action.get("action")!="forge_tool":
                continue
            args=action.get("args")
            if not isinstance(args,dict) or args.get("name")!="apply_staged_card":
                continue
            if (not {"name","logic","test"}<=set(args)<=FIELDS
                or any(not isinstance(args[field],str) or len(args[field])>65536 for field in ("logic","test"))
                or ("description" in args and not isinstance(args["description"],str))
                or ("permission" in args and not isinstance(args["permission"],dict))):
                raise ValueError("proposal arguments do not meet private resume boundary")
            match=(request,args)
        response=entry.get("response")
        if isinstance(response,str):
            seen.add(response)
    if match is None:
        raise ValueError("no matching official rejected apply proposal")
    request,args=match
    message=json.dumps({"tool_args":args,"official_rejection":REJECTION},ensure_ascii=False,sort_keys=True)
    payload=message.encode()
    if len(payload)>150000 or any(needle in payload for needle in needles) or PATTERN.search(payload):
        raise ValueError("unsafe rejected proposal memory")
    metadata={"provider":PROVIDER,"official_system_prefix":True,"tool":"apply_staged_card",
              "source_request_sha256":hash_bytes(request.encode()),
              "logic_sha256":hash_bytes(args["logic"].encode()),"test_sha256":hash_bytes(args["test"].encode()),
              "memory_sha256":hash_bytes(payload),"memory_fields":["tool_args","official_rejection"]}
    return message,metadata


def prepare(root,operator,world,parse):
    return extract(load_private(root),world,parse,credentials(operator))

