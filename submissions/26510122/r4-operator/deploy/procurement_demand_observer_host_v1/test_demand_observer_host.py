from pathlib import Path
from tempfile import TemporaryDirectory
import json,sys,unittest,hashlib,os
sys.path.insert(0,str(Path(__file__).parent))
import demand_observer_host as h
class QA(unittest.TestCase):
 def setUp(self):
  self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.trace=self.root/'trace.jsonl';self.trace.write_text('');self.now=1000.;self.calls=[];self.health=[]
 def add(self,ref,role,payload,at=None):
  with self.trace.open('a') as f:f.write(json.dumps({'at':self.now if at is None else at,'request_ref':ref,'role':role,'payload':payload},ensure_ascii=False)+'\n')
 def observer(self):return h.Observer(self.trace,lambda args:self.calls.append(args) or True,lambda:self.health,clock=lambda:self.now)
 def request(self,ref='r1',text='소이밀크 가격 보여 주세요',validation='verified_semantic_candidates'):
  self.add(ref,'customer',{'text':text,'from':'operator-SELF-UNTRUSTED'});self.add(ref,'model',{'raw':json.dumps({'thought':'PRIVATE_REASON_SENTINEL','action':'search_similar_products','args':{'product_phrase':'소이밀크','queries':['두유']}})});self.add(ref,'tool',{'action':'search_similar_products','validation':validation});self.add(ref,'customer_received',{'reply':'candidate','state':'input_required'})
 def test_old_history_is_not_replayed(self):
  self.request('old');o=self.observer();self.now+=200;o.poll();self.assertEqual(self.calls,[])
 def test_future_turn_debounce_and_no_raw_metrics(self):
  o=self.observer();self.now+=1;self.request();o.poll();self.now+=119;o.poll();self.assertEqual(self.calls,[]);self.now+=1;summary=o.poll();self.assertEqual(len(self.calls),1);self.assertEqual(self.calls[0]['queries'],['두유']);self.assertNotIn('PRIVATE_REASON_SENTINEL',json.dumps(summary));self.assertNotIn('소이밀크',json.dumps(summary));self.assertNotIn('operator-SELF',json.dumps(summary));self.assertEqual(self.calls[0]['source'],'external_completed')
 def test_late_health_before_flush_excludes(self):
  o=self.observer();self.now+=1;self.request();o.poll();self.health=[{'at':self.now,'ended_at':self.now+2,'request_text_sha256':hashlib.sha256('소이밀크 가격 보여 주세요'.encode()).hexdigest()}];self.now+=121;o.poll();self.assertEqual(self.calls,[])
 def test_no_match_is_weak_signal_unsupported_is_not(self):
  o=self.observer();self.now+=1;self.request('miss',validation='no_match');self.request('unsafe',validation='unsupported_request');o.poll();self.now+=121;o.poll();self.assertEqual(len(self.calls),1);self.assertEqual(self.calls[0]['queries'],['두유'])
 def test_rotation_fences_copied_history(self):
  o=self.observer();self.trace.rename(self.root/'old');self.trace.write_text('');self.request('copied');o.poll();self.now+=1;self.request('future');o.poll();self.now+=121;o.poll();self.assertEqual(len(self.calls),1)
 def test_same_ref_is_not_double_recorded(self):
  o=self.observer();self.now+=1;self.request();o.poll();self.now+=121;o.poll();self.now+=1;self.request();o.poll();self.now+=121;o.poll();self.assertEqual(len(self.calls),1)
 def test_partial_utf8_and_malformed_do_not_echo(self):
  o=self.observer();self.now+=1
  raw=(json.dumps({'at':self.now,'request_ref':'a','role':'customer','payload':{'text':'합성 개인정보 SENTINEL'}},ensure_ascii=False)+'\n').encode();self.trace.write_bytes(raw[:-2]);o.poll();self.trace.write_bytes(raw);self.add('a','customer_received',{'reply':'ok'});o.poll();self.now+=121;summary=o.poll();self.assertEqual(len(self.calls),1);self.assertNotIn('SENTINEL',json.dumps(summary))
 def test_exclusion_snapshot_supports_late_classification(self):
  text='synthetic';sha=hashlib.sha256(text.encode()).hexdigest();meta=[{'event_ref':'a'*64,'text_sha':sha,'at':1000}];rows=[{'at':1000,'ended_at':1001,'request_text_sha256':sha}];x=h.exclusion_snapshot(meta,rows,[],1200);self.assertEqual(x['event_refs'],[hashlib.sha256(b'r4:stock-request:event:v2\x00'+b'a'*64).hexdigest()]);self.assertNotIn(text,json.dumps(x))
 def test_truncate_then_regrow_cannot_replay_prefix(self):
  o=self.observer();self.now+=1;self.request('first');o.poll();self.now+=121;o.poll()
  self.trace.write_text('');self.request('historical_rewrite','copied '*50);o.poll();self.now+=1;self.request('new');o.poll();self.now+=121;o.poll();self.assertEqual(len(self.calls),2)
 def test_native_insufficient_does_not_claim_insertion(self):
  o=self.observer();o.record=lambda args:{'status':'insufficient_evidence'};self.now+=1;self.request();o.poll();self.now+=121;summary=o.poll();self.assertEqual(o.completed_meta,[]);self.assertEqual(summary['counts']['native_insufficient_evidence'],1)
 def test_transient_native_failure_has_bounded_same_ref_retry(self):
  o=self.observer();attempts=[]
  def call(args):attempts.append(args['event_ref']);return {'status':'catalog_unavailable'}
  o.record=call;self.now+=1;self.request();o.poll();self.now+=121;o.poll();self.now+=61;o.poll();self.now+=61;o.poll();self.now+=61;o.poll();self.assertEqual(len(attempts),3);self.assertEqual(len(set(attempts)),1)
 def test_hour_coverage_requires_contiguous_sequences(self):
  catalog=[{'sku':'G00000001','name':' 合成  商品 ','category':'食 品'}];ledger=[{'seq':i,'ts':ts,'kind':'join','round':4,'data':{}} for i,ts in [(1,100),(2,3000),(3,3999)]];a,b=h.public_snapshot(ledger,catalog,4000);self.assertTrue(a['coverage']['complete']);self.assertEqual(b['items'][0]['name'],'合成 商品');ledger[1]['seq']=5;a,b=h.public_snapshot(ledger,catalog,4000);self.assertFalse(a['coverage']['complete'])
 def test_public_projection_removes_private_fields_and_retains_unknown(self):
  ledger=[{'seq':1,'ts':1000,'kind':'settle','round':4,'data':{'sku':'G00000001','grade':'A','amount':100,'shop':'https://seller.invalid','buyer':'PRIVATE_BUYER','order':'PRIVATE_ORDER','tx_hash':'PRIVATE_TX','shop_fee':1}}];catalog=[{'sku':'G00000001','name':'합성 두유','category':'식품','PRIVATE':'SECRET'}];a,b=h.public_snapshot(ledger,catalog,1010);raw=json.dumps([a,b]);self.assertNotIn('PRIVATE_BUYER',raw);self.assertNotIn('PRIVATE_ORDER',raw);self.assertNotIn('PRIVATE_TX',raw);self.assertIsNone(a['events'][0]['broken']);self.assertIsNone(a['events'][0]['sealed']);self.assertFalse(a['coverage']['complete']);self.assertEqual(a['events'][0]['shop_fee'],1)
 def test_catalogue5629_is_complete_and_bounds_fail(self):
  catalog=[{'sku':f'G{i:08x}','name':'합성','category':'식품'} for i in range(5629)];a,b=h.public_snapshot([],catalog,1000);self.assertEqual(len(b['items']),5629)
  with self.assertRaises(ValueError):h.public_snapshot([],catalog*2,1000)
 def test_public_pagination_dedupes_and_marks_partial(self):
  calls=[]
  def fetch(path):
   calls.append(path)
   if path=='/api/catalog':return [{'sku':'G00000001','name':'합성','category':'식품'}]
   n=int(path.split('-')[-1]);return [{'seq':n+i,'ts':900+i,'kind':'join','round':4,'data':{}} for i in range(2)]
  x=h.publish_public(self.root,fetch,lambda:1000);self.assertEqual(x['ledger_pages'],4);self.assertFalse(x['one_hour_coverage_complete']);self.assertTrue((self.root/'host_inputs/stock-public-catalog.json').exists())
if __name__=='__main__':unittest.main()
