"""Install-boundary mock only. No original cmd_run, registration, SDK app or service start."""
from pathlib import Path
from types import SimpleNamespace
import importlib.util,json,tempfile,unittest
spec=importlib.util.spec_from_file_location('cold_wrapper',Path(__file__).with_name('cold_start_marketing_wrapper.py'));host=importlib.util.module_from_spec(spec);spec.loader.exec_module(host)
class ColdStartQA(unittest.TestCase):
 def setUp(self):
  self.order=[];self.install_options=[];self.builds=[];self.transports=[]
  class SDKMind:pass
  self.sdkmind=SDKMind;self.official=SimpleNamespace(Mind=SDKMind)
  outer=self
  class ManagedMind:
   def __init__(self,root,agent,model,toolbox,ctx,roles):
    self.marketing_coordinator=SimpleNamespace(marker='original marketing');self.stock_coordinator=object();self.original_fields=(root,agent,model,toolbox,ctx,roles)
   def loop(self):return 'original loop'
   def deliver(self,event):return event
  self.base=ManagedMind
  def install(official,**options):self.order.append('original_install');self.install_options.append(options);official.Mind=ManagedMind
  self.original=SimpleNamespace(install=install)
  def capture(official,operator):
   self.order.append('capture');self.assertIs(official.Mind,SDKMind);return SimpleNamespace(Mind=SDKMind,run_once='ORIGINAL_RUN_ONCE')
  def transport(toolbox,source,pins,official):
   t=SimpleNamespace(toolbox=toolbox,source=source,pins=pins);self.transports.append(t);return t
  def build(sdk,coordinator,operator,root,agent,model,ctx,**kwargs):
   self.builds.append((sdk,coordinator,root,ctx,kwargs));return SimpleNamespace(original_run_once=sdk.run_once)
  self.glue=SimpleNamespace(capture_original_sdk=capture,PinnedBusinessTransport=transport,build_stage=build)
 def installed(self):
  host.wrap_install(self.original,self.glue,Path('/fixed/source'),{'forge.json':'HASH'})
  self.options={'enable_stock':True,'stock_lines':10,'catalogue_options':{'original':'unchanged'},'forum_operator':host.OP}
  self.original.install(self.official,**self.options)
 def mind(self):
  ctx={'tokens':{},'addresses':{}};box=SimpleNamespace(ctx=ctx,root=host.PROD)
  m=self.official.Mind(host.PROD,{},object(),box,ctx,['shop']);return m,ctx,box
 def test_capture_before_originalinstall(self):
  self.installed();self.assertEqual(self.order,['capture','original_install'])
 def test_originalinstall_skips_only_oldslate(self):
  self.installed();expected={**self.options,'forum_operator':None};self.assertEqual(self.install_options,[expected])
 def test_existing_stock_customer_loop_inherited(self):
  self.installed();m,_,_=self.mind();self.assertIs(type(m).loop,self.base.loop);self.assertIs(type(m).deliver,self.base.deliver);self.assertEqual(m.loop(),'original loop')
 def test_one_originalcoordinator_samectx_transport(self):
  self.installed();m,ctx,box=self.mind();self.assertEqual(len(self.builds),1);args=self.builds[0];self.assertIs(args[1],m.marketing_coordinator);self.assertIs(args[3],ctx);self.assertIs(args[4]['execute'],self.transports[0]);self.assertIs(self.transports[0].toolbox,box);self.assertIs(args[4]['stock'],m.stock_coordinator)
 def test_prejoin_ctx_not_read_or_fabricated(self):
  self.installed();m,ctx,_=self.mind();self.assertNotIn('shop_url',ctx);ctx['shop_url']='https://synthetic.invalid';self.assertEqual(self.builds[0][3]['shop_url'],ctx['shop_url'])
 def test_originalsdkclass_reference_preserved(self):
  self.installed();m,_,_=self.mind();self.assertIs(self.builds[0][0].Mind,self.sdkmind);self.assertEqual(m.official_forum_background.original_run_once,'ORIGINAL_RUN_ONCE')
 def test_construct_and_install_do_not_call_tick_or_startloop(self):
  self.installed();m,_,_=self.mind();self.assertEqual(self.order,['capture','original_install']);self.assertFalse(hasattr(m.official_forum_background,'started'))
 def test_forward_root_and_port_preservation(self):
  args=['run','--operator-dir',str(host.OP),'--agent-root',str(host.PROD),'--owner-file','/home/seop/.config/ourolabs-market/owner-code','--port','18805','--tunnel','--enable-procurement'];host.validate_forward(args)
  with self.assertRaises(ValueError):host.validate_forward([*args,'--port','18807'])
  with self.assertRaises(ValueError):host.validate_forward([v if v!='18805' else '18807' for v in args])
 def test_actual_reviewed_glue_source_admitted_without_businesscall(self):
  glue=host.reviewed_glue();self.assertEqual(glue.SLATE_MANIFEST,host.SLATE_SHA)
if __name__=='__main__':
 result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ColdStartQA))
 Path(__file__).with_name('SAFE-QA.json').write_text(json.dumps({'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'install_lifecycle':'Mock original install; real frozen glue hash admission only','original_cmd_run_or_join_called':False,'actual_Model_or_POST_calls':0,'newloop_or_service_or_taskstore_mutations':0,'migration_or_URL_preservation_proven':False},indent=2));raise SystemExit(not result.wasSuccessful())
