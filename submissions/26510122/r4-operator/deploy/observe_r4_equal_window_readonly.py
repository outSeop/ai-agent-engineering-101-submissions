"""Read-only, fixed-window R4 observations. No API, Model, POST, key reads or DB writes."""
import argparse,json,re,sqlite3,time,math
from pathlib import Path
from hashlib import sha256
from collections import Counter,defaultdict
from datetime import datetime,timezone
OP=next(p for p in Path(__file__).resolve().parents if (p/'kit/agent_kit.py').exists())
def canon(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
def jsonlines(paths):
 rows=[];seen=set();meta=[]
 for path in dict.fromkeys(paths):
  raw=path.read_bytes();bad=0;added=0
  for line in raw.splitlines():
   try:v=json.loads(line)
   except ValueError:bad+=1;continue
   if not isinstance(v,dict):bad+=1;continue
   digest=sha256(canon(v)).digest()
   if digest in seen:continue
   seen.add(digest);rows.append(v);added+=1
  meta.append({'path':str(path),'bytes_at_read':len(raw),'sha256_at_read':sha256(raw).hexdigest(),'unique_rows_added':added,'invalid_lines':bad,'full_file':True})
 return rows,meta
def request_refs(v):
 found=set()
 if isinstance(v,dict):
  for k,x in v.items():
   if k in {'request_ref','matching_request_ref','matched_request_ref'} and isinstance(x,str):found.add(x)
   elif isinstance(x,(dict,list)):found.update(request_refs(x))
 elif isinstance(v,list):
  for x in v:found.update(request_refs(x))
 return found
def final_reply(v):
 if not isinstance(v,dict):return None
 task=v.get('result',{});task=task.get('task',task) if isinstance(task,dict) else {}
 try:return task['status']['message']['parts'][0]['text']
 except (KeyError,IndexError,TypeError):return v.get('reply') if isinstance(v.get('reply'),str) else None
def preserved(op,name):
 paths=[]
 for d in (op/'runtime').iterdir():
  if d.is_dir() and any(x in d.name for x in ['cutover','followup-readonly','catalogue-loop']):
   for folder in [d,d/'before',d/'backup',d/'.kit']:
    if folder.is_dir():paths.extend(p for p in folder.iterdir() if p.is_file() and name in p.name and p.suffix in {'.jsonl','.bak'})
 return paths
INFO=re.compile(r'상품|제품|재고|가격|등급|기한|유통|남은|포장|수량|식품|\b(?:price|stock|grade|expiry|product)\b',re.I)
BUY=re.compile(r'구매(?:하겠|할게|합니다|할래|해\s*주세요)|주문(?:할게|하겠|해주세요)|결제(?:할게|하겠|합니다)|살게|사겠|\b(?:I will buy|I.ll buy|buy this)\b',re.I)
NOT_BUY=re.compile(r'비구매|구매\s*의사\s*없|구매\s*아님|안\s*(?:살|사|구매|결제)|구매하지|no\s+purchase',re.I)
ACTIONS={'shop_context','search_products','render_public_products','offer','quote_and_send','review_refund','respond'}
def observe(op,start,end,duration,transport_paths,trace_paths,output):
 now=time.time()
 if not (math.isfinite(start) and math.isfinite(end) and start<end<=now and end-start==duration):raise ValueError('completed interval with end-start==duration required')
 prod=op.parent/'round-4';health_path=Path((op/'runtime/r3-stock-latest-path.txt').read_text().strip())/'health-probes.jsonl'
 transport,tmeta=jsonlines(transport_paths or [prod/'.kit/transport-metrics.jsonl',*preserved(op,'transport-metrics')]);trace,rmeta=jsonlines(trace_paths or [prod/'.kit/decision-trace-review.jsonl',*preserved(op,'decision-trace-review')]);health,hmeta=jsonlines([health_path])
 groups=defaultdict(list)
 for row in trace:
  if isinstance(row.get('request_ref'),str):groups[row['request_ref']].append(row)
 customers={ref:min((r for r in rs if r.get('role')=='customer'),key=lambda r:r.get('at',float('inf'))) for ref,rs in groups.items() if any(r.get('role')=='customer' for r in rs)}
 known=set();methods=Counter();ambiguous=0;emeta=[]
 for probe in health:
  ptime=probe.get('at');reply=probe.get('reply');reply_hash=probe.get('reply_sha256');refs=set();evidence=probe.get('source_evidence',probe.get('evidence'))
  if isinstance(evidence,str):
   p=Path(evidence)
   if not p.is_absolute():p=op/p
   try:
    p=p.resolve(strict=True);p.relative_to(op/'runtime')
    if p.is_dir():p=p/'safe-result.json'
    if p.is_file() and p.suffix=='.json':
     raw=p.read_bytes();doc=json.loads(raw);refs=request_refs(doc);reply=reply or final_reply(doc);reply_hash=reply_hash or doc.get('reply_sha256');emeta.append({'path':str(p),'sha256_at_read':sha256(raw).hexdigest(),'bytes_at_read':len(raw)})
   except (OSError,ValueError,TypeError):pass
  matched=refs & groups.keys()
  if matched:known.update(matched);methods['explicit_evidence_request_ref']+=len(matched);continue
  if (not isinstance(reply,str) and not (isinstance(reply_hash,str) and re.fullmatch(r'[0-9a-f]{64}',reply_hash))) or type(ptime) not in (int,float):continue
  elapsed=probe.get('seconds',probe.get('elapsed_seconds'));elapsed=elapsed if type(elapsed) in (int,float) else 120
  candidates=[]
  for ref,customer in customers.items():
   if not -2<=customer.get('at',0)-ptime<=2:continue
   ends=[r for r in groups[ref] if r.get('role')=='customer_received' and ((isinstance(reply,str) and r.get('payload',{}).get('reply')==reply) or (isinstance(r.get('payload',{}).get('reply'),str) and sha256(r['payload']['reply'].encode()).hexdigest()==reply_hash)) and ptime<=r.get('at',0)<=ptime+elapsed+3]
   if ends:candidates.append(ref)
  if len(candidates)==1:known.add(candidates[0]);methods['unique_operator_reply_hash_and_timing' if not isinstance(reply,str) else 'unique_exact_operator_reply_and_timing']+=1
  elif len(candidates)>1:ambiguous+=1
 within=[(ref,r) for ref,r in customers.items() if start<=r.get('at',0)<end];unlinked=[(ref,r) for ref,r in within if ref not in known];categories=Counter();actions=Counter()
 for ref,r in unlinked:
  text=r.get('payload',{}).get('text','');text=text if isinstance(text,str) else ''
  category='explicit_purchase_like' if BUY.search(text) and not NOT_BUY.search(text) else 'public_product_information_like' if INFO.search(text) else 'other_or_undetermined';categories[category]+=1
  for event in groups[ref]:
   action=event.get('payload',{}).get('action') if event.get('role')=='model' else None
   if action in ACTIONS:actions[action]+=1
 starts=[r for r in transport if r.get('event')=='request_start' and start<=r.get('at',0)<end];ends=[r for r in transport if r.get('event')=='request_end' and start<=r.get('at',0)<end];durations=sorted(r['seconds'] for r in ends if type(r.get('seconds')) in (int,float));endrefs={r.get('internal_ref') for r in ends};allends={r.get('internal_ref'):r.get('at',0) for r in transport if r.get('event')=='request_end'}
 ledger=prod/'state/r4-benefits/benefits.sqlite3'
 with sqlite3.connect(ledger.as_uri()+'?mode=ro',uri=True,timeout=5) as db:
  db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
  checkouts=db.execute('SELECT COUNT(*) FROM sale WHERE created>=? AND created<?',(start,end)).fetchone()[0];settled=db.execute("SELECT COUNT(*) FROM sale WHERE settled>=? AND settled<? AND status IN ('settled','refunded')",(start,end)).fetchone()[0]
  contribution=db.execute("SELECT SUM(price-cost) FROM sale WHERE settled>=? AND settled<? AND status IN ('settled','refunded')",(start,end)).fetchone()[0]
  posts=db.execute("SELECT content FROM forum_publication WHERE created>=? AND created<? AND status='posted'",(start,end)).fetchall();grades=Counter()
  for content, in posts:
   found=set(re.findall(r'(?<![A-Za-z0-9])([ABC])\s*등급',content));grades.update(found or ['unspecified'])
  pending={'signed_sales':db.execute("SELECT COUNT(*) FROM sale WHERE status IN ('issued','cancel_requested','paid','missing')").fetchone()[0],'refunds':db.execute("SELECT COUNT(*) FROM refund WHERE status!='refunded'").fetchone()[0],'procurement_unknown':db.execute("SELECT COUNT(*) FROM stock_intent WHERE state IN ('sending','unknown')").fetchone()[0]};db.rollback()
 result={'window':{'start':start,'end':end,'duration_seconds':duration,'left_inclusive_right_exclusive':True,'start_UTC':datetime.fromtimestamp(start,timezone.utc).isoformat(),'end_UTC':datetime.fromtimestamp(end,timezone.utc).isoformat(),'captured_at':now,'completed':True},'transport':{'starts':len(starts),'ends':len(ends),'started_not_ended_within_cutoff':sum(r.get('internal_ref') not in endrefs for r in starts),'completed_after_cutoff':sum(allends.get(r.get('internal_ref'),0)>=end for r in starts),'server_p50_seconds':durations[len(durations)//2] if durations else None,'server_max_seconds':max(durations) if durations else None,'checkout_envelopes_by_end':sum(r.get('result_kind')=='checkout' for r in ends)},'trace':{'request_groups':len(within),'operator_linked_groups':sum(ref in known for ref,r in within),'not_operator_linked_groups':len(unlinked),'not_operator_linked_categories':dict(categories),'not_operator_linked_model_action_counts':dict(actions),'link_methods_whole_log':dict(methods),'ambiguous_probe_matches_whole_log':ambiguous},'health_probes_recorded_in_window':sum(start<=r.get('at',0)<end for r in health),'ledger':{'new_checkout_rows':checkouts,'new_settlements_including_later_refunded':settled,'settled_price_less_purchase_cost':contribution if settled else None,'actual_profit':None,'profit_note':'No actual settlement in interval.' if not settled else 'Full actual profit unavailable: price-cost contribution excludes fees, gas, storage, refunds and benefits.','posted_forum':len(posts),'posted_grade_presence_counts':dict(grades),'grade_note':'Per-post presence; a multi-grade post contributes to multiple grades.','pending_at_capture':pending},'limitations':['Not-operator-linked inquiry groups are not verified distinct buyers or proven buyer identities.','Transport and trace use separate random references; they are not joined by guessed request IDs.','Same reply plus unique recorded timing is separately labelled, not treated as an explicit request-ref match.','No marketing causality, conversion improvement or A/B inference follows from one short interval.','No raw question/reply, actor, request reference, Model reason, key or ledger row is emitted.'],'source_cutoff':{'transport':tmeta,'review_trace':rmeta,'health':hmeta,'operator_evidence':list({x['path']:x for x in emeta}.values()),'DB_read_transaction':True},'actual_API_Model_posts_prod_mutations':0}
 output.parent.mkdir(parents=True,exist_ok=True);output.write_bytes(canon(result)+b'\n');output.chmod(0o600);return result
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--operator',type=Path,default=OP);p.add_argument('--start',type=float,required=True);p.add_argument('--end',type=float,required=True);p.add_argument('--duration',type=int,required=True);p.add_argument('--transport',type=Path,action='append');p.add_argument('--trace',type=Path,action='append');p.add_argument('--output',type=Path,required=True);a=p.parse_args();r=observe(a.operator,a.start,a.end,a.duration,a.transport,a.trace,a.output);print(json.dumps({k:v for k,v in r.items() if k!='source_cutoff'}))
