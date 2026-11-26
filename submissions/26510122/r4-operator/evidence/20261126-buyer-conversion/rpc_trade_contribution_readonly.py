"""Read-only actual-chain trade contribution. Never uses cached unit cost or sends a transaction."""
import ast,json,re,time,sqlite3
from pathlib import Path
from fractions import Fraction
from hashlib import sha256
import httpx
METHODS={'eth_getTransactionByHash','eth_getTransactionReceipt','eth_blockNumber'}
HEX=re.compile(r'0x[0-9a-fA-F]+\Z');TX=re.compile(r'0x[0-9a-fA-F]{64}\Z')
def integer(x):
 if not isinstance(x,str) or not HEX.fullmatch(x):raise ValueError('invalid chain integer')
 return int(x,16)
def constants(path):
 out={}
 for n in ast.parse(path.read_text()).body:
  if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id in {'RPC','MARKET'}:out[n.targets[0].id]=ast.literal_eval(n.value)
 if set(out)!={'RPC','MARKET'}:raise ValueError('missing reviewed endpoint constants')
 return out
class ReadChain:
 def __init__(self,source):
  self.endpoints=constants(source);self.inputs=[];self.cache={};self.client=httpx.Client(timeout=8,trust_env=False,follow_redirects=False)
  r=self.client.get(self.endpoints['MARKET']+'/api/chain');r.raise_for_status();facts=r.json()
  if facts.get('rpc')!=self.endpoints['RPC'] or facts.get('chain_id')!=450815 or type(facts.get('credit_wei')) is not int or facts['credit_wei']<=0:raise ValueError('unexpected chain configuration')
  self.credit=facts['credit_wei'];self.inputs.append({'kind':'chain_config','sha256':sha256(r.content).hexdigest(),'at':time.time()});self.head=integer(self.rpc('eth_blockNumber'))
 def rpc(self,method,*args):
  if method not in METHODS:raise ValueError('RPC mutation forbidden')
  key=(method,*args)
  if key in self.cache:return self.cache[key]
  r=self.client.post(self.endpoints['RPC'],json={'jsonrpc':'2.0','id':1,'method':method,'params':list(args)});r.raise_for_status();doc=r.json()
  if doc.get('error') or 'result' not in doc:raise ValueError('RPC unavailable')
  self.inputs.append({'method':method,'response_sha256':sha256(r.content).hexdigest(),'at':time.time()});self.cache[key]=doc['result'];return doc['result']
 def transfer(self,txhash,sender,recipient,expected,marker):
  if not isinstance(txhash,str) or not TX.fullmatch(txhash):raise ValueError('unverified transaction hash')
  t=self.rpc('eth_getTransactionByHash',txhash);r=self.rpc('eth_getTransactionReceipt',txhash)
  low=lambda x:x.lower() if isinstance(x,str) else None
  if not isinstance(t,dict) or not isinstance(r,dict):raise ValueError('missing transaction receipt')
  if not (low(t.get('hash'))==low(txhash)==low(r.get('transactionHash')) and low(t.get('from'))==low(sender) and low(t.get('to'))==low(recipient) and low(t.get('input'))==low(marker) and integer(t.get('value'))==int(expected) and integer(r.get('status'))==1 and isinstance(t.get('blockHash'),str) and TX.fullmatch(t['blockHash']) and low(t.get('blockHash'))==low(r.get('blockHash')) and t.get('blockNumber')==r.get('blockNumber') and self.head>=integer(t['blockNumber'])+2):raise ValueError('transaction case binding unverified')
  return integer(t['value']),integer(r.get('gasUsed'))*integer(r.get('effectiveGasPrice'))
 def close(self):self.client.close()
def contributions(operator,*,verify_rpc=False):
 prod=operator.parent/'round-4';path=prod/'state/r4-benefits/benefits.sqlite3'
 with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=5) as db:
  db.row_factory=sqlite3.Row;db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
  seller=db.execute('SELECT wallet FROM identity WHERE singleton=1').fetchone()[0]
  sales=[dict(r) for r in db.execute("SELECT id,unit,status,payment,payer,wallet,expected_wei,digest,settled FROM sale WHERE settled IS NOT NULL AND status IN ('settled','refunded')")]
  intents=[dict(r) for r in db.execute("SELECT units,delivered,qty,tx,wei,recipient,marker,state FROM stock_intent WHERE state='arrived'")]
  lots={r['sale_id']:dict(r) for r in db.execute('SELECT sale_id,amount,revoked FROM lot')};db.rollback()
 chain=ReadChain(prod/'codex-r4/dispatcher.py') if verify_rpc and sales else None;records=[]
 try:
  for sale in sales:
   rec={'settled_at':sale['settled'],'status':'unavailable','reason':'RPC verification not requested','lot_full_burden_credits':lots.get(sale['id'],{}).get('amount')}
   try:
    if not chain:records.append(rec);continue
    if sale['status']=='refunded':raise ValueError('refunded transaction requires refund cash-flow reconciliation')
    matches=[x for x in intents if sale['unit'] in json.loads(x['units'] or '[]')]
    if len(matches)!=1:raise ValueError('original unit purchase mapping not unique')
    intent=matches[0];units=json.loads(intent['units']);delivered=json.loads(intent['delivered']) if intent['delivered'] else None
    if type(intent['qty']) is not int or intent['qty']!=len(units) or len(set(units))!=len(units) or intent['qty']<=0 or (delivered is not None and set(delivered)!=set(units)):raise ValueError('original unit batch evidence inconsistent')
    lot=lots.get(sale['id'])
    if not lot or type(lot['amount']) is not int or lot['amount']<0 or lot['revoked'] is not None:raise ValueError('full earned-lot burden not established')
    incoming,_buyer_gas=chain.transfer(sale['payment'],sale['payer'],sale['wallet'],sale['expected_wei'],'0x'+sale['digest'])
    outgoing,seller_gas=chain.transfer(intent['tx'],seller,intent['recipient'],intent['wei'],intent['marker'])
    purchase=Fraction(outgoing+seller_gas,intent['qty']*chain.credit);received=Fraction(incoming,chain.credit);burden=Fraction(lot['amount']);value=received-purchase-burden
    rec.update(status='verified',reason=None,receipt_cash_in_credits_exact=str(received),original_unit_purchase_plus_gas_credits_exact=str(purchase),trade_contribution_after_full_new_lot_exact=str(value),batch_qty=intent['qty'])
   except (ValueError,TypeError,KeyError,httpx.HTTPError,json.JSONDecodeError) as e:rec['reason']=str(e) if isinstance(e,ValueError) else type(e).__name__
   records.append(rec)
  metadata=chain.inputs if chain else []
 finally:
  if chain:chain.close()
 return {'records_private_calculation':records,'verified_count':sum(r['status']=='verified' for r in records),'settled_count':len(sales),'receipt_input_hashes':metadata,'RPC_methods_allowed':sorted(METHODS),'actual_transaction_send_calls':0,'method_notes':['Original physical unit maps uniquely into one arrived procurement intent; actual transfer value plus actual receipt gas, allocated equally only if batch has multiple units.','Actual seller receipt cash is already net of redeemed mileage; prior mileage spending is not subtracted again.','Full newly earned lot amount including the extra bonus is charged conservatively at issuance; future redemption/refund accounting is separate.','This is verified transaction contribution, not fully allocated final profit. Holding/operating costs not separately attributable are not allocated; bundled procurement payments may already include charges.','No cached accounting unit-price field is queried or used.']}
