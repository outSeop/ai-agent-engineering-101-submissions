"""Build immutable HOST releases from one maintained source tree and pinned assets.

This is packaging only: no imports of agent code, wallet/DB access, network, service
or firewall actions. Existing releases are verified and reused, never overwritten.
"""
from pathlib import Path
from hashlib import sha256
import argparse
import json
import os
import stat
import tempfile

MAX_FILE = 4 * 1024 * 1024

def encode(value):
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode()

def digest(raw):
    return sha256(raw).hexdigest()

def protected(path):
    path=Path(path)
    before=path.lstat()
    if (path.resolve(strict=True)!=path or not stat.S_ISREG(before.st_mode)
            or before.st_uid!=os.getuid() or before.st_nlink!=1 or before.st_mode&0o022
            or not 0<before.st_size<=MAX_FILE):
        raise ValueError("unprotected release source")
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        held=os.fstat(fd)
        if (held.st_dev,held.st_ino)!=(before.st_dev,before.st_ino):
            raise ValueError("release source changed")
        with os.fdopen(fd,"rb",closefd=False) as stream:raw=stream.read(MAX_FILE+1)
        after=path.lstat()
        if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):
            raise ValueError("release source changed during read")
        return raw
    finally:
        os.close(fd)

def relative(value):
    if not isinstance(value,str) or not value or "\\" in value:
        raise ValueError("invalid relative source")
    p=Path(value)
    if p.is_absolute() or ".." in p.parts or "." in p.parts:
        raise ValueError("release path escapes component")
    return p

def pinned_source(operator,record):
    if not isinstance(record,dict) or set(record)!={"source","sha256"}:
        raise ValueError("invalid pinned source")
    rel=relative(record["source"])
    if rel.parts[0] not in {"src","deploy"}:
        raise ValueError("source must be maintained code or pinned deployment asset")
    raw=protected(operator/rel)
    if digest(raw)!=record["sha256"]:
        raise ValueError("release source pin mismatch")
    return raw

def verify_component(folder,pin,field):
    raw=protected(folder/"MANIFEST.json")
    if digest(raw)!=pin:
        raise ValueError("release manifest mismatch")
    meta=json.loads(raw)
    files=meta.get(field)
    if not isinstance(files,dict) or not files:
        raise ValueError("empty release manifest")
    for name,expected in files.items():
        if digest(protected(folder/relative(name)))!=expected:
            raise ValueError("release artifact drift")
    return meta

def build(operator,descriptor,expected_spec_sha):
    operator=Path(operator).resolve(strict=True)
    descriptor=Path(descriptor)
    if not descriptor.is_relative_to(operator/"deploy/release_specs"):
        raise ValueError("descriptor outside release_specs")
    specraw=protected(descriptor)
    if digest(specraw)!=expected_spec_sha:
        raise ValueError("release specification changed")
    spec=json.loads(specraw)
    if set(spec)!={"schema","builder_sha256","runtime_base","runtime_overrides","native_semantic","front_sources","front_binding"} or spec["schema"]!="r4-host-release.v1":
        raise ValueError("invalid release specification")
    builder_raw=protected(Path(__file__).resolve())
    if digest(builder_raw)!=spec["builder_sha256"]:
        raise ValueError("release builder changed")
    base=spec["runtime_base"]
    if set(base)!={"source","manifest_sha256"}:
        raise ValueError("invalid runtime base")
    base_rel=relative(base["source"])
    if base_rel.parts[0]!="deploy":raise ValueError("runtime base outside deploy")
    base_folder=operator/base_rel
    base_meta=verify_component(base_folder,base["manifest_sha256"],"file_sha256")
    runtime_files={name:protected(base_folder/relative(name)) for name in base_meta["file_sha256"]}
    if not isinstance(spec["runtime_overrides"],dict):raise ValueError("invalid overrides")
    for name,record in spec["runtime_overrides"].items():
        name=str(relative(name))
        if name not in runtime_files or not name.endswith(".py"):
            raise ValueError("override is not an existing HOST module")
        # Business catalogue and native tool sources are only copied as exact assets.
        if "/" in name or name in {"logic.py","test.py"}:
            raise ValueError("native business source override forbidden")
        runtime_files[name]=pinned_source(operator,record)
    native=spec["native_semantic"]
    if not isinstance(native,dict) or set(native)!={"tool","version","files"} or native["tool"]!="semantic_candidates" or type(native["version"]) is not int:
        raise ValueError("invalid semantic asset")
    if set(native["files"])!={"logic.py","test.py","permission.yml","forge.json"}:
        raise ValueError("semantic requires all original forge files")
    assets={name:pinned_source(operator,record) for name,record in native["files"].items()}
    forge=json.loads(assets["forge.json"])
    if ((forge.get("tool"),forge.get("version"))!=(native["tool"],native["version"])
            or forge.get("sha256")!={n:digest(assets[n]) for n in assets if n!="forge.json"}):
        raise ValueError("semantic forge record mismatch")
    runtime_files.update({"semantic/"+name:raw for name,raw in assets.items()})
    if not isinstance(spec["front_sources"],dict) or not spec["front_sources"]:
        raise ValueError("empty front source set")
    front_files={str(relative(name)):pinned_source(operator,record) for name,record in spec["front_sources"].items()}
    if any("/" in name for name in front_files):raise ValueError("front sources must be flat")
    required={"config.py","admission_gate.py","front_edge_app.py","run_front_edge.py","transition_guard.py"}
    if not required<=set(front_files):raise ValueError("incomplete common front")
    if "RUNTIME-BINDING.json" in front_files:raise ValueError("binding is produced from specification")
    release_id=digest(specraw)
    root=operator/"runtime/releases"
    root.mkdir(mode=0o700,parents=True,exist_ok=True)
    if root.resolve()!=root or root.stat().st_uid!=os.getuid() or root.stat().st_mode&0o022:
        raise ValueError("unsafe release store")
    target=root/release_id
    runtime_meta={**base_meta,"bundle":"r4-host-runtime-"+release_id,"release_spec_sha256":release_id,
                  "parent_manifest_sha256":base["manifest_sha256"],"semantic_version":native["version"],
                  "semantic_original_forge_sha256":digest(assets["forge.json"]),
                  "file_sha256":{name:digest(raw) for name,raw in sorted(runtime_files.items())}}
    runtime_raw=encode(runtime_meta)
    binding=dict(spec["front_binding"])
    if "runtime_path" in binding or "runtime_manifest_sha256" in binding:
        raise ValueError("runtime location is generated, not caller-supplied")
    binding.update(runtime_path=str(target/"runtime"),runtime_manifest_sha256=digest(runtime_raw))
    front_files["RUNTIME-BINDING.json"]=encode(binding)
    front_meta={"bundle":"r4-host-front-"+release_id,"sources_only":False,"release_spec_sha256":release_id,
                "files":{name:digest(raw) for name,raw in sorted(front_files.items())}}
    front_raw=encode(front_meta)
    receipt={"schema":"r4-host-build.v1","release_id":release_id,"descriptor_sha256":release_id,
             "builder_sha256":digest(builder_raw),"runtime_path":str(target/"runtime"),
             "runtime_manifest_sha256":digest(runtime_raw),"front_path":str(target/"front"),
             "front_manifest_sha256":digest(front_raw),"native_semantic_version":native["version"],
             "native_asset_bytes_preserved":True,"business_sources_modified_by_builder":False}
    if target.exists():
        if target.resolve()!=target:raise ValueError("release target is a symlink")
        verify_component(target/"runtime",receipt["runtime_manifest_sha256"],"file_sha256")
        verify_component(target/"front",receipt["front_manifest_sha256"],"files")
        if protected(target/"BUILD.json")!=encode(receipt):raise ValueError("existing build receipt changed")
        return {**receipt,"reused":True}
    temporary=Path(tempfile.mkdtemp(prefix=".building-"+release_id[:10]+"-",dir=root))
    for component,files,manifest in [("runtime",runtime_files,runtime_raw),("front",front_files,front_raw)]:
        folder=temporary/component
        folder.mkdir(mode=0o700)
        for name,raw in {**files,"MANIFEST.json":manifest}.items():
            path=folder/relative(name);path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            with path.open("xb") as stream:stream.write(raw)
            path.chmod(0o400)
    (temporary/"BUILD.json").write_bytes(encode(receipt));(temporary/"BUILD.json").chmod(0o400)
    # No deletion or replacement of an existing release is permitted.
    if target.exists():raise ValueError("release created concurrently; inspect existing build")
    os.rename(temporary,target)
    verify_component(target/"runtime",receipt["runtime_manifest_sha256"],"file_sha256")
    verify_component(target/"front",receipt["front_manifest_sha256"],"files")
    return {**receipt,"reused":False}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--operator',type=Path,required=True)
    parser.add_argument('--descriptor',type=Path,required=True)
    parser.add_argument('--expected-spec-sha',required=True)
    args=parser.parse_args()
    print(json.dumps(build(args.operator,args.descriptor,args.expected_spec_sha)))

if __name__=='__main__':main()
