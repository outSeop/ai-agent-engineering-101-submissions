"""Root operations binding: read seop's user manager as seop, then retain the frozen exact-rule guard."""
from pathlib import Path
from hashlib import sha256
import importlib.util,json,os,pwd,subprocess,sys
OP=Path('/home/seop/.local/share/ourolabs-r4-checkout/submissions/26510122/r4-operator')
FRONT=OP/'deploy/front_edge_runtime_v3'
FRONT_PIN='c2232e5e8a3ef7ced3e4475a009a519232393c309633c219d05ff3859e9385f2'
def main():
 args=sys.argv[1:]
 if args[:1]!=['--binding-manifest-sha'] or len(args)<3:raise ValueError('reviewed binding manifest required')
 pin=args[1];args=args[2:];folder=Path(__file__).resolve().parent;raw=(folder/'MANIFEST.json').read_bytes()
 if sha256(raw).hexdigest()!=pin:raise ValueError('binding manifest drift')
 for n,d in json.loads(raw)['files'].items():
  path=folder/n
  if path.resolve()!=path or sha256(path.read_bytes()).hexdigest()!=d:raise ValueError('binding source drift')
 if os.geteuid()!=0 or pwd.getpwnam('seop').pw_uid!=1000:raise ValueError('explicit root/seop ownership required')
 manifest=(FRONT/'MANIFEST.json').read_bytes()
 if sha256(manifest).hexdigest()!=FRONT_PIN:raise ValueError('front guard package drift')
 source=FRONT/'route_guard.py';body=source.read_bytes()
 if sha256(body).hexdigest()!=json.loads(manifest)['files']['route_guard.py']:raise ValueError('route guard drift')
 spec=importlib.util.spec_from_file_location('verified_route_guard',source);mod=importlib.util.module_from_spec(spec);exec(compile(body,str(source),'exec'),mod.__dict__)
 def owner_service_pid():
  result=subprocess.run(['/usr/sbin/runuser','-u','seop','--','env','XDG_RUNTIME_DIR=/run/user/1000','DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus','systemctl','--user','show','ourolabs-market-r4.service','-p','MainPID','--value'],capture_output=True,text=True)
  if result.returncode or not result.stdout.strip().isdigit():raise ValueError('actual owner service PID unavailable')
  return int(result.stdout.strip())
 mod.service_pid=owner_service_pid
 sys.argv=[str(source),*args];mod.main()
if __name__=='__main__':main()
