"""Execute a reviewed generated public catalogue in the ordinary official sandbox."""
from contextlib import redirect_stderr, redirect_stdout
from hashlib import sha256
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from tempfile import TemporaryDirectory


NAME="public_catalogue"
REQUIRED={"logic.py","permission.yml","test.py","forge.json"}


def verified_catalogue(directory,pins):
    from card_source_read_lane import raw_file,safe_directory

    safe_directory(directory)
    if not isinstance(pins,dict) or set(pins)!=REQUIRED:
        raise ValueError("catalogue pins must identify all official files")
    files={name:raw_file(directory/name) for name in REQUIRED}
    if any(sha256(files[name]).hexdigest()!=digest for name,digest in pins.items()):
        raise ValueError("catalogue source does not match reviewed hashes")
    manifest=json.loads(files["forge.json"])
    if (manifest.get("tool")!=NAME or type(manifest.get("version")) is not int
        or manifest["sha256"]!={name:digest for name,digest in pins.items() if name!="forge.json"}):
        raise ValueError("catalogue forge manifest mismatch")
    return files


def instruction_from(directory,pins,official):
    files=verified_catalogue(directory,pins)
    metadata=official.forge_runner.parse_permission(files["permission.yml"].decode())
    permission=metadata.get("permission") or {}
    if (any(permission.get(key) for key in ("wallet","identity","network","write","exec","handles"))
        or permission.get("pay_limit",0)!=0):
        raise ValueError("catalogue must be read-only and credential-free")
    instruction=metadata["description"]
    if not isinstance(instruction,str) or not instruction or len(instruction)>600:
        raise ValueError("catalogue instruction is incomplete")
    return instruction


class BoundedPublicCatalogue:
    def __init__(self,source,kit,scratch,pins):
        self.source=source
        self.kit=kit
        self.scratch=scratch
        self.pins=dict(pins)

    def __call__(self, *, args, snapshot, timeout):
        from public_catalogue_snapshot_host import CatalogueError

        if not isinstance(timeout,(int,float)) or not 0<timeout<=5:
            raise ValueError("invalid public catalogue deadline")
        if not isinstance(snapshot,bytes) or not 0<len(snapshot)<=2*1024*1024:
            raise ValueError("invalid bounded catalogue snapshot")
        action=json.dumps(args,ensure_ascii=False,separators=(",",":"),allow_nan=False).encode()
        if len(action)>8192:
            raise ValueError("catalogue arguments exceed host limit")
        encoded=action+b"\n"+snapshot
        env={key:os.environ[key] for key in ("PATH","LANG","LC_ALL","TMPDIR") if key in os.environ}
        env["PYTHONIOENCODING"]="utf-8"
        with TemporaryDirectory(prefix="r4-public-catalogue-",dir=self.scratch) as temporary:
            command=[sys.executable,"-I",str(Path(__file__).resolve()),str(self.source),str(self.kit),
                     temporary,json.dumps(self.pins)]
            worker=subprocess.Popen(command,cwd=temporary,env=env,stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,start_new_session=True)
            try:
                raw,_=worker.communicate(encoded,timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(worker.pid,signal.SIGKILL)
                except ProcessLookupError:
                    pass
                worker.communicate()
                raise ValueError("public catalogueer host deadline exceeded") from None
        if worker.returncode!=0 or len(raw)>32768 or not raw:
            raise ValueError("public catalogueer sandbox unavailable")
        return json.loads(raw)


def main():
    source,kit,root=(Path(x).resolve(strict=True) for x in sys.argv[1:4])
    pins=json.loads(sys.argv[4])
    sys.path[:0]=[str(Path(__file__).resolve().parent),str(kit)]
    import agent_kit as official

    class NoWallet:
        def grant(self,name,permission,timeout):
            if any(permission.get(key) for key in ("wallet","identity","network","write","exec","handles")):
                raise ValueError("unexpected catalogue capability")
            return None

    instruction_from(source,pins,official)
    action=sys.stdin.buffer.readline(8193)
    snapshot=sys.stdin.buffer.read(2*1024*1024+1)
    if not action.endswith(b"\n") or not 0<len(snapshot)<=2*1024*1024:
        return 2
    args=json.loads(action)
    if not isinstance(args,dict) or args.get("op") not in {"context","search","render","fallback","prepare","prepared_fallback"}:
        return 2
    os.umask(0o077)
    inputs=root/"host_inputs"
    inputs.mkdir(mode=0o700)
    fixed=inputs/"customer_offer_context.json"
    fixed.write_bytes(snapshot)
    fixed.chmod(0o400)
    directory=root/"tools"/NAME
    directory.mkdir(mode=0o700,parents=True)
    for name,data in verified_catalogue(source,pins).items():
        path=directory/name
        path.write_bytes(data)
        path.chmod(0o400)
    context={"name":"outseop-r4","market":"https://market.ourolabs.ai","tokens":{},
             "addresses":{},"signer":NoWallet()}
    official.mk.LOG_FILE=None
    with open("/dev/null","w") as sink,redirect_stdout(sink),redirect_stderr(sink):
        result=official.Toolbox(root,context).run(NAME,"call",args)
    if not isinstance(result,dict) or set(result)!={"ok","result"} or result["ok"] is not True:
        return 2
    print(json.dumps(result["result"],ensure_ascii=False,separators=(",",":"),allow_nan=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())

