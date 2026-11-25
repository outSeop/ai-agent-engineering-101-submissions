from pathlib import Path
import json,sys,time,tempfile,hashlib,argparse
P=argparse.ArgumentParser();P.add_argument('--sources',required=True);P.add_argument('--output',required=True);a=P.parse_args();source=Path(a.sources);out=Path(a.output);op=Path('/home/seop/.local/share/ourolabs-r4-checkout/submissions/26510122/r4-operator');sys.path.insert(0,str(op/'kit'));import agent_kit as official
checks=[]
def ck(n,b,detail=None):checks.append(dict(case=n,passed=bool(b),observed=detail))
def row(i,expiry):return dict(unit_ref='SYNTH-'+str(i),sku=f'G{i:08X}',name='합성 사과',category_path=['식품'],state='available',grade='A',price_credits=1000+i,standard_fee_credits=1,expires_at=expiry)
def doc(rows):
 now=int(time.time());return dict(schema='outseop-r4.customer-offers.v1',shop='outseop-r4',observed_at=now-1,valid_until=now+120,units=rows)
with tempfile.TemporaryDirectory(dir=out,prefix='Synthetic-lifetime-') as t:
 root=Path(t);tool=root/'tools/public_catalogue';tool.mkdir(parents=True);(root/'logs').mkdir();inputs=root/'host_inputs';inputs.mkdir(mode=0o700);file=inputs/'customer_offer_context.json'
 for n in ('logic.py','test.py','permission.yml','forge.json'):(tool/n).write_bytes((source/n).read_bytes())
 tb=official.Toolbox(root,dict(market='https://market.ourolabs.ai',name='outseop-r4',tokens={},addresses={},signer=official.Signer({},root)))
 def write(d):
  if file.exists():file.chmod(0o600)
  file.write_text(json.dumps(d,ensure_ascii=False));file.chmod(0o400)
 def call(args):
  e=tb.call('public_catalogue',args);assert e.get('ok'),e;return e['result']
 for minimum in (0,59,60,61):
  now=int(time.time());d=doc([row(1,now+60),row(2,None),row(3,now)])
  write(d);z=call(dict(op='search',min_remaining_seconds=minimum));expected=['G00000001','G00000002'] if minimum==0 else ['G00000001'] if minimum<=60 else []
  if z.get('status')=='ready':
   expected=[u['sku'] for u in d['units'] if (u['expires_at'] is None and minimum==0) or (u['expires_at'] is not None and u['expires_at']>z['as_of'] and u['expires_at']-z['as_of']>=minimum)]
   ck('minimum_boundary_'+str(minimum),[r[0] for r in z['rows']]==expected,dict(expected=expected,returned=[r[0] for r in z['rows']]))
  else:ck('minimum_boundary_'+str(minimum),z.get('reason')=='query_restart_required',dict(result=z,boundary_crossed=True))
 now=int(time.time());d=doc([row(1,now+2),row(2,now+100)]);write(d);first=call(dict(op='search',limit=1));nx=first.get('catalogue',{}).get('next_args');assert nx
 time.sleep(max(0,now+2.05-time.time()));z=call(nx);ck('cursor_eligibility_expired_since_first_page',z==dict(status='unavailable',reason='query_restart_required'))
 write(doc([row(1,int(time.time())+100)]));z=call(dict(op='search',q='test@example.net'));ck('sensitive_q_not_echoed','test@example.net' not in json.dumps(z,ensure_ascii=False),dict(status=z.get('status'),reason=z.get('reason'),uniformly_rejected=z.get('status')=='unavailable'))
result=dict(source_logic_sha256=hashlib.sha256((source/'logic.py').read_bytes()).hexdigest(),checks=checks,passed=sum(x['passed'] for x in checks),failed=sum(not x['passed'] for x in checks),all_inputs_synthetic=True,ordinary_SDK_call=True,source_changes=0,clock_patched=False,model_market_DB_wallet_calls=0)
(out/'independent-lifetime-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False))
