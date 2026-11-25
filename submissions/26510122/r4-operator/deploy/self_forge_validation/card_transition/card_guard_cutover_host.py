"""Host-only atomic fence for the old card publisher. Default is dry inspection."""
import argparse
from contextlib import contextmanager
import ctypes
import fcntl
from hashlib import sha256
import json
import os
import signal
from pathlib import Path
import stat
import sys
import tempfile
import time


NAME = "publish_shop_info"
OLD = {
    "permission.yml":"8f308115eb87a87fc16991e423b947feda068603827c10b8d2da4bb87c76caf9",
    "logic.py":"5cc1db49df822e9a6dac5883f5db589e80bde4c2572661d8f1d660f1751650df",
    "test.py":"5cf45e7ed728629df1e052e5360614c8fcadf96f78a1edfb1bf0cec2ffd3028d",
}
NEW = {
    "permission.yml":"599f987876a750c3349e57b754e2b5c2085a1a9b21e9f290f58ec5ab10e5821b",
    "logic.py":"cb3c5a6e5c6ca36fb329e4b2279c2b718a304386665707ecaf9a7e21eb887dc2",
    "test.py":"bde98d730b945e0adc85c7802f36eb3155521ac79ff7c63f2d2b7234c536e60c",
}
OLD_MANIFEST = "e2a78f3c9e4440931a196e46550fabe6d6891448d7f9381d2ee5fa1258894017"
NEW_MANIFEST = "f31f1604abc3157116ecbd284688d04662694be694c787ab8b560918a5236004"
MANAGED_OLD = "1eda55d5142230f2ba6860f33e424b288531fde32f9f915170dd527831cc19a6"
MANAGED_NEW = "5ebb64a2ed1a0c909bac94aaee52c9f41974fd4f757b0068667a7a770b174493"


def sha(raw):
    return sha256(raw).hexdigest()


def verify_path(path, isdir=False):
    info=path.lstat()
    kind=stat.S_ISDIR if isdir else stat.S_ISREG
    if (not kind(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode & 0o022
        or (not isdir and info.st_nlink!=1) or path.resolve()!=path):
        raise ValueError("path failed ownership/type checks")
    return info


def read(path):
    verify_path(path)
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW),"rb") as source:
        return source.read()


def bundle(path,pins):
    verify_path(path,True)
    data={name:read(path/name) for name in (*pins,"forge.json")}
    manifest=json.loads(data["forge.json"])
    if sha(data["forge.json"]) != (NEW_MANIFEST if pins==NEW else OLD_MANIFEST):
        raise ValueError("publisher manifest bytes changed")
    if ((manifest.get("tool"),manifest.get("version"),manifest.get("sha256"))!=(NAME,1,pins)
        or any(sha(data[name])!=digest for name,digest in pins.items())):
        raise ValueError("publisher bundle hash mismatch")
    return data


def sync(directory):
    fd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def exchange(left,right):
    if left.parent!=right.parent or left==right:
        raise ValueError("exchange requires siblings")
    if verify_path(left,True).st_dev!=verify_path(right,True).st_dev:
        raise ValueError("exchange requires same filesystem")
    directory=left.parent
    verify_path(directory,True)
    fn=ctypes.CDLL(None,use_errno=True).renameat2
    fn.argtypes=(ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint)
    fn.restype=ctypes.c_int
    fd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        if fn(fd,os.fsencode(left.name),fd,os.fsencode(right.name),2)!=0:
            raise OSError(ctypes.get_errno(),"RENAME_EXCHANGE failed")
    finally:
        os.close(fd)


def write_once(path,data):
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def create_lock(pub):
    pub.mkdir(mode=0o700,exist_ok=True)
    verify_path(pub,True)
    path=pub/"lock"
    fd=os.open(path,os.O_CREAT|os.O_NOFOLLOW|os.O_RDWR,0o600)
    os.close(fd)
    verify_path(path)
    return path


@contextmanager
def exclusive(path):
    verify_path(path)
    with os.fdopen(os.open(path,os.O_RDWR|os.O_NOFOLLOW),"rb+") as stream:
        fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield


def no_native_progress(production):
    pub=production/"card_publication"
    if pub.exists():
        verify_path(pub,True)
        if any(path.name!="lock" for path in pub.iterdir()):
            return False
    inputs=production/"host_inputs"
    if inputs.exists():
        verify_path(inputs,True)
        if any(path.name in {"card_publication_authority.json","card_publication_handoff.json"} for path in inputs.iterdir()):
            return False
    return True


def running_tool(path):
    own=os.getuid()
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if proc.stat().st_uid!=own:
                continue
            args=(proc/"cmdline").read_bytes().split(b"\0")
            if (any(a.endswith(b"/forge_runner.py") for a in args)
                and os.fsencode(path) in args and b"call" in args):
                return True
        except OSError:
            continue
    return False


def approved_guard_probe(production, target, kit_path):
    sys.path.insert(0,str(kit_path))
    import agent_kit

    class NoWallet:
        def grant(self,name,perm,timeout):
            if any(perm.get(k) for k in ("wallet","identity","network","exec","handles")):
                raise ValueError("guard asked for capability")
            if perm.get("write")!=["card_handoff_selftest"]:
                raise ValueError("guard asked for unexpected file write")
            return None

    ctx={"name":"outseop-r4","market":"https://market.ourolabs.ai","tokens":{},
         "addresses":{},"signer":NoWallet()}
    toolbox=agent_kit.Toolbox(production,ctx)
    result=toolbox.run(NAME,"call",{},d=target)
    expected={"ok":True,"result":{"status":"waiting","reason":"required_publication_file_missing"}}
    if result!=expected:
        raise ValueError("guard did not remain read-only and waiting without handoff")


def managed_replace(path, raw):
    verify_path(path)
    fd,name=tempfile.mkstemp(prefix=".managed-card-guard-",dir=path.parent)
    temp=Path(name)
    try:
        with os.fdopen(fd,"wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp,stat.S_IMODE(path.stat().st_mode))
        os.replace(temp,path)
        sync(path.parent)
    finally:
        temp.unlink(missing_ok=True)


def fence(production, session, source, kit_path, managed=None, sleep=time.sleep, probe=approved_guard_probe):
    tools=production/"tools"
    target=tools/NAME
    lock=create_lock(production/"card_publication")
    if not no_native_progress(production):
        raise ValueError("native publication already started")
    candidate=Path(tempfile.mkdtemp(prefix=".card-publisher-fence-",dir=tools))
    for name,data in source.items():
        write_once(candidate/name,data)
    sync(candidate)
    old=bundle(target,OLD)
    archived=session/"legacy-publisher"
    archived.mkdir(mode=0o700)
    for name,data in old.items():
        write_once(archived/name,data)
    sync(archived)
    switched=False
    managed_changed=False
    try:
        with exclusive(lock):
            if not no_native_progress(production) or bundle(target,OLD)!=old or bundle(candidate,NEW)!=source:
                raise ValueError("pre-swap baseline changed")
            previous=signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGINT,signal.SIGTERM})
            try:
                exchange(target,candidate)
                switched=True
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK,previous)
            sync(tools)
        sleep(10)  # Pinned legacy permission timeout is eight seconds.
        if running_tool(target):
            raise ValueError("publisher runner still in flight")
        card=production/"card.json"
        settled=read(card)
        probe(production,target,kit_path)
        if read(card)!=settled or not no_native_progress(production) or bundle(target,NEW)!=source:
            raise ValueError("guard probe changed public or native state")
        if managed:
            path,old_source,new_source=managed
            if read(path)!=old_source:
                raise ValueError("managed runtime changed before replacement")
            write_once(session/"managed-runtime-before.py",old_source)
            managed_changed=True
            managed_replace(path,new_source)
        return {"status":"fenced","card_sha256":sha(settled),"native_apply_started":False,
                "retained_swapped_bundle":candidate.name}
    except BaseException:
        if switched:
            with exclusive(lock):
                if (not no_native_progress(production) or bundle(candidate,OLD)!=old
                    or bundle(target,NEW)!=source):
                    raise RuntimeError("native progress or publisher mismatch; automatic restore refused")
                exchange(target,candidate)
                sync(tools)
                if managed_changed:
                    path,old_source,new_source=managed
                    current=read(path)
                    if current==new_source:
                        managed_replace(path,old_source)
                    elif current!=old_source:
                        raise RuntimeError("managed runtime changed; automatic restore refused")
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operator",required=True,type=Path)
    parser.add_argument("--session",required=True,type=Path)
    parser.add_argument("--managed-candidate",type=Path)
    parser.add_argument("--allow-fence",action="store_true")
    options=parser.parse_args()
    op=options.operator.resolve(strict=True)
    production=op.parent/"round-4"
    runtime=op/"runtime"
    staging=options.session.absolute()
    for folder in (op,production,production/"tools",runtime):
        verify_path(folder,True)
    if staging.parent!=runtime or not staging.name.startswith("card-cutover-") or staging.exists():
        parser.error("expected fresh private cutover session")
    target=production/"tools"/NAME
    source=bundle(runtime/"class-rebuild-reach-20261125/tools"/NAME,NEW)
    old=bundle(target,OLD)
    managed=None
    if options.managed_candidate:
        current=production/"codex-r4/managed_runtime.py"
        old_source=read(current)
        new_source=read(options.managed_candidate.absolute())
        if (sha(old_source),sha(new_source))!=(MANAGED_OLD,MANAGED_NEW):
            raise ValueError("expected exact managed runtime permission patch")
        managed=(current,old_source,new_source)
    if not no_native_progress(production):
        raise ValueError("native publication already started")
    if not options.allow_fence:
        print(json.dumps({"status":"dry","legacy_sha256":sha(old["logic.py"]),
                          "guard_sha256":sha(source["logic.py"]),"managed_patch":bool(managed)}))
        return
    os.umask(0o077)
    staging.mkdir(mode=0o700)
    record={"record_type":"host-derived guard reuse","original_external_legacy":OLD,"genuine_guard":NEW,
            "origin":"class-rebuild-reach-20261125","new_forge_created":False}
    write_once(staging/"cutover-origin.json",json.dumps(record).encode())
    def interrupted(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM,interrupted)
    result=fence(production,staging,source,op/"kit",managed)
    write_once(staging/"summary.json",json.dumps(result).encode())
    print(json.dumps(result))


if __name__=="__main__":
    main()

