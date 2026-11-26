"""Fixed-cutoff safe funnel windows. Read-only logs/DB; RPC proof is explicit opt-in."""
import argparse,json,time,re,sqlite3,sys,importlib.util
from pathlib import Path
from hashlib import sha256
from collections import Counter,defaultdict
from fractions import Fraction
OP=next(p for p in Path(__file__).resolve().parents if (p/'kit/agent_kit.py').exists())
HELPER=OP/'runtime/r3-stock-20261124-204104/agent-work/host/observe_equal_window_readonly.py'
spec=importlib.util.spec_from_file_location('safe_log_reader',HELPER);log=importlib.util.module_from_spec(spec);spec.loader.exec_module(log)
from rpc_trade_contribution_readonly import contributions
SKU=re.compile(r'(?<![A-Za-z0-9])[FG][a-fA-F0-9]{8}(?![A-Za-z0-9])')
FOLLOW=re.compile(r'그거|그\s*상품|이거|해당\s*상품|첫\s*번째|두\s*번째|방금|앞서|아까|그\s*두\s*개')
RECONFIRM={'explicit_purchase_confirmation_required','checkout_already_committed','already_dispatched'}
def read_data(op):
 prod=op.parent/'round-4';transport,tm=log.jsonlines([prod/'.kit/transport-metrics.jsonl',*log.preserved(op,'transport-metrics')]);trace,rm=log.jsonlines([prod/'.kit/decision-trace-review.jsonl',*log.preserved(op,'decision-trace-review')]);healthpath=Path((op/'runtime/r3-stock-latest-path.txt').read_text().strip())/'health-probes.jsonl';health,hm=log.jsonlines([healthpath]);groups=defaultdict(list)
 for row in trace:
  if isinstance(row.get('request_ref'),str):groups[row['request_ref']].append(row)
 customers={ref:min((r for r in rs if r.get('role')=='customer'),key=lambda r:r['at']) for ref,rs in groups.items() if any(r.get('role')=='customer' for r in rs)};known=set();link_methods=Counter()
 for probe in health:
  ptime=probe.get('at',probe.get('start'));reply=probe.get('reply');rhash=probe.get('reply_sha256');qhash=probe.get('request_text_sha256',probe.get('requesttextsha'));refs=set();evidence=probe.get('source_evidence',probe.get('evidence'))
  if isinstance(evidence,str):
   p=Path(evidence);p=p if p.is_absolute() else op/p
   try:
    p=p.resolve(strict=True);p.relative_to(op/'runtime');p=p/'safe-result.json' if p.is_dir() else p
    if p.is_file() and p.suffix=='.json':
     d=json.loads(p.read_bytes());refs=log.request_refs(d);reply=reply or log.final_reply(d);rhash=rhash or d.get('reply_sha256')
   except (OSError,ValueError,TypeError):pass
  direct=refs & groups.keys()
  if direct:known.update(direct);link_methods['explicit_probe_evidence_ref']+=len(direct);continue
  if type(ptime) not in (int,float):continue
  if isinstance(qhash,str) and re.fullmatch('[0-9a-f]{64}',qhash):
   exact=[ref for ref,r in customers.items() if isinstance(r.get('payload',{}).get('text'),str) and sha256(r['payload']['text'].encode()).hexdigest()==qhash and -2<=r['at']-ptime<=2]
   if len(exact)==1:known.add(exact[0]);link_methods['unique_probe_request_text_sha_and_timing']+=1;continue
  if not (isinstance(reply,str) or isinstance(rhash,str)):continue
  elapsed=probe.get('seconds',probe.get('elapsed_seconds'));elapsed=elapsed if type(elapsed) in (int,float) else 120;candidates=[]
  for ref,customer in customers.items():
   if not -2<=customer['at']-ptime<=2:continue
   ends=[r for r in groups[ref] if r.get('role')=='customer_received' and isinstance(r.get('payload',{}).get('reply'),str) and (r['payload']['reply']==reply or sha256(r['payload']['reply'].encode()).hexdigest()==rhash) and ptime<=r['at']<=ptime+elapsed+3]
   if ends:candidates.append(ref)
  if len(candidates)==1:known.add(candidates[0]);link_methods['unique_probe_reply_or_hash_and_timing']+=1
 return transport,groups,customers,known,{'transport':tm,'review_trace':rm,'health':hm,'operator_link_methods_whole_log':dict(link_methods)}
def group_kind(rows):
 validations={r.get('payload',{}).get('validation') for r in rows if r.get('role')=='tool'};channels={r.get('payload',{}).get('customer_channel') for r in rows if r.get('role')=='tool'};outcomes=[r['payload']['result'].get('outcome') for r in rows if r.get('role')=='tool' and isinstance(r.get('payload',{}).get('result'),dict)]
 if 'signed_checkout' in validations|channels:kind='checkout_delivered'
 elif 'public_verification_unavailable' in validations:kind='requested_product_not_verified_clear_reply'
 elif validations & {'verified_public_catalogue','verified_public_renderer'}:kind='verified_product_information'
 elif any(r.get('role')=='model_error' for r in rows):kind='model_error_or_timeout'
 elif 'public_lookup_required' in outcomes or 'public_lookup_uncertain' in outcomes:kind='lookup_retry_or_generic_fallback'
 elif 'public_text_only' in validations:kind='plain_text_without_verified_catalogue_reply'
 else:kind='other_or_no_final_validation'
 return kind,Counter(o for o in outcomes if o in RECONFIRM)
def window(op,start,end,data,proof):
 transport,groups,customers,known,_=data;selected=[(ref,r) for ref,r in customers.items() if start<=r['at']<end];external=[(ref,r) for ref,r in selected if ref not in known];kinds=Counter();reconfirmation=Counter();followup=0;explicit=0;messages=0
 for ref,r in external:
  kind,rs=group_kind(groups[ref]);kinds[kind]+=1;reconfirmation.update(rs);text=r.get('payload',{}).get('text','');explicit+=bool(SKU.search(text));followup+=bool(FOLLOW.search(text) and not SKU.search(text));messages+=sum(x.get('role')=='customer' for x in groups[ref])
 prod=op.parent/'round-4';path=prod/'state/r4-benefits/benefits.sqlite3'
 with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=5) as db:
  db.row_factory=sqlite3.Row;db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
  issued=db.execute('SELECT COUNT(*) FROM sale WHERE created>=? AND created<?',(start,end)).fetchone()[0];settled=db.execute("SELECT COUNT(*) FROM sale WHERE settled>=? AND settled<? AND status IN ('settled','refunded')",(start,end)).fetchone()[0]
  mileage=db.execute('SELECT COUNT(*),COALESCE(SUM(l.amount),0) FROM lot l JOIN sale s ON s.id=l.sale_id WHERE s.settled>=? AND s.settled<?',(start,end)).fetchone()
  spent=db.execute("SELECT COUNT(*),COALESCE(SUM(a.amount),0) FROM allocation a JOIN sale s ON s.id=a.sale_id WHERE a.status='spent' AND s.settled>=? AND s.settled<?",(start,end)).fetchone();db.rollback()
 matching=[r for r in proof['records_private_calculation'] if start<=r['settled_at']<end];verified=[r for r in matching if r['status']=='verified'];complete=len(verified)==settled
 margin=str(sum((Fraction(r['trade_contribution_after_full_new_lot_exact']) for r in verified),Fraction())) if complete else None
 ends=[r for r in transport if r.get('event')=='request_end' and start<=r.get('at',0)<end];durations=sorted(r['seconds'] for r in ends if type(r.get('seconds')) in (int,float))
 return {'start':start,'end':end,'seconds':end-start,'transport_started':sum(r.get('event')=='request_start' and start<=r.get('at',0)<end for r in transport),'transport_ended':len(ends),'server_p50_seconds':durations[len(durations)//2] if durations else None,'trace_message_count':messages,'trace_request_groups':len(selected),'registered_operator_groups':sum(ref in known for ref,r in selected),'non_operator_linked_request_groups':len(external),'verified_unique_people':None,'person_count_note':'Trace groups/messages and settled wallets do not establish distinct persons.','non_operator_linked_funnel':dict(kinds),'explicit_SKU_message_groups':explicit,'followup_reference_no_explicitSKU_groups':followup,'checkout_guard_outcome_counts':dict(reconfirmation),'new_checkout_rows':issued,'new_settlements':settled,'trade_margin_after_full_new_lot_credits_exact':margin,'trade_margin_receipt_evidence_complete':complete,'actual_fully_allocated_profit':None,'profit_note':'Zero settled trades means zero recognized trade margin; cumulative settled trades are reported separately. Holding/operating/unattributed costs are not fully allocated.','earned_lot_count':mileage[0],'full_earned_lot_burden_credits':mileage[1],'spent_mileage_allocation_count':spent[0],'spent_mileage_credits':spent[1]}
def main(op,end,span,bucket,verify_rpc,output):
 if not 0<end<=time.time() or not 0<span or not 0<bucket:raise ValueError('completed positive interval required')
 output.mkdir(mode=0o700,parents=True,exist_ok=False);data=read_data(op);proof=contributions(op,verify_rpc=verify_rpc);(output/'receipt-contribution-private.json').write_text(json.dumps(proof,indent=2))
 start=end-span;buckets=[];cursor=start
 while cursor<end:
  stop=min(end,cursor+bucket);buckets.append(window(op,cursor,stop,data,proof));cursor=stop
 cumulative=proof['records_private_calculation'];verified=[r for r in cumulative if r['status']=='verified'];margin=str(sum((Fraction(r['trade_contribution_after_full_new_lot_exact']) for r in verified),Fraction())) if len(verified)==proof['settled_count'] else None
 summary={'cutoff':end,'span_seconds':span,'baseline30m':window(op,end-1800,end,data,proof),'whole_span':window(op,start,end,data,proof),'buckets':buckets,'cumulative_actual_settlements':proof['settled_count'],'cumulative_verified_original_unit_contribution_count':proof['verified_count'],'cumulative_trade_margin_after_full_lot_credits_exact':margin,'cumulative_full_profit':None,'contribution_method':proof['method_notes'],'raw_input_cutoffs':data[-1],'actual_transaction_sends_Model_or_forum_calls':0,'receipt_readRPC_optin':verify_rpc,'limitations':['No exposure/conversion causality from a simple before/after window.','PRE must end at actual stop/cutoff; POST starts at verified readiness, excluding deployment downtime.','Two-hour buckets compare equal duration; a final short bucket is explicitly labelled by its seconds.','Raw customer text, rights, wallet identifiers, transaction hashes and Model reasoning are excluded.']}
 (output/'safe-summary.json').write_text(json.dumps(summary,indent=2));manifest={'code_sha256':{n:sha256((Path(__file__).parent/n).read_bytes()).hexdigest() for n in ['measure_conversion_readonly.py','rpc_trade_contribution_readonly.py']},'safe_summary_sha256':sha256((output/'safe-summary.json').read_bytes()).hexdigest(),'private_calculations_exported':False};(output/'MANIFEST.json').write_text(json.dumps(manifest,indent=2));print(json.dumps({'output':str(output),'span_non_operator_linked_messages':summary['whole_span']['trace_message_count'],'funnel':summary['whole_span']['non_operator_linked_funnel'],'span_checkouts':summary['whole_span']['new_checkout_rows'],'span_settled':summary['whole_span']['new_settlements'],'cumulative_settled':proof['settled_count'],'RPC_verified':proof['verified_count'],'raw_customer_or_financial_unit_rows_printed':False}))
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--operator',type=Path,default=OP);p.add_argument('--end',type=float,required=True);p.add_argument('--span',type=int,default=32400);p.add_argument('--bucket',type=int,default=7200);p.add_argument('--verify-rpc',action='store_true');p.add_argument('--output',type=Path,required=True);a=p.parse_args();main(a.operator,a.end,a.span,a.bucket,a.verify_rpc,a.output)
