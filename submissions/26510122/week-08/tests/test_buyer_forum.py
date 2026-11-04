import json,tempfile,time,unittest
from pathlib import Path
import buyer_forum

class BuyerForumTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.now=time.time()
  for p in ['logs','state','.market']:(self.root/p).mkdir()
  (self.root/'logs/buyer-events.jsonl').write_text(json.dumps({'event':'settled','at':self.now-60,'ledger':101,'sku':'tea','name':'Tea','shop_name':'Shop','price':950,'list_price':1000,'grade':'A','claim_honest':True})+'\n')
  self.decision={'action':'post','ledger_refs':[101],'headline':'구매 조건 확인 기록','body':'가격과 등급을 함께 확인한 거래입니다.','reason':'useful'}
 def model(self,role,prompt,schema):return {'approve':True,'unsupported_claims':[]} if 'checker' in role else self.decision
 def test_plain_purchase_below_twenty_percent_discount_can_publish(self):
  r=buyer_forum.run_once(self.root,now=self.now,model=self.model);self.assertEqual(r['status'],'queued')
  p=json.loads((self.root/'.market/outbox.jsonl').read_text());self.assertEqual(p['as'],'buyer');self.assertEqual(p['refs'],[101]);self.assertIn('950',p['post'])
  self.assertNotIn('order_budget',p['post'])
 def test_ack_is_required_and_same_ledger_not_posted_twice(self):
  buyer_forum.run_once(self.root,now=self.now,model=self.model)
  self.assertEqual(buyer_forum.run_once(self.root,now=self.now+2000,model=self.model)['status'],'pending')
  sent=json.loads((self.root/'.market/outbox.jsonl').read_text())
  (self.root/'.market/outbox.sent.jsonl').write_text(json.dumps({'sent':sent,'status':200,'answer':'{"id":42}'})+'\n')
  (self.root/'.market/outbox.jsonl').unlink()
  r=buyer_forum.run_once(self.root,now=self.now+2000,model=self.model);self.assertEqual(r['status'],'no_evidence')
  state=json.loads((self.root/'state/buyer-forum.json').read_text());self.assertEqual(state['posts'][0]['status'],'published');self.assertEqual(state['posts'][0]['post_id'],42)
 def test_fabricated_ledger_cannot_be_published(self):
  self.decision['ledger_refs']=[999]
  with self.assertRaises(ValueError):buyer_forum.run_once(self.root,now=self.now,model=self.model)
  self.assertFalse((self.root/'.market/outbox.jsonl').exists())
 def test_rejected_creative_is_removed_before_verified_facts_publish(self):
  self.decision['body']='근거가 부족한 분류 문구입니다.'
  def model(role,prompt,schema):
   return {'approve':False,'unsupported_claims':['unsupported category']} if 'checker' in role else self.decision
  result=buyer_forum.run_once(self.root,now=self.now,model=model)
  self.assertEqual(result['status'],'queued')
  text=json.loads((self.root/'.market/outbox.jsonl').read_text())['post']
  self.assertNotIn('근거가 부족한 분류',text)
  self.assertIn('정산된 가격',text);self.assertIn('원장 #101',text)
 def test_checker_receives_explicit_settlement_provenance(self):
  seen=[]
  def model(role,prompt,schema):
   if 'checker' in role:
    self.assertIn('creative_copy',prompt);self.assertNotIn('post',prompt)
    seen.extend(prompt['paid_evidence']);return {'approve':True,'unsupported_claims':[]}
   return self.decision
  buyer_forum.run_once(self.root,now=self.now,model=model,dry_run=True)
  self.assertEqual(seen[0]['event'],'settled');self.assertIn('successful paid settlement',seen[0]['provenance'])
 def test_dry_run_never_hands_off(self):
  self.assertEqual(buyer_forum.run_once(self.root,now=self.now,model=self.model,dry_run=True)['status'],'dry_run')
  self.assertFalse((self.root/'.market/outbox.jsonl').exists())
