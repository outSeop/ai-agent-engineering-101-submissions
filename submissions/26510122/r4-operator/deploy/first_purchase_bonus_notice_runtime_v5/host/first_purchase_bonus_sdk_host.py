"""Bind a reviewed, generated bonus tool to the original keyless SDK lane."""
from hashlib import sha256
import json
import os
from pathlib import Path
import stat

NAME="first_purchase_bonus"
REQUIRED={"logic.py","test.py","permission.yml","forge.json"}
WRITE_SCOPE=["state/r4-benefits"]
NO_CAPS=("network","wallet","identity","exec","handles")


class NoWallet:
    def grant(self,name,permission,timeout):
        if (name!=NAME or any(permission.get(key) for key in NO_CAPS)
            or permission.get("write")!=WRITE_SCOPE or permission.get("pay_limit",0)!=0):
            raise ValueError("unexpected bonus runner capability")
        return None


def checked_file(path,maximum=1024*1024):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,"rb") as stream:
        info=os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid()
            or info.st_mode&0o022 or info.st_nlink!=1 or info.st_size>maximum):
            raise ValueError("unsafe bonus source artifact")
        raw=stream.read(maximum+1)
    if len(raw)>maximum:
        raise ValueError("bonus source artifact too large")
    return raw


def verified_source(root,pins,official,version):
    root=Path(root)
    folder=root/"tools"/NAME
    if folder.resolve(strict=True)!=folder or set(pins)!=REQUIRED:
        raise ValueError("unexpected verified bonus source path")
    info=folder.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o022:
        raise ValueError("unprotected bonus source directory")
    files={name:checked_file(folder/name) for name in REQUIRED}
    if any(sha256(raw).hexdigest()!=pins[name] for name,raw in files.items()):
        raise ValueError("unreviewed bonus source")
    manifest=json.loads(files["forge.json"])
    if (manifest.get("tool")!=NAME or manifest.get("version")!=version
        or manifest.get("sha256")!={key:pins[key] for key in REQUIRED-{"forge.json"}}):
        raise ValueError("bonus forge manifest mismatch")
    permission=official.forge_runner.parse_permission(files["permission.yml"].decode())["permission"]
    if (any(permission.get(key) for key in NO_CAPS)
        or permission.get("write")!=WRITE_SCOPE or permission.get("pay_limit",0)!=0):
        raise ValueError("bonus source requests unexpected privileges")
    return folder


class ToolInvocation:
    def __init__(self,official,agent_root,pins,version,result_schema):
        self.official=official
        self.root=agent_root
        self.pins=dict(pins)
        self.version=version
        self.result_schema=result_schema
        self.context={"name":"outseop-r4","market":"https://market.ourolabs.ai",
                      "tokens":{},"addresses":{},"signer":NoWallet()}
        verified_source(self.root,self.pins,self.official,self.version)

    def __call__(self,sale_id):
        if not isinstance(sale_id,str) or not 1<=len(sale_id)<=128:
            raise ValueError("unexpected internal settlement sale identifier")
        verified_source(self.root,self.pins,self.official,self.version)
        response=self.official.Toolbox(self.root,self.context).run(NAME,"call",{"sale_id":sale_id})
        if not isinstance(response,dict) or set(response)!={"ok","result"} or response["ok"] is not True:
            raise ValueError("bonus tool execution unavailable")
        return self.result_schema(response["result"])

