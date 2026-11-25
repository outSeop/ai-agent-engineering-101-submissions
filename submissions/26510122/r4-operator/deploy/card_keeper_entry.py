"""Application card-cache maintenance entry; no model or financial decisions."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

MANIFEST_SHA = "2634c1b9fed45b1126941354b0a433babcce3a5916d6968bee2b5bd502839e2a"

def protected(path):
    info=path.lstat()
    if path.resolve()!=path or not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1 or info.st_mode&0o022:
        raise RuntimeError("unprotected keeper artifact")
    return path.read_bytes()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operator",required=True,type=Path)
    parser.add_argument("--allow-refresh",action="store_true")
    args=parser.parse_args()
    operator=args.operator.resolve(strict=True)
    bundle=operator/"deploy/native_card_keeper_v1"
    raw=protected(bundle/"MANIFEST.json")
    if hashlib.sha256(raw).hexdigest()!=MANIFEST_SHA:
        raise RuntimeError("frozen keeper manifest changed")
    for name,digest in json.loads(raw)["file_sha256"].items():
        if Path(name).name!=name or hashlib.sha256(protected(bundle/name)).hexdigest()!=digest:
            raise RuntimeError("frozen keeper artifact changed")
    sys.path.insert(0,str(bundle))
    import card_keeper_same_choice_host_candidate as keeper
    result=keeper.run_once(operator=operator,allow_refresh=args.allow_refresh)
    print(json.dumps(result),flush=True)
    if args.allow_refresh:
        state=operator/"runtime/card-keeper-native"
        if state.is_dir():
            keeper.files.atomic_host(state/"latest.json",keeper.files.encode(result))
    return 0 if result.get("status") in ("dry","applied","already_applied","busy") else 1

if __name__=="__main__":
    raise SystemExit(main())
