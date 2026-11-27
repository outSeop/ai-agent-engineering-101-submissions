"""Manifest-pinned operator configuration only. Never accepts customer/A2A parameters."""
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import json,re
def operator_root(value=None):
 if value is not None:
  p=Path(value)
  if not p.is_absolute() or p.resolve(strict=True)!=p:raise ValueError('canonical absolute operator root required')
  return p
 for p in Path(__file__).resolve().parents:
  if (p/'kit/agent_kit.py').is_file() and (p/'sources/upstream.json').is_file():return p
 raise ValueError('pass the operator root explicitly')
OP=operator_root()
SCHEMA='outseop-r4.front-release.v1'
def exact(value,keys):
 if type(value) is not dict or set(value)!=set(keys):raise ValueError('unknown/missing front configuration fields')
def unit(value):
 if type(value) is not str or not re.fullmatch(r'ourolabs-market-r4(?:-[A-Za-z0-9_-]+)?\.service',value):raise ValueError('invalid fixed user service')
 return value
def positive(value):
 if type(value) is not int or value<=0:raise ValueError('positive PID hint required')
 return value
def port(value):
 if type(value) is not int or not 18805<value<=65535:raise ValueError('invalid local listener port')
 return value
def digest(value):
 if type(value) is not str or not re.fullmatch('[0-9a-f]{64}',value):raise ValueError('exact manifest SHA256 required')
 return value
def artifact(value,leaf=None,*,operator=None):
 if type(value) is not str:raise ValueError('operator artifact path required')
 op=operator_root(operator);p=Path(value)
 if not p.is_absolute():p=op/p
 if '..' in p.parts or not (p.is_relative_to(op/'runtime') or p.is_relative_to(op/'deploy')) or (leaf and p.name!=leaf):raise ValueError('artifact outside fixed operator roots')
 return p
def state(value):
 if type(value) is not str:raise ValueError('private relative state required')
 p=Path(value)
 if str(p)!=value or p.is_absolute() or '..' in p.parts or not p.parts or p.parts[0]!='runtime' or len(p.parts)<2:raise ValueError('state must stay under fixed operator/runtime')
 return value
def marker(value):
 if type(value) is not str or not re.fullmatch('[A-Za-z0-9_.-]{1,80}',value):raise ValueError('invalid HTTP marker')
 return value
@dataclass(frozen=True)
class Role:
 service:str
 pid_hint:int
@dataclass(frozen=True)
class Edge:
 port:int
 service:str
 pid_hint:int
 launcher:Path
 manifest_path:Path
 manifest_sha256:str
 marker:str
 state_dir:str
@dataclass(frozen=True)
class FrontConfig:
 new_port:int
 old_proxy_port:int
 marker:str
 state_dir:str
 service:str
 runtime_path:Path
 runtime_manifest_sha256:str
 main:Role
 worker:Role
 cf_pid_hint:int
 edges:tuple
 semantic_instruction:object=None
 operator_root:object=None
 @property
 def card_ports(self):return (18805,*(e.port for e in self.edges),self.new_port)
 @property
 def idle_ports(self):return (18805,*(e.port for e in self.edges))
 @property
 def old_marker(self):return self.edges[-1].marker
 @property
 def services(self):return (self.main.service,self.worker.service,*(e.service for e in self.edges),self.service)

def parse(data,operator=None):
 op=operator_root(operator)
 required={'schema','new_port','old_proxy_port','marker','state_dir','service','runtime_path','runtime_manifest_sha256','main','worker','cf_pid_hint','preserved_edges'}
 if type(data) is not dict or set(data) not in (required,required|{'semantic_instruction'}) or data['schema']!=SCHEMA:raise ValueError('unreviewed front config schema')
 roles=[]
 for name in ('main','worker'):
  exact(data[name],('service','pid_hint'));roles.append(Role(unit(data[name]['service']),positive(data[name]['pid_hint'])))
 if roles[0].service!='ourolabs-market-r4.service' or roles[1].service!='ourolabs-market-r4-worker.service':raise ValueError('original main and worker identities fixed')
 rows=data['preserved_edges']
 if type(rows) is not list or not 1<=len(rows)<=64:raise ValueError('bounded preserved chain required')
 edges=[]
 for row in rows:
  exact(row,('port','service','pid_hint','launcher','manifest_path','manifest_sha256','marker','state_dir'))
  launcher=artifact(row['launcher'],'run_front_edge.py',operator=op);manifest=artifact(row['manifest_path'],'MANIFEST.json',operator=op)
  if launcher.parent!=manifest.parent:raise ValueError('edge manifest must bind its exact launcher folder')
  edges.append(Edge(port(row['port']),unit(row['service']),positive(row['pid_hint']),launcher,manifest,digest(row['manifest_sha256']),marker(row['marker']),state(row['state_dir'])))
 ports=[e.port for e in edges];new=port(data['new_port']);old=port(data['old_proxy_port'])
 if ports!=sorted(set(ports)) or old!=ports[-1] or new in ports or new<=old:raise ValueError('invalid forward-only port chain')
 services=[r.service for r in roles]+[e.service for e in edges]+[unit(data['service'])]
 states=[e.state_dir for e in edges]+[state(data['state_dir'])];markers=[e.marker for e in edges]+[marker(data['marker'])]
 if len(set(services))!=len(services) or len(set(states))!=len(states) or len(set(markers))!=len(markers):raise ValueError('existing service/gate/marker cannot be reused')
 if any(Path(states[-1]).is_relative_to(Path(old)) or Path(old).is_relative_to(Path(states[-1])) for old in states[:-1]):raise ValueError('new state must not overlap preserved state directories')
 semantic=data.get('semantic_instruction')
 if semantic is not None and (type(semantic) is not str or not 1<=len(semantic)<=1500 or '\x00' in semantic):raise ValueError('bounded HOST semantic instruction required')
 return FrontConfig(new,old,markers[-1],states[-1],services[-1],artifact(data['runtime_path'],operator=op),digest(data['runtime_manifest_sha256']),roles[0],roles[1],positive(data['cf_pid_hint']),tuple(edges),semantic,op)

def unique(pairs):
 result={}
 for k,v in pairs:
  if k in result:raise ValueError('duplicate configuration key')
  result[k]=v
 return result
def load_pinned(folder,verified_manifest,operator=None):
 """Caller must first validate whole own manifest against operator supplied expected SHA."""
 folder=Path(folder);path=folder/'RUNTIME-BINDING.json';raw=path.read_bytes()
 if path.resolve(strict=True)!=path or len(raw)>65536 or sha256(raw).hexdigest()!=verified_manifest['files'].get('RUNTIME-BINDING.json'):raise ValueError('configuration is not bound by reviewed own manifest')
 return parse(json.loads(raw,object_pairs_hook=unique),operator=operator)
