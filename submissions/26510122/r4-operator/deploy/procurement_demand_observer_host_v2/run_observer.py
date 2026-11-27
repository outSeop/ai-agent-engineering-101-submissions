"""Pin-first bootstrap for the standalone no-Model/no-wallet host observer."""
from pathlib import Path
import argparse,hashlib,json,os,stat,sys,importlib.util

def main():
 p=argparse.ArgumentParser();p.add_argument('--package-manifest-sha',required=True);p.add_argument('--recorder-forge-sha',required=True);p.add_argument('--run',action='store_true');a=p.parse_args();folder=Path(__file__).resolve().parent;raw=(folder/'MANIFEST.json').read_bytes()
 if hashlib.sha256(raw).hexdigest()!=a.package_manifest_sha:raise ValueError('unreviewed observer package')
 for n,h in json.loads(raw)['files'].items():
  rel=Path(n);source=folder/rel;st=source.lstat()
  if rel.is_absolute() or '..' in rel.parts or source.resolve()!=source or not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or st.st_mode&0o022 or hashlib.sha256(source.read_bytes()).hexdigest()!=h:raise ValueError('observer source drift')
 source=folder/'demand_observer_host.py';spec=importlib.util.spec_from_file_location('reviewed_demand_observer',source);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 return m.main(['--recorder-forge-sha',a.recorder_forge_sha]+(['--run'] if a.run else []))
if __name__=='__main__':
 try:main()
 except Exception as exc:
  print(json.dumps({'status':'observer_bootstrap_failed','error_type':type(exc).__name__,'args_or_body_exported':False}));sys.exit(1)
