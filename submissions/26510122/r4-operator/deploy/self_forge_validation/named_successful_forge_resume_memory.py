"""Private same-session continuity for the current successful selected-tool forge."""
import json

from card_source_read_lane import PATTERN, credentials, raw_file, safe_directory
from rejected_forge_resume_memory import FIELDS, PROVIDER, hash_bytes, load_private


TOOL = "apply_staged_card"
TOOLS = frozenset({TOOL, "read_customer_offers", "refresh_representative_card"})


def extract(raw, world, parse, needles, manifest, *, tool_name=TOOL):
    if tool_name not in TOOLS:
        raise ValueError("unsupported proposal continuity tool")
    seen=set()
    match=None
    unit=(tool_name,manifest["version"])
    for line in raw.splitlines():
        event=json.loads(line)
        context=event.get("messages")
        if (event.get("model_provider")!=PROVIDER or not context or context[0].get("role")!="system"
            or not context[0].get("content","").startswith(world)):
            continue
        for request,observation in zip(context,context[1:]):
            call=request.get("content")
            outcome=observation.get("content")
            if (request.get("role")!="assistant" or observation.get("role")!="user"
                or not isinstance(call,str) or call not in seen or not isinstance(outcome,str)
                or not outcome.startswith("Observation: {")):
                continue
            try:
                verdict=json.JSONDecoder().raw_decode(outcome[len("Observation: "):])[0]
            except ValueError:
                continue
            if not isinstance(verdict,dict) or verdict.get("test")!="passed" or (verdict.get("tool"),verdict.get("version"))!=unit:
                continue
            action=parse(call)
            if not isinstance(action,dict) or action.get("action")!="forge_tool":
                continue
            args=action.get("args")
            if (not isinstance(args,dict) or args.get("name")!=tool_name
                or not {"name","logic","test"}<=set(args)<=FIELDS):
                continue
            if (not all(isinstance(args[key],str) and len(args[key])<=65536 for key in ("logic","test"))
                or any(hash_bytes(args[key].encode())!=manifest["sha256"][key+".py"] for key in ("logic","test"))):
                continue
            match=(call,args)
        response=event.get("response")
        if isinstance(response,str):
            seen.add(response)
    if match is None:
        raise ValueError("no matching current successful selected-tool forge")
    call,args=match
    message=json.dumps({"tool_args":args,"official_forge":{"test":"passed","tool":tool_name,"version":unit[1]}},
                       ensure_ascii=False,sort_keys=True)
    payload=message.encode()
    if len(payload)>150000 or any(needle in payload for needle in needles) or PATTERN.search(payload):
        raise ValueError("unsafe successful proposal memory")
    return message,{"provider":PROVIDER,"official_system_prefix":True,"tool":tool_name,"version":unit[1],
                    "source_request_sha256":hash_bytes(call.encode()),"logic_sha256":manifest["sha256"]["logic.py"],
                    "test_sha256":manifest["sha256"]["test.py"],"memory_sha256":hash_bytes(payload),
                    "memory_fields":["tool_args","official_forge"]}


def prepare(root,operator,world,parse,*,tool_name=TOOL):
    if tool_name not in TOOLS:
        raise ValueError("unsupported proposal continuity tool")
    path=safe_directory(safe_directory(root/"tools")/tool_name)
    manifest=json.loads(raw_file(path/"forge.json"))
    if (manifest.get("tool")!=tool_name or type(manifest.get("version")) is not int
        or not 1<=manifest["version"]<=1000
        or any(hash_bytes(raw_file(path/name))!=manifest.get("sha256",{}).get(name)
               for name in ("logic.py","test.py","permission.yml"))):
        raise ValueError("current selected tool manifest mismatch")
    return extract(load_private(root),world,parse,credentials(operator),manifest,tool_name=tool_name)

