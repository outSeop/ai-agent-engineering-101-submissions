"""Apply3/refresh2 independent integration. All roots/choices/facts are synthetic."""
from copy import deepcopy
from hashlib import sha256
import json,os,sys,time,unittest
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

HERE=Path(__file__).resolve().parent;OP=next(p for p in HERE.parents if (p/'kit/agent_kit.py').exists())
WORK=OP/'deploy/self_forge_validation/card_transition'
sys.path[:0]=[str(HERE),str(OP/'deploy/native_card_keeper_v1'),str(WORK),str(OP/'kit')]
import agent_kit as official
import card_apply_canary_host as infrastructure
from card_apply_authority_host import StageOrigin,normalized_fresh
from card_apply_v2_inputs import make_authority
from card_offer_producer_host import produce_view

OUT=HERE/'fixtures/card-renewal-apply3-independent-20261125'
SOURCE_REFS=json.loads((OUT/'source-references.json').read_text())
BUNDLES=json.loads((OUT/'snapshot-manifest.json').read_text())
STAGE_PIN=BUNDLES['tools/stage_representative_card']['sha256']['logic.py']
REFRESH_PIN=BUNDLES['tools/refresh_representative_card']['sha256']['logic.py']
METRICS={}
class NoWallet:
    def grant(self,name,perm,timeout):
        if name not in ('stage_representative_card','refresh_representative_card','apply_staged_card','publish_shop_info') or any(perm.get(k) for k in ('wallet','identity','network','exec','handles')):raise PermissionError('No capabilities')
        return None

def encode(value):return infrastructure.encode(value)
def sha(raw):return sha256(raw).hexdigest()
@contextmanager
def cwd(path):
    previous=Path.cwd();os.chdir(path)
    try:yield
    finally:os.chdir(previous)

class RenewalIntegrationQA(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory(prefix='r4-renewal-apply3-');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        for path in ('host_inputs','card_update_stage','card_publication'):(self.root/path).mkdir(mode=0o700)
        (self.root/'card_publication/lock').touch(mode=0o600)
        for relative,record in BUNDLES.items():
            target=self.root/relative;target.mkdir(parents=True)
            for name,pin in record['sha256'].items():
                raw=(OP/SOURCE_REFS[record['snapshot']]/name).read_bytes();self.assertEqual(sha(raw),pin);(target/name).write_bytes(raw)
        self.policies={'mileage':'합성 적립 약속','wait':'합성 대기 약속','refund':'합성 검토 약속'}
        card={'name':'outseop-r4','description':'보존할 소개\nold offers\n보존할 구매 안내','skills':[
          {'id':'a2a-checkout','description':'합성 구매 안내'}, {'id':'repeat-benefits','description':'합성 적립 약속. 합성 대기 약속.'},{'id':'refund-review','description':'합성 검토 약속.'}]}
        self.original=encode(card);(self.root/'card.json').write_bytes(self.original)
        self.now0=int(time.time());self.product_expiry=self.now0+3600
        offers=[{'sku':f'F{i+1:08x}','grade':g,'price':5100+i,'expiry':self.product_expiry} for i,g in enumerate(('A','B','C'))]
        catalog=[{'sku':x['sku'],'name':f'합성 상품 {i}','category':'합성>검증'} for i,x in enumerate(offers)]
        view=produce_view(self.original,'old offers',offers,catalog,self.now0)
        view['valid_until']=self.now0+7
        for row in view['offers']:row['valid_until']=view['valid_until']
        self.selection=[offers[2]['sku'],offers[0]['sku'],offers[1]['sku']]
        self.toolbox=official.Toolbox(self.root,{'name':'outseop-r4','market':'https://fixture.invalid','tokens':{},'addresses':{},'signer':NoWallet()})
        origin,old,fresh=self.stage(view,self.selection,first=True)
        result=self.apply(origin,old,fresh)
        self.assertEqual(result['status'],'applied')
        self.first_id,self.first_event=infrastructure.committed(self.root,result['event'])
        self.initial_description=json.loads(self.first_event['after_card_json'])['description']
        self.retained=self.initial_description[self.first_event['block']['end']:]

    def call(self,name,args):
        envelope=self.toolbox.call(name,args);self.assertTrue(envelope.get('ok'),envelope.get('error'));return envelope['result']
    def clock(self):return int(time.time())
    def advance_after_stage(self,origin,observed):
        target=max(observed+1,(origin.mtime_ns+999999999)//10**9)
        while int(time.time())<target:time.sleep(.015)
        return int(time.time())
    def stage(self,view,selection=None,first=False,scopes=None,clock=None):
        raw=encode(view);infrastructure.atomic_host(self.root/'host_inputs/card_offer_context.json',raw)
        start=time.time_ns();name='stage_representative_card' if first else 'refresh_representative_card'
        args={'op':'stage','skus':selection,'view_sha256':sha(raw)} if first else {'view_sha256':sha(raw)}
        answer=self.call(name,args) if scopes is None else scopes[name]['run'](args,None)
        self.assertEqual(answer['status'],'staged',answer)
        origin=StageOrigin.capture(self.root/'card_update_stage',answer,raw,STAGE_PIN if first else REFRESH_PIN,start,selection or self.selection)
        if clock is None:fresh_at=self.advance_after_stage(origin,view['observed_at'])
        else:
            clock[0]=max(view['observed_at']+1,(origin.mtime_ns+999999999)//10**9);fresh_at=clock[0]
        fresh=deepcopy(view);fresh['observed_at']=fresh_at
        before=(self.root/'card.json').read_bytes()
        validated=normalized_fresh(origin,raw,fresh,before,fresh_at*10**9)
        return origin,raw,encode(validated)
    def context(self,event,stamp):
        prior=json.loads((self.root/'host_inputs/card_offer_original'/(event['view_sha256']+'.json')).read_bytes())
        result={**prior,'offers':[dict(row,valid_until=stamp+150) for row in prior['offers']],
          'observed_at':stamp,'valid_until':stamp+150,'card_sha256':event['after_sha256'],'replace_text':event['block']['text']}
        return result
    def authority(self,origin,old,fresh,now):
        before=(self.root/'card.json').read_bytes();head=infrastructure.head(self.root);record=json.loads(origin.record_raw)
        if origin.source_sha256==STAGE_PIN:return make_authority(origin,old,fresh,before,self.policies,head,now)
        self.assertEqual(origin.source_sha256,REFRESH_PIN)
        _,event=infrastructure.committed(self.root);oldtext=json.loads(before)['description'];newtext=json.loads(record['after_card_json'])['description']
        span=event['block'];prefix=oldtext[:span['start']];suffix=oldtext[span['end']:]
        self.assertTrue(newtext.startswith(prefix));self.assertTrue(newtext.endswith(suffix) if suffix else True)
        block=newtext[len(prefix):len(newtext)-len(suffix) if suffix else None]
        return {'schema':'outseop-r4.card-publication-authority.v1','shop':'outseop-r4','owner':'native','op':'apply','record_id':origin.record_id,'head':head,
          'before_sha256':sha(before),'after_sha256':record['after_sha256'],'issued_at':now,'valid_until':min(now+30,record['valid_until'],json.loads(old)['valid_until'],json.loads(fresh)['valid_until']),
          'details':{'fresh_view_sha256':sha(fresh),'replacement_sha256':sha(block.encode()),'policies':self.policies}}
    def issue(self,origin,old,fresh,now,changes=None):
        authority=self.authority(origin,old,fresh,now)
        if changes:authority.update(changes)
        with infrastructure.exclusive(self.root):
            infrastructure.immutable(self.root/'host_inputs/card_offer_original'/(sha(old)+'.json'),old)
            infrastructure.immutable(self.root/'host_inputs/card_offer_fresh'/(sha(fresh)+'.json'),fresh)
            infrastructure.atomic_host(self.root/'host_inputs/card_publication_authority.json',encode(authority))
        return authority
    def handoff(self,result,scopes=None,clock=None):
        event_id,event=infrastructure.committed(self.root,result['event']);stamp=self.clock() if clock is None else clock[0]
        body={'schema':'outseop-r4.card-publication-handoff.v1','shop':'outseop-r4','owner':'native','event':event_id,'card_sha256':event['after_sha256'],'issued_at':stamp,'valid_until':min(stamp+100,event['offer_until']) if event['offer_until'] is not None else stamp+100}
        with infrastructure.exclusive(self.root):infrastructure.atomic_host(self.root/'host_inputs/card_publication_handoff.json',encode(body))
        guard=self.call('publish_shop_info',{}) if scopes is None else scopes['publish_shop_info']['run']({},None)
        self.assertEqual(guard['status'],'skipped',guard);return event
    def apply(self,origin,old,fresh,scopes=None,clock=None):
        self.issue(origin,old,fresh,self.clock() if clock is None else clock[0]);args={'op':'apply','record_id':origin.record_id}
        result=self.call('apply_staged_card',args) if scopes is None else scopes['apply_staged_card']['run'](args,None)
        self.assertEqual(result['status'],'applied',result);self.handoff(result,scopes,clock);return result
    def scopes(self,clock):
        result={}
        for name in ('refresh_representative_card','apply_staged_card','publish_shop_info'):
            path=self.root/'tools'/name/'logic.py';scope={'__file__':str(path),'__name__':'synthetic_exact_source'}
            with cwd(self.root):exec(compile(path.read_bytes(),str(path),'exec'),scope)
            scope['ROOT']=self.root
            if name=='apply_staged_card':scope['now']=lambda:clock[0]
            else:scope['time']=SimpleNamespace(time=lambda:clock[0])
            if name=='refresh_representative_card':scope['SOURCE']=self.root/'tools/stage_representative_card/logic.py'
            result[name]=scope
        return result

    def test_actual_clock_old_ttl_past_refresh2_apply3_guard(self):
        while int(time.time())<=self.first_event['offer_until']:time.sleep(.02)
        stamp=int(time.time());view=self.context(self.first_event,stamp)
        origin,old,fresh=self.stage(view)
        result=self.apply(origin,old,fresh);_,event=infrastructure.committed(self.root,result['event'])
        self.assertEqual(event['parent'],self.first_id);self.assertEqual(event['skus'],self.selection)
        self.assertGreater(event['offer_until'],self.first_event['offer_until']);self.assertLessEqual(event['offer_until'],self.product_expiry)
        text=json.loads(event['after_card_json'])['description'];self.assertEqual(len(text),len(self.initial_description));self.assertEqual(text[event['block']['end']:],self.retained)
        METRICS['actual_clock_end_to_end']={'ordinary_toolbox_call':True,'old_ttl_expired':True,'new_origin':True,'apply3_status':'applied','head_non_none':True,'guard':'skipped','selection_order_preserved':True,'outside_text_unchanged':True,'deadline_extended':True}

    def test_controlled_35_complete_native_renewals_keep_length_and_surroundings(self):
        clock=[self.first_event['offer_until']+1];scopes=self.scopes(clock);event=self.first_event;lengths=[]
        for count in range(35):
            clock[0]=max(clock[0],event['recorded_at']+1);view=self.context(event,clock[0])
            origin,old,fresh=self.stage(view,scopes=scopes,clock=clock);answer=self.apply(origin,old,fresh,scopes,clock)
            _,event=infrastructure.committed(self.root,answer['event']);text=json.loads(event['after_card_json'])['description'];lengths.append(len(text))
            self.assertEqual(event['skus'],self.selection);self.assertEqual(text[event['block']['end']:],self.retained);self.assertLessEqual(event['offer_until'],self.product_expiry)
            clock[0]+=1
        self.assertEqual(set(lengths),{len(self.initial_description)})
        METRICS['controlled_35_full_apply_cycles']={'cycles':35,'length_unique_count':len(set(lengths)),'outside_text_unchanged':True,'guard_skipped_each_cycle':True,'actual_expiry_never_extended':True,'clock':'controlled exact-source stage+apply+guard, not live publications'}

    def test_changes_to_product_terms_stock_or_expiry_are_rejected(self):
        clock=[self.first_event['recorded_at']+1];scopes=self.scopes(clock);view=self.context(self.first_event,clock[0]);before=(self.root/'card.json').read_bytes()
        outcomes={}
        for field,value in (('price_credits',9999),('grade','C'),('expires_at',self.product_expiry+1),('state','reserved'),('sku','F00000009')):
            changed=deepcopy(view);changed['offers'][0][field]=value;raw=encode(changed);infrastructure.atomic_host(self.root/'host_inputs/card_offer_context.json',raw)
            answer=scopes['refresh_representative_card']['run']({'view_sha256':sha(raw)},None)
            self.assertEqual(answer['status'],'rejected');outcomes[field]=answer.get('error')
        self.assertEqual((self.root/'card.json').read_bytes(),before)
        origin,old,fresh=self.stage(view,scopes=scopes,clock=clock)
        bad=json.loads(fresh);bad['offers'][0]['expires_at']=self.product_expiry+1;badraw=encode(bad)
        self.issue(origin,old,badraw,clock[0]);answer=scopes['apply_staged_card']['run']({'op':'apply','record_id':origin.record_id},None)
        self.assertEqual(answer['status'],'rejected');self.assertEqual((self.root/'card.json').read_bytes(),before)
        METRICS['changed_facts_rejection']=outcomes

    def test_expired_authority_and_head_mismatch_leave_card_and_head(self):
        clock=[self.first_event['recorded_at']+1];scopes=self.scopes(clock);origin,old,fresh=self.stage(self.context(self.first_event,clock[0]),scopes=scopes,clock=clock)
        before=(self.root/'card.json').read_bytes();headraw=(self.root/'card_publication/head.json').read_bytes();codes=[]
        for changes in ({'issued_at':clock[0]-30,'valid_until':clock[0]},{'head':'f'*64}):
            self.issue(origin,old,fresh,clock[0],changes);answer=scopes['apply_staged_card']['run']({'op':'apply','record_id':origin.record_id},None)
            self.assertEqual(answer['status'],'rejected');codes.append(answer.get('reason'));self.assertEqual((self.root/'card.json').read_bytes(),before);self.assertEqual((self.root/'card_publication/head.json').read_bytes(),headraw)
        METRICS['authority_gates']=codes

    def test_rollback_after_second_apply_and_guard(self):
        clock=[self.first_event['recorded_at']+1];scopes=self.scopes(clock);origin,old,fresh=self.stage(self.context(self.first_event,clock[0]),scopes=scopes,clock=clock)
        applied=self.apply(origin,old,fresh,scopes,clock);_,active=infrastructure.committed(self.root,applied['event'])
        authority={'schema':'outseop-r4.card-publication-authority.v1','shop':'outseop-r4','owner':'native','op':'rollback','record_id':applied['event'],'head':applied['event'],
         'before_sha256':active['after_sha256'],'after_sha256':active['before_sha256'],'issued_at':clock[0],'valid_until':clock[0]+25,'details':{}}
        infrastructure.atomic_host(self.root/'host_inputs/card_publication_authority.json',encode(authority));request={'op':'rollback','record_id':applied['event']}
        answer=scopes['apply_staged_card']['run'](request,None);self.assertEqual(answer['status'],'rolled_back',answer);self.handoff(answer,scopes,clock)
        self.assertEqual((self.root/'card.json').read_bytes(),self.first_event['after_card_json'].encode());self.assertEqual(scopes['apply_staged_card']['run'](request,None)['status'],'already_rolled_back')
        METRICS['rollback']={'status':'rolled_back','guard':'skipped','restored_exact_previous_card':True,'idempotent':True}

    def test_new_sku_or_reordered_selection_safely_rejected(self):
        clock=[self.first_event['recorded_at']+1];scopes=self.scopes(clock);view=self.context(self.first_event,clock[0]);extra=dict(view['offers'][0],sku='F00000009',name='추가 합성 상품');view['offers'].append(extra)
        before=(self.root/'card.json').read_bytes();codes=[]
        for selection in (['F00000009'],list(reversed(self.selection))):
            # New genuine stage is synthetic selection only; no class decision is claimed.
            clock[0]+=1;view['observed_at']=clock[0];view['valid_until']=clock[0]+150
            for row in view['offers']:row['valid_until']=view['valid_until']
            stage_scope={};path=self.root/'tools/stage_representative_card/logic.py';exec(compile(path.read_bytes(),str(path),'exec'),stage_scope)
            stage_scope.update(ROOT=self.root,CARD=self.root/'card.json',CONTEXT=self.root/'host_inputs/card_offer_context.json',STAGE=self.root/'card_update_stage',time=SimpleNamespace(time=lambda:clock[0]))
            local={**scopes,'stage_representative_card':stage_scope}
            origin,old,fresh=self.stage(view,selection,first=True,scopes=local,clock=clock)
            self.issue(origin,old,fresh,clock[0]);answer=scopes['apply_staged_card']['run']({'op':'apply','record_id':origin.record_id},None)
            self.assertEqual(answer['status'],'rejected');codes.append(answer.get('reason'));self.assertEqual((self.root/'card.json').read_bytes(),before)
        METRICS['reselection_limit']={'status':'safe_rejection','reasons':codes,'data_corruption':False,'fresh_class_reselection_apply_supported':False}

    def test_original_apply3_official_selftest(self):
        answer=self.toolbox.run('apply_staged_card','test');self.assertTrue(answer.get('ok'),answer.get('error'))

if __name__=='__main__':
    with patch.object(official,'log'),patch.object(official.maroo.Wallet,'load',side_effect=AssertionError('KEY_LOAD_FORBIDDEN')),patch.object(official.maroo,'pay',side_effect=AssertionError('PAY_FORBIDDEN')),(OUT/'unittest-original.log').open('w') as log:
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RenewalIntegrationQA))
    report={'apply3_logic_sha256':BUNDLES['tools/apply_staged_card']['sha256']['logic.py'],'refresh2_logic_sha256':REFRESH_PIN,'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'failed_tests':[test.id().split('.')[-1] for test,_ in result.failures+result.errors],
      'metrics':METRICS,'actual_clock_vs_controlled_clock_explicit':True,'business_source_modified':False,'production_files_or_data_accessed':False,'wallet_or_model_calls':False,'manual_testing_flags':False,'live_installed':False}
    (OUT/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report));raise SystemExit(not result.wasSuccessful())
