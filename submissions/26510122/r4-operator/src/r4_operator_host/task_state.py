"""Private HOST task persistence and ownership index. No transport, wallet, Model or business execution."""
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import asyncio,json,math,os,sqlite3,stat,time
from a2a.server.tasks import TaskStore,InMemoryTaskStore
from a2a.server.owner_resolver import resolve_user_scope
from a2a.types import Task
APP_ID=0x52345453
MAX_TASK_BYTES=8*1024*1024
PROVENANCE={'own_list_tasks','new_engine','ascending_exclusion','known_owner_response'}
class RouteConflict(RuntimeError):pass
class UnsafeTaskState(RuntimeError):pass

def _task_id(value):
 if type(value) is not str or not 1<=len(value)<=256 or '\x00' in value:raise ValueError('invalid task identifier')
 return value

def _scope(value):
 if type(value) is not str or len(value)>4096:raise ValueError('invalid SDK owner scope')
 return sha256(b'r4-host-task-scope-v1\0'+value.encode()).hexdigest()

def _payload(value):
 if not isinstance(value,(bytes,bytearray)) or not 0<len(value)<=MAX_TASK_BYTES:raise ValueError('invalid bounded task protobuf')
 task=Task.FromString(bytes(value));_task_id(task.id)
 return task,bytes(value)

@dataclass(frozen=True)
class LegacySnapshot:
 task_id:str
 owner_port:int
 task_proto:bytes
 observed_at:float
 provenance:str
 @property
 def task(self):return Task.FromString(self.task_proto)

class TaskStateDB:
 """One separate0600 SQLite for task blobs, routes and read-only legacy snapshots."""
 def __init__(self,path,*,allowed_legacy_ports=tuple(range(18805,18811))):
  self.path=Path(path);self.allowed_legacy_ports=tuple(allowed_legacy_ports)
  if not self.allowed_legacy_ports or any(type(p) is not int or not 1<=p<=65535 for p in self.allowed_legacy_ports) or len(set(self.allowed_legacy_ports))!=len(self.allowed_legacy_ports):raise ValueError('fixed distinct legacy ports required')
  if self.path.name in ('benefits.sqlite3','market.sqlite3') or 'r4-benefits' in self.path.parts or self.path.suffix not in ('.sqlite3','.db'):raise UnsafeTaskState('financial DB reuse forbidden')
  self._directory()
  if not self.path.exists():
   fd=os.open(self.path,os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);os.close(fd)
  self._file()
  with sqlite3.connect(self.path.as_uri()+'?mode=rw',uri=True,timeout=5) as db:
   app=db.execute('PRAGMA application_id').fetchone()[0];tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
   if app not in (0,APP_ID) or (app==0 and tables):raise UnsafeTaskState('existing unrelated DB refused without migration')
   if app==APP_ID and (tables!={'tasks','routes','legacy_snapshots','host_control','public_facts'} or db.execute('PRAGMA user_version').fetchone()[0]!=1):raise UnsafeTaskState('unsupported private task-state schema')
   db.execute('PRAGMA synchronous=FULL')
   if app==0:
    db.executescript(f"""BEGIN IMMEDIATE;
    CREATE TABLE tasks(scope_hash TEXT NOT NULL,task_id TEXT NOT NULL,payload BLOB NOT NULL,updated_ns INTEGER NOT NULL,PRIMARY KEY(scope_hash,task_id));
    CREATE TABLE routes(scope_hash TEXT NOT NULL,task_id TEXT NOT NULL,destination TEXT NOT NULL,provenance TEXT NOT NULL,topology TEXT NOT NULL,observed_ns INTEGER NOT NULL,PRIMARY KEY(scope_hash,task_id));
    CREATE TABLE legacy_snapshots(scope_hash TEXT NOT NULL,task_id TEXT NOT NULL,owner_port INTEGER NOT NULL,payload BLOB NOT NULL,observed_ns INTEGER NOT NULL,provenance TEXT NOT NULL,PRIMARY KEY(scope_hash,task_id));
    CREATE TABLE host_control(name TEXT PRIMARY KEY,value TEXT NOT NULL);
    CREATE TABLE public_facts(key BLOB PRIMARY KEY,facts_json TEXT NOT NULL,created_at REAL NOT NULL,expires_at REAL NOT NULL);
    INSERT INTO host_control VALUES('maintenance','1');
    PRAGMA application_id={APP_ID}; PRAGMA user_version=1; COMMIT;""")
 def _directory(self):
  parent=self.path.parent;s=parent.lstat()
  if not self.path.is_absolute() or parent.resolve(strict=True)!=parent or not stat.S_ISDIR(s.st_mode) or s.st_uid!=os.getuid() or stat.S_IMODE(s.st_mode)!=0o700:raise UnsafeTaskState('owned canonical0700 HOST directory required')
 def _file(self):
  self._directory();s=self.path.lstat()
  if self.path.resolve(strict=True)!=self.path or not stat.S_ISREG(s.st_mode) or s.st_uid!=os.getuid() or s.st_nlink!=1 or stat.S_IMODE(s.st_mode)!=0o600:raise UnsafeTaskState('owned single-link0600 HOST DB required')
 @contextmanager
 def _connection(self,write=False):
  self._file();db=sqlite3.connect(self.path.as_uri()+'?mode=rw',uri=True,timeout=5,isolation_level=None)
  try:
   if db.execute('PRAGMA application_id').fetchone()[0]!=APP_ID:raise UnsafeTaskState('task DB identity changed')
   db.execute('PRAGMA synchronous=FULL')
   if write:db.execute('BEGIN IMMEDIATE')
   else:db.execute('PRAGMA query_only=ON')
   yield db
   if write:db.execute('COMMIT')
  except BaseException:
   if write and db.in_transaction:db.execute('ROLLBACK')
   raise
  finally:db.close()
 def _destination(self,value):
  if value=='current':return 'current'
  if type(value) is not int or value not in self.allowed_legacy_ports:raise ValueError('destination outside fixed routing topology')
  return str(value)
 def _bind(self,db,task_id,destination,scope,provenance,topology):
  task_id=_task_id(task_id);key=_scope(scope);dest=self._destination(destination)
  if provenance not in PROVENANCE or (dest=='current')!=(provenance=='new_engine') or type(topology) is not str or len(topology)>256:raise ValueError('invalid ownership provenance')
  row=db.execute('SELECT destination,topology FROM routes WHERE scope_hash=? AND task_id=?',(key,task_id)).fetchone()
  if row and (row[0]!=dest or (row[1] and topology and row[1]!=topology)):raise RouteConflict('conflicting task ownership/topology; no reassignment')
  if row:
   db.execute('UPDATE routes SET provenance=?,topology=CASE WHEN topology=? THEN ? ELSE topology END,observed_ns=? WHERE scope_hash=? AND task_id=?',(provenance,'',topology,time.time_ns(),key,task_id))
  else:db.execute('INSERT INTO routes VALUES(?,?,?,?,?,?)',(key,task_id,dest,provenance,topology,time.time_ns()))
 def get_route(self,task_id,scope=''):
  with self._connection() as db:row=db.execute('SELECT destination FROM routes WHERE scope_hash=? AND task_id=?',(_scope(scope),_task_id(task_id))).fetchone()
  if row is None:return None
  return 'current' if row[0]=='current' else int(row[0])
 def transport_route(self,task_id):
  # Transport location only: the selected native backend still authenticates the request.
  with self._connection() as db:rows=db.execute('SELECT DISTINCT destination FROM routes WHERE task_id=?',(_task_id(task_id),)).fetchall()
  if len(rows)>1:raise RouteConflict('task identifier maps to conflicting scoped endpoints')
  if not rows:return None
  value='current' if rows[0][0]=='current' else int(rows[0][0]);self._destination(value);return value
 def bind(self,task_id,destination,scope='',provenance='own_list_tasks',topology=''):
  with self._connection(True) as db:self._bind(db,task_id,destination,scope,provenance,topology)
 def list_routes(self,scope=''):
  with self._connection() as db:rows=db.execute('SELECT task_id,destination FROM routes WHERE scope_hash=? ORDER BY task_id',(_scope(scope),)).fetchall()
  return [(r[0],'current' if r[1]=='current' else int(r[1])) for r in rows]
 def route_stats(self):
  with self._connection() as db:
   rows=db.execute('SELECT destination,count(*) FROM routes GROUP BY destination').fetchall();snapshots=db.execute('SELECT count(*) FROM legacy_snapshots').fetchone()[0];tasks=db.execute('SELECT count(*) FROM tasks').fetchone()[0]
  return {'total':sum(r[1] for r in rows),'current':sum(r[1] for r in rows if r[0]=='current'),'legacy':sum(r[1] for r in rows if r[0]!='current'),'snapshots':snapshots,'tasks':tasks}
 def save_legacy_snapshot(self,task_id,task_proto,owner_port,scope='',observed_at=None,provenance='own_list_tasks'):
  task,payload=_payload(task_proto)
  if task.id!=_task_id(task_id) or type(owner_port) is not int or owner_port not in self.allowed_legacy_ports or provenance not in ('own_list_tasks','ascending_exclusion','known_owner_response'):raise ValueError('invalid legacy snapshot identity/evidence')
  observed=time.time() if observed_at is None else observed_at
  if type(observed) not in (int,float) or not math.isfinite(observed) or not 0<observed<=time.time()+60:raise ValueError('invalid snapshot observation time')
  with self._connection(True) as db:
   self._bind(db,task_id,owner_port,scope,provenance,'')
   db.execute('INSERT INTO legacy_snapshots VALUES(?,?,?,?,?,?) ON CONFLICT(scope_hash,task_id) DO UPDATE SET payload=excluded.payload,observed_ns=excluded.observed_ns,provenance=excluded.provenance',(_scope(scope),task_id,owner_port,payload,int(observed*1e9),provenance))
 def get_legacy_snapshot(self,task_id,scope=''):
  with self._connection() as db:row=db.execute('SELECT owner_port,payload,observed_ns,provenance FROM legacy_snapshots WHERE scope_hash=? AND task_id=?',(_scope(scope),_task_id(task_id))).fetchone()
  return None if row is None else LegacySnapshot(task_id,row[0],bytes(row[1]),row[2]/1e9,row[3])
 def set_maintenance(self,enabled):
  if type(enabled) is not bool:raise ValueError('explicit boolean maintenance required')
  with self._connection(True) as db:db.execute("UPDATE host_control SET value=? WHERE name='maintenance'",('1' if enabled else '0',))
 def maintenance_enabled(self):
  with self._connection() as db:row=db.execute("SELECT value FROM host_control WHERE name='maintenance'").fetchone()
  if row is None or row[0] not in ('0','1'):raise UnsafeTaskState('invalid maintenance state')
  return row[0]=='1'
 def _public_key(self,key):
  if type(key) is not bytes or len(key)!=32:raise ValueError('public task/context digest required')
  return key
 def _public_time(self,now):
  if type(now) not in (int,float) or not math.isfinite(now) or now<=0:raise ValueError('explicit finite wall-clock time required')
  return float(now)
 def _public_rows(self,facts):
  if type(facts) not in (tuple,list) or len(facts)>3:raise ValueError('bounded public hint facts required')
  rows=[]
  for row in facts:
   if type(row) is not dict or set(row)!={'sku','grade','preferred_price'}:raise ValueError('public hint fields only')
   code=row['sku'];price=row['preferred_price']
   if type(code) is not str or not 1<=len(code)<=64 or any(not(c.isascii() and (c.isalnum() or c in '_-')) for c in code) or row['grade'] not in ('A','B','C') or type(price) is not int or not 0<price<=9223372036854775807:raise ValueError('invalid typed public hint')
   rows.append(dict(row))
  return rows
 def get_public_facts(self,key,now):
  key=self._public_key(key);now=self._public_time(now)
  with self._connection() as db:row=db.execute('SELECT facts_json,created_at,expires_at FROM public_facts WHERE key=?',(key,)).fetchone()
  if row is None or now<row[1] or now>=row[2]:return None
  return tuple(self._public_rows(json.loads(row[0])))
 def save_public_facts(self,key,facts,now,ttl=300,limit=300):
  key=self._public_key(key);now=self._public_time(now);rows=self._public_rows(facts)
  if type(ttl) not in (int,float) or not math.isfinite(ttl) or not 0<ttl<=300 or type(limit) is not int or not 1<=limit<=300:raise ValueError('bounded public hint retention required')
  with self._connection(True) as db:
   db.execute('DELETE FROM public_facts WHERE expires_at<=? OR created_at>?',(now,now))
   db.execute('INSERT INTO public_facts VALUES(?,?,?,?) ON CONFLICT(key) DO UPDATE SET facts_json=excluded.facts_json,created_at=excluded.created_at,expires_at=excluded.expires_at',(key,json.dumps(rows,separators=(',',':')),now,now+ttl))
   db.execute('DELETE FROM public_facts WHERE key IN (SELECT key FROM public_facts ORDER BY created_at DESC,key LIMIT -1 OFFSET ?)',(limit,))
 def _save_current(self,task,scope):
  if not isinstance(task,Task):raise TypeError('native SDK protobuf Task required')
  payload=task.SerializeToString(deterministic=True);_payload(payload)
  with self._connection(True) as db:
   self._bind(db,task.id,'current',scope,'new_engine','')
   db.execute('INSERT INTO tasks VALUES(?,?,?,?) ON CONFLICT(scope_hash,task_id) DO UPDATE SET payload=excluded.payload,updated_ns=excluded.updated_ns',(_scope(scope),task.id,payload,time.time_ns()))
 def _get_current(self,task_id,scope):
  with self._connection() as db:row=db.execute('SELECT payload FROM tasks WHERE scope_hash=? AND task_id=?',(_scope(scope),_task_id(task_id))).fetchone()
  return None if row is None else _payload(row[0])[0]
 def _list_current(self,scope):
  with self._connection() as db:rows=db.execute('SELECT payload FROM tasks WHERE scope_hash=?',(_scope(scope),)).fetchall()
  return [_payload(r[0])[0] for r in rows]
 def _delete_current(self,task_id,scope):
  # Keep route tombstone: deletion must not cause legacy reprobe/reassignment.
  with self._connection(True) as db:db.execute('DELETE FROM tasks WHERE scope_hash=? AND task_id=?',(_scope(scope),_task_id(task_id)))

class SQLiteTaskStore(TaskStore):
 """Unmodified SDK TaskStore API. Deep protobuf copies; same trusted owner resolver."""
 def __init__(self,state_db,owner_resolver=resolve_user_scope):
  if not isinstance(state_db,TaskStateDB):raise TypeError('private HOST TaskStateDB required')
  self.state_db=state_db;self.owner_resolver=owner_resolver
 def _owner(self,context):
  owner=self.owner_resolver(context);_scope(owner);return owner
 async def save(self,task,context):await asyncio.to_thread(self.state_db._save_current,task,self._owner(context))
 async def get(self,task_id,context):return await asyncio.to_thread(self.state_db._get_current,task_id,self._owner(context))
 async def delete(self,task_id,context):await asyncio.to_thread(self.state_db._delete_current,task_id,self._owner(context))
 async def list(self,params,context):
  owner=self._owner(context);tasks=await asyncio.to_thread(self.state_db._list_current,owner)
  # Delegate exact native filtering, cursor and pagination semantics, not a forked reimplementation.
  native=InMemoryTaskStore(owner_resolver=lambda _context:owner)
  for task in tasks:await native.save(task,context)
  return await native.list(params,context)
