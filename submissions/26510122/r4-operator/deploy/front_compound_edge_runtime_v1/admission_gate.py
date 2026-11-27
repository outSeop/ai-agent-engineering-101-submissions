"""HOST request admission only. Sticky count contains no task ID/customer/product data."""
from contextlib import contextmanager
from pathlib import Path
import fcntl,json,os,stat,tempfile
class AdmissionGate:
 def __init__(self,path,owner=1000):self.path=Path(path);self.owner=owner;self.lock=self.path.with_name('admission.lock')
 def directory(self):
  s=self.path.parent.lstat()
  if self.path.parent.resolve()!=self.path.parent or not stat.S_ISDIR(s.st_mode) or s.st_uid!=self.owner or stat.S_IMODE(s.st_mode)!=0o700:raise ValueError('unsafe admission directory')
 def checked_fd(self,path,flags):
  s=path.lstat()
  if path.resolve()!=path or not stat.S_ISREG(s.st_mode) or s.st_uid!=self.owner or s.st_nlink!=1 or stat.S_IMODE(s.st_mode)!=0o600:raise ValueError('unsafe admission file')
  fd=os.open(path,flags|os.O_NOFOLLOW|os.O_NONBLOCK);actual=os.fstat(fd)
  if (s.st_dev,s.st_ino)!=(actual.st_dev,actual.st_ino):os.close(fd);raise ValueError('admission file changed')
  return fd
 @contextmanager
 def locked(self):
  self.directory();fd=self.checked_fd(self.lock,os.O_RDWR)
  try:fcntl.flock(fd,fcntl.LOCK_EX);yield
  finally:fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)
 def _read(self):
  fd=self.checked_fd(self.path,os.O_RDONLY)
  with os.fdopen(fd,'rb') as f:content=f.read(4097)
  if len(content)>4096:raise ValueError('admission state too large')
  data=json.loads(content)
  if (type(data) is not dict or set(data)!={'version','open','admissions'} or type(data['version']) is not int or data['version']!=1 or type(data['open']) is not bool or type(data['admissions']) is not int or not 0<=data['admissions']<=10**12):raise ValueError('invalid admission state')
  return data
 def _write(self,data):
  fd,name=tempfile.mkstemp(prefix='.admission-',dir=self.path.parent)
  try:
   if os.geteuid()==0:os.fchown(fd,self.owner,self.owner)
   os.fchmod(fd,0o600)
   with os.fdopen(fd,'wb') as f:f.write(json.dumps(data,separators=(',',':')).encode());f.flush();os.fsync(f.fileno())
   os.replace(name,self.path)
   d=os.open(self.path.parent,os.O_RDONLY|os.O_DIRECTORY)
   try:os.fsync(d)
   finally:os.close(d)
  finally:
   if os.path.exists(name):os.unlink(name)
 def initialize_closed(self):
  self.directory()
  fresh_lock=False
  if not self.lock.exists():
   fresh_lock=True
   fd=os.open(self.lock,os.O_CREAT|os.O_EXCL|os.O_RDWR|os.O_NOFOLLOW,0o600)
   if os.geteuid()==0:os.fchown(fd,self.owner,self.owner)
   os.close(fd)
  with self.locked():
   if not self.path.exists() and not fresh_lock:raise ValueError('admission history missing; never reset sticky count')
   state=self._read() if self.path.exists() else {'version':1,'open':False,'admissions':0}
   state['open']=False;self._write(state)
 def read(self):
  with self.locked():return self._read()
 def admit(self):
  with self.locked():
   data=self._read()
   if not data['open']:return False
   data['admissions']+=1;self._write(data);return True
 def open_if_pristine(self):
  with self.locked():
   state=self._read()
   if state['open'] or state['admissions']!=0:raise ValueError('new-task gate not pristine closed')
   state['open']=True;self._write(state)
 def close(self):
  with self.locked():state=self._read();state['open']=False;self._write(state);return state
 def require_pristine_closed(self):
  state=self.read()
  if state['open'] or state['admissions']!=0:raise ValueError('new tasks possible; lossless reverse forbidden')
  return state
