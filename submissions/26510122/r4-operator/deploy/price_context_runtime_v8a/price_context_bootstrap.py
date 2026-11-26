"""External filesystem binding only; execute one of two unchanged pinned entrypoints."""
from pathlib import Path
from hashlib import sha256
import importlib.util,json,os,runpy,stat,sys
OPERATOR=Path('/home/seop/.local/share/ourolabs-r4-checkout/submissions/26510122/r4-operator')
REGISTERED=OPERATOR.parent/'round-4'
POLICY_SOURCE_SHA='6e101702c38d47b3f2c68c860dc0198fd1d7557e311c2753dc4a71fed127118f'
POLICY_RELATIVE=Path('codex-r4/launch-price-policy.json')
TARGETS={
 'catalogue':('public_catalogue_runtime_v8a','public_catalogue_snapshot_producer.py','ffa36c8557ecea6f53a7e9ac7271fa598565fd898f1f5d966444bc34a3f808cc','file_sha256'),
 'card':('native_card_reselection_v1','card_maintenance.py','296ed9c61e69e797fe74b1219d7a267a3e982ce743b1876bcabce8867240c960','files'),
}
def read_checked(path):
 path=Path(path);before=path.lstat()
 if path.resolve(strict=True)!=path or not stat.S_ISREG(before.st_mode) or before.st_uid!=os.getuid() or before.st_nlink!=1 or before.st_mode&0o022:raise ValueError('unprotected bootstrap dependency')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 try:
  held=os.fstat(fd)
  if (held.st_dev,held.st_ino)!=(before.st_dev,before.st_ino):raise ValueError('dependency changed')
  with os.fdopen(fd,'rb',closefd=False) as stream:raw=stream.read()
  after=path.lstat()
  if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):raise ValueError('dependency changed during read')
  return raw
 finally:os.close(fd)
def verify_target(alias):
 if alias not in TARGETS:raise ValueError('target not allowlisted')
 release,entry,expected,field=TARGETS[alias];folder=OPERATOR/'deploy'/release
 raw=read_checked(folder/'MANIFEST.json')
 if sha256(raw).hexdigest()!=expected:raise ValueError('target manifest changed')
 files=json.loads(raw).get(field)
 if type(files) is not dict or entry not in files:raise ValueError('invalid target manifest')
 for leaf,pin in files.items():
  if type(leaf) is not str or type(pin) is not str:raise ValueError('invalid dependency')
  relative=Path(leaf)
  if relative.is_absolute() or '..' in relative.parts or sha256(read_checked(folder/relative)).hexdigest()!=pin:raise ValueError('target dependency changed')
 return folder/entry

def bind_policy():
 source=REGISTERED/'codex-r4/price_policy.py';raw=read_checked(source)
 if sha256(raw).hexdigest()!=POLICY_SOURCE_SHA:raise ValueError('unreviewed price policy source')
 module=sys.modules.get('price_policy')
 if module is None:
  spec=importlib.util.spec_from_file_location('price_policy',source);module=importlib.util.module_from_spec(spec);sys.modules['price_policy']=module
  # Execute exactly the bytes just verified, without an unverified second file read.
  exec(compile(raw,str(source),'exec'),module.__dict__)
 elif Path(getattr(module,'__file__','')).resolve()!=source:raise ValueError('unreviewed preloaded price policy')
 absolute=REGISTERED/POLICY_RELATIVE
 if module.POLICY_PATH not in (POLICY_RELATIVE,absolute):raise ValueError('unexpected price configuration path')
 # Missing config retains the original fail-closed behavior. Never copy or rewrite it.
 if absolute.exists() or absolute.is_symlink():read_checked(absolute)
 module.POLICY_PATH=absolute
 return module

def run(alias,args,*,check=False):
 target=verify_target(alias);module=bind_policy()
 if check:return {'status':'verified_only','target':alias,'policy_source_sha256':POLICY_SOURCE_SHA,'absolute_config_path':str(module.POLICY_PATH),'target_file_sha256':sha256(read_checked(target)).hexdigest(),'target_executed':False}
 # Only the established operator is allowed; original business options otherwise pass through.
 positions=[i for i,value in enumerate(args) if value=='--operator' or value.startswith('--operator=')]
 if len(positions)!=1:raise ValueError('exactly one original operator argument required')
 i=positions[0];value=args[i].split('=',1)[1] if args[i].startswith('--operator=') else args[i+1] if i+1<len(args) else ''
 if Path(value).resolve(strict=True)!=OPERATOR:raise ValueError('unexpected original operator')
 sys.argv=[str(target),*args]
 # Match normal script imports, while retaining the caller's cwd and original __file__.
 sys.path.insert(0,str(target.parent))
 return runpy.run_path(str(target),run_name='__main__')
def main():
 args=sys.argv[1:];check=False
 if args and args[0]=='--check':check=True;args=args[1:]
 if not args:raise SystemExit('expected catalogue or card')
 alias=args.pop(0)
 if args[:1]==['--']:args=args[1:]
 result=run(alias,args,check=check)
 if check:print(json.dumps(result))
if __name__=='__main__':main()
