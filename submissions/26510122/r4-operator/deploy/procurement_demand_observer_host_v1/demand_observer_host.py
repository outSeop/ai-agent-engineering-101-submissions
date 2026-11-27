"""External host plumbing: future-only demand ingestion and public raw projections. No decisions or payments."""
from pathlib import Path
import argparse,contextlib,hashlib,io,json,math,os,re,stat,time,unicodedata
MAX_LINE=65536
ROOT=Path('/home/seop/.local/share/ourolabs-r4-checkout/submissions/26510122/round-4')
OP=ROOT.parent/'r4-operator'
PUBLIC_SKU=re.compile(r'[FG][0-9a-fA-F]{8}\Z')
HEX64=re.compile(r'[0-9a-f]{64}\Z')
def finite(v):return type(v) in (int,float) and math.isfinite(v)
def strict_read(path,maximum=16*1024*1024):
 p=Path(path);st=p.lstat()
 if p.resolve()!=p or not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or st.st_mode&0o022 or st.st_size>maximum:raise ValueError('unsafe host source')
 fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as f:return f.read(maximum+1)
def atomic_json(path,value):
 p=Path(path);p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 if p.parent.resolve()!=p.parent:raise ValueError('unsafe destination')
 raw=(json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode();tmp=p.with_name(p.name+'.tmp-'+str(os.getpid()))
 fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 try:
  with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
  os.replace(tmp,p)
 finally:
  if tmp.exists():tmp.unlink()
class FutureReader:
 def __init__(self,path):self.path=Path(path);self.identity=None;self.offset=0;self.partial=b'';self.discard=False;self.anchor=b'';self.resets=0
 def fence(self):
  st=self.path.lstat()
  if self.path.resolve()!=self.path or not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid():raise ValueError('unsafe trace')
  self.identity=(st.st_dev,st.st_ino);self.offset=st.st_size;self.partial=b'';self.discard=False
  with self.path.open('rb') as f:f.seek(max(0,self.offset-64));self.anchor=f.read(min(64,self.offset))
 def lines(self):
  st=self.path.lstat()
  if self.path.resolve()!=self.path or not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid():raise ValueError('unsafe trace')
  identity=(st.st_dev,st.st_ino)
  if identity!=self.identity or st.st_size<self.offset:self.fence();self.resets+=1;return []
  with self.path.open('rb') as f:
   f.seek(max(0,self.offset-64))
   if f.read(min(64,self.offset))!=self.anchor:self.fence();self.resets+=1;return []
   f.seek(self.offset);chunk=f.read(512*1024);self.offset=f.tell();f.seek(max(0,self.offset-64));self.anchor=f.read(min(64,self.offset))
  if self.discard:
   if b'\n' not in chunk:return []
   chunk=chunk.split(b'\n',1)[1];self.discard=False
  blocks=(self.partial+chunk).split(b'\n');self.partial=blocks.pop()
  if len(self.partial)>MAX_LINE:self.partial=b'';self.discard=True
  return [line for line in blocks if 0<len(line)<=MAX_LINE]
def health_rows(path):
 if not Path(path).exists():raise ValueError('health registry unavailable')
 rows=[]
 for line in strict_read(path).splitlines():
  try:d=json.loads(line)
  except (ValueError,UnicodeDecodeError):continue
  if isinstance(d,dict) and finite(d.get('at')) and finite(d.get('ended_at')) and isinstance(d.get('request_text_sha256'),str) and HEX64.fullmatch(d['request_text_sha256']):rows.append(d)
 return rows
def is_probe(row,health,excluded):
 return row['ref'] in excluded or any(h['request_text_sha256']==row['text_sha'] and h['at']-2<=row['at']<=h['ended_at']+2 for h in health)
def semantic_args(value):
 if not isinstance(value,dict) or set(value) not in ({'queries'},{'product_phrase','queries'}):return None
 qs=value['queries']
 if not isinstance(qs,list) or not 1<=len(qs)<=2 or any(type(q) is not str or not 1<=len(q)<=48 for q in qs):return None
 if 'product_phrase' in value and (type(value['product_phrase']) is not str or not 1<=len(value['product_phrase'])<=128):return None
 return {k:v for k,v in value.items()}
class Observer:
 def __init__(self,trace,record,health,excluded=(),clock=time.time):
  self.reader=FutureReader(trace);self.reader.fence();self.record=record;self.health=health;self.excluded=set(excluded);self.clock=clock;self.started=clock();self.pending={};self.counts={};self.seen={};self.completed_meta=[]
 def count(self,key):self.counts[key]=self.counts.get(key,0)+1
 def ingest(self,line):
  try:d=json.loads(line)
  except (ValueError,UnicodeDecodeError):self.count('malformed');return
  if not isinstance(d,dict) or not isinstance(d.get('request_ref'),str) or not 1<=len(d['request_ref'])<=128 or not finite(d.get('at')):return
  at=d['at'];now=self.clock()
  if not self.started-2<=at<=now+5:self.count('timestamp_fence');return
  ref=d['request_ref'];role=d.get('role');v=d.get('payload')
  if not isinstance(v,dict):return
  if role=='customer':
   if ref in self.pending or ref in self.seen:self.count('duplicate_ref');return
   text=v.get('text')
   if type(text) is not str or not 1<=len(text)<=1500 or len(self.pending)>=512:return
   self.pending[ref]={'ref':ref,'at':at,'text':text,'text_sha':hashlib.sha256(text.encode()).hexdigest(),'move':None,'semantic':None,'blocked':False,'completed':None};self.count('future_customer');return
  row=self.pending.get(ref)
  if row is None:return
  if role=='model' and type(v.get('raw')) is str and len(v['raw'])<=32768:
   try:move=json.loads(v['raw'])
   except ValueError:return
   row['move']=semantic_args(move.get('args')) if isinstance(move,dict) and move.get('action')=='search_similar_products' else None
   row['semantic']=None
  elif role=='tool' and v.get('action')=='search_similar_products':
   validation=v.get('validation')
   if validation in ('verified_semantic_candidates','no_match') and row['move'] is not None:row['semantic']=row['move'];row['signal']='semantic_success' if validation=='verified_semantic_candidates' else 'semantic_no_match'
   else:row['blocked']=True
  elif role=='customer_received' and isinstance(v.get('reply'),str) and v['reply']:
   row['completed']=at
 def poll(self):
  for line in self.reader.lines():self.ingest(line)
  now=self.clock();health=self.health()
  for ref,row in list(self.pending.items()):
   if now-row['at']>900:self.pending.pop(ref);self.count('expired');continue
   if row['completed'] is None or now-row['completed']<120 or now<row.get('retry_after',0):continue
   self.pending.pop(ref);self.seen[ref]=now
   if is_probe(row,health,self.excluded):self.count('operator_excluded');continue
   if row['blocked']:self.count('unsafe_semantic_skipped');continue
   args={'op':'record','text':row['text'],'event_ref':hashlib.sha256(('r4-stock-request-v1:'+ref).encode()).hexdigest(),'observed_at':row['at'],'source':'external_completed'}
   if row['semantic'] is not None:args.update(row['semantic'])
   try:result=self.record(args)
   except Exception:result=False
   status=('recorded' if result is True else result.get('status','call_failed') if isinstance(result,dict) else 'call_failed')
   allowed={'recorded','duplicate','insufficient_evidence','invalid_request','catalog_unavailable','storage_unavailable','call_failed'}
   status=status if status in allowed else 'call_failed';self.count('native_'+status)
   if status in ('catalog_unavailable','storage_unavailable','call_failed') and row.get('attempts',0)<2:
    row['attempts']=row.get('attempts',0)+1;row['retry_after']=now+60;self.pending[ref]=row;self.seen.pop(ref,None)
   elif status in ('recorded','duplicate'):self.completed_meta.append({'event_ref':args['event_ref'],'text_sha':row['text_sha'],'at':row['at']})
  self.seen={key:at for key,at in self.seen.items() if now-at<21600}
  self.completed_meta=[r for r in self.completed_meta if now-r['at']<21600][-10000:]
  return {'at':now,'counts':dict(self.counts),'pending_count':len(self.pending),'trace_offset':self.reader.offset,'trace_resets':self.reader.resets,'raw_text_or_actor_or_Model_reason_persisted':False}
def nonnegative(v):return v if type(v) is int and v>=0 else None
def public_shop(v):
 from urllib.parse import urlsplit
 if type(v) is not str or not 1<=len(v)<=512:return None
 try:u=urlsplit(v)
 except ValueError:return None
 return v if u.scheme=='https' and u.hostname and not u.username and not u.password and not u.query and not u.fragment else None
def public_snapshot(ledger,catalog,now,complete=None):
 if not isinstance(ledger,list) or len(ledger)>2000 or not isinstance(catalog,list) or len(catalog)>10000:raise ValueError('public source bound')
 events=[]
 for row in ledger:
  if not isinstance(row,dict) or row.get('round')!=4:continue
  d=row.get('data');d=d if isinstance(d,dict) else {};order=d.get('order');sku=d.get('sku');kind=row.get('kind');ts=row.get('ts')
  e={'seq':nonnegative(row.get('seq')),'ts':ts if finite(ts) and ts>=0 else None,'kind':kind if type(kind) is str and len(kind)<=64 else None,'round':4,'sku':sku if type(sku) is str and PUBLIC_SKU.fullmatch(sku) else None,'grade':d.get('grade') if d.get('grade') in ('A','B','C') else None,'amount':nonnegative(d.get('amount')),'shop':public_shop(d.get('shop')),'broken':d.get('broken') if type(d.get('broken')) is bool else None,'sealed':d.get('sealed') if type(d.get('sealed')) is bool else None,'order_ref':hashlib.sha256(order.encode()).hexdigest() if type(order) is str and 0<len(order)<=256 else None}
  for field in ('shop_fee','buyer_fee','market_fee'):e[field]=nonnegative(d.get(field))
  for field in ('expires_at','warranty_hours'):
   value=d.get(field);e[field]=value if finite(value) and value>=0 else None
  events.append(e)
 items=[]
 for row in catalog:
  if not isinstance(row,dict):raise ValueError('catalogue schema')
  sku,name,category=(row.get(k) for k in ('sku','name','category'))
  if not(type(sku) is str and PUBLIC_SKU.fullmatch(sku) and type(name) is str and type(category) is str):raise ValueError('catalogue schema')
  name=' '.join(name.split());category=' '.join(category.split())
  if not 0<len(name)<=512 or not 0<len(category)<=512 or any(unicodedata.category(ch).startswith('C') for ch in name+category):raise ValueError('catalogue public string unsafe')
  items.append({'sku':sku,'name':name,'category':category})
 if len({row['sku'].upper() for row in items})!=len(items):raise ValueError('duplicate catalogue SKU')
 timestamps=[row.get('ts') for row in ledger if isinstance(row,dict) and finite(row.get('ts'))]
 seqs=sorted(row['seq'] for row in ledger if isinstance(row,dict) and type(row.get('seq')) is int)
 contiguous=bool(seqs) and len(seqs)==len(ledger) and all(b==a+1 for a,b in zip(seqs,seqs[1:]))
 inferred=bool(timestamps) and min(timestamps)<=now-3600 and contiguous
 is_complete=inferred if complete is None else bool(complete and inferred)
 return ({'observed_at':int(now),'valid_until':int(now)+150,'round':4,'coverage':{'since':min(timestamps) if timestamps else now,'complete':is_complete},'events':events},{'observed_at':int(now),'valid_until':int(now)+150,'round':4,'items':items})
def fetch_public(path):
 import httpx
 data=bytearray()
 with httpx.stream('GET','https://market.ourolabs.ai'+path,trust_env=False,follow_redirects=False,timeout=8) as r:
  r.raise_for_status()
  for chunk in r.iter_bytes():
   data.extend(chunk)
   if len(data)>8*1024*1024:raise ValueError('public source byte cap')
 return json.loads(data)
def publish_public(root,fetch=fetch_public,clock=time.time):
 now=clock();byseq={};pages=0
 for offset in (500,1000,1500,2000):
  batch=fetch('/api/ledger?after=-'+str(offset));pages+=1
  if not isinstance(batch,list) or len(batch)>500:raise ValueError('ledger page schema')
  for row in batch:
   if not isinstance(row,dict) or type(row.get('seq')) is not int or row['seq']<0:raise ValueError('ledger sequence schema')
   if row['seq'] in byseq and byseq[row['seq']]!=row:raise ValueError('ledger sequence changed')
   byseq[row['seq']]=row
  timestamps=[row.get('ts') for row in byseq.values() if finite(row.get('ts'))]
  if not batch or timestamps and min(timestamps)<=now-3600:break
 ledger=[byseq[key] for key in sorted(byseq)];catalog=fetch('/api/catalog');a,b=public_snapshot(ledger,catalog,clock())
 if any(len(json.dumps(x,ensure_ascii=False).encode())>2*1024*1024 for x in (a,b)):raise ValueError('projected source byte cap')
 atomic_json(root/'host_inputs/stock-demand-signals.json',a);atomic_json(root/'host_inputs/stock-public-catalog.json',b)
 return {'at':clock(),'ledger_events':len(a['events']),'ledger_pages':pages,'catalogue_items':len(b['items']),'one_hour_coverage_complete':a['coverage']['complete'],'source_TTL_seconds':150,'business_statistics_computed':False}
def stored_event_hash(event_ref):
 return hashlib.sha256(b'r4:stock-request:event:v2\x00'+event_ref.encode('ascii')).hexdigest()
def exclusion_snapshot(meta,health,excluded,now):
 refs={stored_event_hash(hashlib.sha256(('r4-stock-request-v1:'+ref).encode()).hexdigest()) for ref in excluded}
 for row in meta:
  if isinstance(row,dict) and type(row.get('event_ref')) is str and HEX64.fullmatch(row['event_ref']) and finite(row.get('at')) and type(row.get('text_sha')) is str and any(h['request_text_sha256']==row['text_sha'] and h['at']-2<=row['at']<=h['ended_at']+2 for h in health):refs.add(stored_event_hash(row['event_ref']))
 return {'observed_at':int(now),'valid_until':int(now)+150,'round':4,'event_refs':sorted(refs)}

def recorder_callback(root,forge_pin):
 import sys
 sys.path.insert(0,str(OP/'kit'));import agent_kit as official
 entries=json.loads(strict_read(OP/'sources/upstream.json'))['files']
 if len(entries)!=7:raise ValueError('SDK7 required')
 for entry in entries:
  raw=strict_read(OP/'kit'/entry['name'])
  if hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()!=entry['upstream_git_blob_sha']:raise ValueError('original SDK drift')
 directory=root/'tools/record_stock_request'
 def verify():
  raw=strict_read(directory/'forge.json')
  if hashlib.sha256(raw).hexdigest()!=forge_pin:raise ValueError('unreviewed recorder source')
  manifest=json.loads(raw)
  if manifest.get('tool')!='record_stock_request':raise ValueError('unexpected recorder name')
  for name in ('logic.py','permission.yml','test.py'):
   if hashlib.sha256(strict_read(directory/name)).hexdigest()!=manifest['sha256'][name]:raise ValueError('recorder source drift')
  perm=official.forge_runner.parse_permission(strict_read(directory/'permission.yml').decode()).get('permission') or {}
  if any(perm.get(k) for k in ('network','identity','wallet','handles','exec')) or perm.get('pay_limit',0)!=0 or perm.get('write')!=['state/r4-demand']:raise ValueError('recorder capability rejected')
 verify()
 class NoWallet:
  url=None
  def grant(self,name,perm,timeout):
   if name!='record_stock_request' or any(perm.get(k) for k in ('network','identity','wallet','handles','exec')) or perm.get('pay_limit',0)!=0:raise ValueError('no financial capabilities')
   return None
  def revoke(self,cap):return []
 official.mk.LOG_FILE=None
 context={'name':'outseop-r4','market':'https://market.ourolabs.ai','tokens':{},'addresses':{},'signer':NoWallet()}
 with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):box=official.Toolbox(root,context)
 def call(args):
  verify()
  with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):result=box.run('record_stock_request','call',args)
  # Never echo args, exception messages, tool trace or printed text.
  if not isinstance(result,dict) or result.get('ok') is not True:return {'status':'call_failed'}
  native=result.get('result');status=native.get('status') if isinstance(native,dict) else None
  return {'status':status if status in ('recorded','duplicate','insufficient_evidence','invalid_request','catalog_unavailable','storage_unavailable') else 'call_failed'}
 return call

def main(argv=None):
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--recorder-forge-sha',required=True);parser.add_argument('--run',action='store_true');args=parser.parse_args(argv);os.umask(0o077)
 record=recorder_callback(ROOT,args.recorder_forge_sha)
 if not args.run:print(json.dumps({'status':'checked_only','SDK7':True,'recorder_capabilities_no_finance':True,'Model_calls':0,'listener_or_payment_or_request_recording_started':False}));return
 pointer=Path(strict_read(OP/'runtime/r3-stock-latest-path.txt',4096).decode().strip())
 if not pointer.is_relative_to(OP/'runtime') or pointer.resolve()!=pointer:raise ValueError('untrusted health registry parent')
 health_path=pointer/'health-probes.jsonl';excluded_path=OP/'runtime/model-minimal-20261126-method/operator-test-exclusions-private.json'
 exclusions=json.loads(strict_read(excluded_path))['exact_operator_decision_refs'];excluded=[x['decision_ref'] for x in exclusions]
 observer=Observer(ROOT/'.kit/decision-trace-private.jsonl',record,lambda:health_rows(health_path),excluded)
 state=OP/'runtime/procurement-demand-observer-live';state.mkdir(exist_ok=True,mode=0o700);next_source=0
 meta_path=state/'completed-metadata.json'
 if meta_path.exists():
  loaded=json.loads(strict_read(meta_path,2*1024*1024))
  if isinstance(loaded,list):observer.completed_meta=loaded[-10000:]
 while True:
  now=time.time()
  if now>=next_source:
   try:summary=publish_public(ROOT)
   except Exception:summary={'at':now,'status':'public_source_unavailable'}
   atomic_json(state/'source-safe.json',summary);next_source=time.time()+60
  try:summary=observer.poll()
  except Exception:summary={'at':time.time(),'status':'observer_unavailable','raw_data_output':False}
  atomic_json(state/'observer-safe.json',summary)
  try:
   health=health_rows(health_path);atomic_json(ROOT/'host_inputs/stock-demand-exclusions.json',exclusion_snapshot(observer.completed_meta,health,excluded,time.time()));atomic_json(meta_path,observer.completed_meta)
  except Exception:pass # No fresh exclusion attestation is published on unavailable registry.
  time.sleep(1)
if __name__=='__main__':main()
