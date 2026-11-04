import json,os,random,tempfile,time,unittest
from pathlib import Path
from unittest.mock import Mock
import seller_meta as meta
from seller_meta_policy import active,DEFAULT,validate
from procurement_cost import ceiling
from capital_policy import operating_policy,ROUND_END
import inventory_portfolio as portfolio

class MetaHarnessTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=Path.cwd();os.chdir(self.tmp.name)
  self.addCleanup(self.tmp.cleanup);self.addCleanup(os.chdir,self.old)
  self.root=Path.cwd();self.now=10000
  for p in ['.market','state','logs']:(self.root/p).mkdir()
  self.inv={'round':3,'balance':10_000_000,'units':[],'restock':{'open':True,'opens_at':9990,'closes_at':10170}}
  self.cat={'bed':{'name':'Bed','kind':'goods','category':'beds','list_price':4_000_000}}
  (self.root/'.market/catalog.json').write_text(json.dumps(self.cat));self.fresh()
 def fresh(self,now=None):
  t=self.now if now is None else now;p=self.root/'.market/inventory.json';p.write_text(json.dumps(self.inv));os.utime(p,(t,t))
 def decision(self,value=6_000_000):return {'action':'change','parameter':'window_budget','numeric_value':value,'focus_value':None,'reason':'Observe smaller spend','expected_effect':'Controlled experiment','evidence':['risk']}
 def test_high_ticket_candidate_is_affordable_and_surge_is_reserved(self):
  self.assertEqual(ceiling(self.cat['bed']),4_500_000)
  def choose(role,prompt,schema):
   self.assertEqual(prompt['candidates'][0]['sku'],'bed')
   return {'action':'buy','skus':['bed'],'replenishment':[],'reason':'Single high ticket test'}
  result=portfolio.run(self.inv,self.cat,[],self.now,model=choose,rng=random.Random(1),refresh=lambda:(self.inv,self.now,True))
  self.assertEqual(result,{'buy':[{'sku':'bed','qty':1}]})
  i=json.loads(portfolio.STATE.read_text())['intents'][0];self.assertEqual(i['cost_ceiling'],4_500_000)
 def test_single_change_is_active_and_hard_market_cutoff_remains(self):
  r=meta.review(self.root,now=self.now,public=[],model=lambda *a:self.decision())
  self.assertEqual(r['status'],'changed');self.assertEqual(operating_policy(self.now)['window_budget'],6_000_000)
  self.assertEqual(operating_policy(ROUND_END-3600)['window_budget'],0)
  self.assertEqual(active(self.now+14401)['meta_status'],'operator_default')
 def test_no_rapid_or_unobserved_retuning(self):
  meta.review(self.root,now=self.now,public=[],model=lambda *a:self.decision())
  later=self.now+1801;self.fresh(later)
  r=meta.review(self.root,now=later,public=[],model=lambda *a:self.decision(3_000_000))
  self.assertEqual(r['status'],'evaluation_pending');self.assertEqual(active(later)['window_budget'],6_000_000)
 def test_shadow_does_not_write_active_policy(self):
  r=meta.review(self.root,now=self.now,public=[],model=lambda *a:self.decision(),shadow=True)
  self.assertEqual(r['status'],'shadow');self.assertFalse((self.root/'state/seller-meta-policy.json').exists())
 def test_invalid_bounds_never_become_live_config(self):
  for d in [dict(DEFAULT,epsilon=0),dict(DEFAULT,window_budget=13_000_000),dict(DEFAULT,focus='disable guards'),dict(DEFAULT,extra=1)]:
   with self.assertRaises(ValueError):validate(d)
  with self.assertRaises(ValueError):meta.revised(DEFAULT,self.decision(1_200_000))
 def test_stale_evidence_never_calls_policy_model(self):
  model=Mock(side_effect=AssertionError('must not call'))
  with self.assertRaises(ValueError):meta.review(self.root,now=self.now+31,public=[],model=model)
  model.assert_not_called()
