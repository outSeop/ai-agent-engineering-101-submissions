"""Typed HOST metadata unit wiring only: isolated import-loader base stub.
Not a genuine-tool, actual SDK, Model meaning or payment test.
"""
from pathlib import Path
from copy import deepcopy
from hashlib import sha256
from types import ModuleType
from unittest.mock import patch
import importlib.util,json,sys,tempfile,unittest
SOURCE=Path(__file__).resolve().parents[2]/'src/r4_operator_host'
PROTOCOL_BASE="""import re
class CatalogueError(ValueError):pass
def sku(v):return isinstance(v,str) and re.fullmatch(r'[FG][A-Fa-f0-9]{8}',v) is not None
class CatalogueProtocol:
 def __init__(self,*args):self.calls=[]
 def result(self,op,result,observed,valid):
  self.calls.append((op,result,observed,valid));return dict(result,base_checked=True)
"""
BROKER_BASE="""from copy import deepcopy
SEMANTIC_INSTRUCTION='fixture instruction'
def mask(text):return text
class Broker:
 def __init__(self,*args,**kwargs):self.catalogue=kwargs['catalogue'];self.trace=kwargs.get('trace')
 def handle(self,text,**kwargs):
  if text=='RAISE_SYNTHETIC':raise RuntimeError('synthetic base failure')
  self.catalogue.semantic();answer={'reply':text,'state':'completed','data':{'existing':'preserved'}}
  if self.trace:self.trace.add('synthetic-ref','customer_received',deepcopy(answer),{'fixture':True})
  return answer
"""
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);exec(compile(path.read_bytes(),str(path),'exec'),module.__dict__);return module
def terminal():return {'status':'rendered','reply':'SYNTHETIC_VERIFIED_REPLY','observed_at':1000,'valid_until':1100,'payment_request':{'status':'not_issued','reason':'product_selection_required'},'public_facts':[{'sku':'G00000001','grade':'A','preferred_price':100}]}
class Catalogue:
 def __init__(self,result):self.result=result
 def semantic(self,*args,**kwargs):return self.result
class Trace:
 def __init__(self):self.rows=[]
 def add(self,*args):self.rows.append(deepcopy(args))
class MetadataTransportTests(unittest.TestCase):
 def setUp(self):
  temp=tempfile.TemporaryDirectory(prefix='host-metadata-import-fixture-');self.addCleanup(temp.cleanup);self.root=Path(temp.name);base=self.root/'deploy/pinned-base';base.mkdir(parents=True)
  self.base=base
  for name,data in [('public_catalogue_protocol.py',PROTOCOL_BASE),('broker_public_catalogue_host_candidate.py',BROKER_BASE)]:
   (base/name).write_text(data)
  manifest={'file_sha256':{p.name:sha256(p.read_bytes()).hexdigest() for p in base.iterdir()}};raw=json.dumps(manifest).encode();(base/'MANIFEST.json').write_bytes(raw)
  context={'schema':'r4-host-context.v1','operator_root':str(self.root),'base_protocol':'deploy/pinned-base/public_catalogue_protocol.py','base_protocol_sha256':manifest['file_sha256']['public_catalogue_protocol.py'],'base_manifest_sha256':sha256(raw).hexdigest()}
  lane=ModuleType('card_source_read_lane')
  def raw_file(path):
   path=Path(path)
   if path==SOURCE/'HOST-CONTEXT.json':return json.dumps(context).encode()
   if path.is_relative_to(base):return path.read_bytes()
   raise AssertionError('unexpected import fixture read')
  lane.raw_file=raw_file
  with patch.dict(sys.modules,{'card_source_read_lane':lane}):
   self.protocol=load('_metadata_protocol_test',SOURCE/'catalogue_protocol.py')
   broker_core=load('_metadata_broker_core_test',base/'broker_public_catalogue_host_candidate.py')
   with patch.dict(sys.modules,{'public_catalogue_protocol':self.protocol,'catalogue_broker_core':broker_core}):self.broker=load('_metadata_broker_test',SOURCE/'catalogue_broker.py')
 def test_typed_extras_are_removed_before_base_validation_and_copied_back(self):
  original=terminal();saved=deepcopy(original);p=self.protocol.CatalogueProtocol();out=p.result('semantic_candidates',original,1000,1100)
  self.assertTrue(out['base_checked']);plain=p.calls[0][1];self.assertNotIn('payment_request',plain);self.assertNotIn('public_facts',plain)
  self.assertEqual(out['payment_request'],saved['payment_request']);self.assertEqual(out['public_facts'],saved['public_facts']);self.assertEqual(original,saved)
  out['payment_request']['reason']='mutated only in output';out['public_facts'][0]['preferred_price']=1;self.assertEqual(original,saved)
 def test_authorizing_or_malformed_metadata_is_rejected_before_base(self):
  for change in [lambda x:x['payment_request'].update(status='issued'),lambda x:x['payment_request'].update(reason='arbitrary'),lambda x:x['payment_request'].update(reason=[]),lambda x:x['public_facts'][0].update(grade={}),lambda x:x['payment_request'].update(checkout_jwt='synthetic-no-token'),lambda x:x['public_facts'][0].update(preferred_price=True),lambda x:x.update(public_facts=[])]:
   value=terminal();change(value);p=self.protocol.CatalogueProtocol()
   with self.subTest():
    with self.assertRaises(self.protocol.CatalogueError):p.result('semantic_candidates',value,1000,1100)
    self.assertEqual(p.calls,[])
 def test_final_delivery_and_customer_received_trace_match_once(self):
  value=terminal();catalogue=Catalogue(value);trace=Trace();remembered=[];broker=self.broker.Broker(catalogue=catalogue,trace=trace)
  answer=broker.handle(value['reply'],remember=lambda facts:remembered.append(deepcopy(facts)) or True)
  delivered=trace.rows[-1][2];self.assertEqual(answer,delivered);self.assertEqual(answer['state'],'input_required');self.assertEqual(answer['data']['existing'],'preserved');self.assertEqual(answer['data']['payment_request']['status'],'not_issued');self.assertEqual(len(remembered),1)
  self.assertIs(broker.catalogue,catalogue);self.assertIs(broker.trace,trace)
 def test_unrelated_reply_never_receives_metadata_or_memory(self):
  view=self.broker.CatalogueView(Catalogue(terminal()));view.semantic();calls=[];delivery=self.broker.Delivery(view,lambda facts:calls.append(facts) or True);answer={'reply':'unrelated fixed error','state':'completed'}
  self.assertIs(delivery.apply(answer),answer);self.assertEqual(calls,[]);self.assertNotIn('data',answer)
 def test_exception_restores_original_broker_collaborators(self):
  catalogue=Catalogue(terminal());trace=Trace();broker=self.broker.Broker(catalogue=catalogue,trace=trace)
  with self.assertRaisesRegex(RuntimeError,'synthetic base failure'):broker.handle('RAISE_SYNTHETIC')
  self.assertIs(broker.catalogue,catalogue);self.assertIs(broker.trace,trace);self.assertEqual(trace.rows,[])
 def test_imported_base_source_tamper_is_rejected(self):
  p=self.base/'public_catalogue_protocol.py';p.write_bytes(p.read_bytes()+b'\n# synthetic tamper\n')
  with self.assertRaisesRegex(ValueError,'source changed'):self.protocol.load_base_host('_tampered_protocol','public_catalogue_protocol.py')
if __name__=='__main__':unittest.main(verbosity=2)
