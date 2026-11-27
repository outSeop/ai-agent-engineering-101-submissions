"""External HOST QA only: source checks and tamper of an owned temporary copy.
No target execution, API, Model, POST, credentials, production SQL or service calls.
This preserves the executed stdin procedure as a script with a fresh-output argument.
"""
from pathlib import Path
import argparse,hashlib,importlib.util,json,re,shutil,subprocess

PIN="c55ada0a0df0e56963f0fdea40472cf4320e6ecef5d4b620bbb47da637e99957"
OP=Path("/home/seop/.local/share/ourolabs-r4-checkout/submissions/26510122/r4-operator")

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument("--output",type=Path,required=True,help="Fresh directory directly under OP/runtime/cache-repair-20261128-qa")
 args=parser.parse_args();out=args.output.resolve();parent=(OP/"runtime/cache-repair-20261128-qa").resolve(strict=True)
 if out.parent!=parent or out.exists():raise ValueError("expected fresh owned QA output directory")
 out.mkdir(mode=0o700);bundle=OP/"deploy/price_context_runtime_v8b"
 assert digest(bundle/"MANIFEST.json")==PIN
 sources={prefix+"/"+name:folder/name for prefix,folder in [("archived5",bundle/"legacy_root/tools/forum_marketing"),("active9",OP.parent/"round-4/tools/forum_marketing")] for name in ["logic.py","test.py","permission.yml","forge.json"]}
 before={name:digest(path) for name,path in sources.items()};checks={}
 for alias in ["catalogue","card"]:
  result=subprocess.run(["unshare","-Urn",str(OP/".venv/bin/python"),"-B",str(bundle/"price_context_bootstrap.py"),"--package-manifest-sha",PIN,"--check",alias],capture_output=True,text=True,timeout=30)
  assert result.returncode==0,"source-only check failed; no raw error exported"
  data=json.loads(result.stdout);assert data["status"]=="verified_only" and data["target_executed"] is False
  checks[alias]={key:data[key] for key in ["status","target_executed","binding","reader_source_unchanged","helper_file_sha256"]}
  checks[alias]["absolute_policy_binding_preserved"]=Path(data["absolute_config_path"])==OP.parent/"round-4/codex-r4/launch-price-policy.json"
  assert checks[alias]["absolute_policy_binding_preserved"]
 copy=out/"tamper-package-copy";shutil.copytree(bundle,copy)
 spec=importlib.util.spec_from_file_location("_cache_binding_tamper_qa",copy/"price_context_bootstrap.py")
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);module.verify_package(PIN)
 source=copy/"legacy_root/tools/forum_marketing/logic.py";source.chmod(0o600);source.write_bytes(source.read_bytes()+b"\n# independent synthetic tamper\n")
 try:module.verify_package(PIN)
 except ValueError:source_rejected=True
 else:source_rejected=False
 assert source_rejected
 manifest=copy/"MANIFEST.json";manifest.chmod(0o600);manifest.write_bytes(manifest.read_bytes()+b"\n")
 try:module.verify_package(PIN)
 except ValueError:manifest_rejected=True
 else:manifest_rejected=False
 assert manifest_rejected and all(digest(path)==before[name] for name,path in sources.items())
 safe={"bundle_manifest_sha256":PIN,"checks":checks,"temporary_legacy_logic_tamper_rejected":source_rejected,"temporary_manifest_tamper_rejected":manifest_rejected,"archived5_and_active9_source4_unchanged":True,"source4_sha256":before,"actual_producer_API_Model_POST_pay_service_DB_calls":0,"actual_timer_recovery_observed":False}
 (out/"safe-result.json").write_text(json.dumps(safe,indent=2))
 print(json.dumps({"source_only_passed":True,"tamper_cases":2,"target_executed":False,"output":str(out/"safe-result.json")}))
if __name__=="__main__":main()
