"""HOST control/timeout tests; no market, keys, model or financial DB."""
import asyncio,importlib.util,json,os,sqlite3,sys,tempfile,threading,time,unittest
from pathlib import Path

SOURCE=Path(__file__).resolve().parents[2]/'src/r4_operator_host/seller_marketing_host.py'
spec=importlib.util.spec_from_file_location('seller_marketing_under_test',SOURCE);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
GEN='a'*64;TOKEN='b'*64

class HostTests(unittest.TestCase):
    def fixture(self):
        temporary=tempfile.TemporaryDirectory(prefix='r4-marketing-host-');self.addCleanup(temporary.cleanup);root=Path(temporary.name)
        folder=root/'state/r4-benefits';folder.mkdir(parents=True,mode=0o700);policy=folder/'marketing-owner-policy.json'
        policy.write_text(json.dumps({'schema':'outseop-r4.marketing-owner.v1','active':True,'generation':GEN,'token':TOKEN}));policy.chmod(0o600)
        return root,m.OwnerPolicy(root,GEN),m.JobStore(root/'host/marketing-jobs.sqlite3')
    def test_policy_requires_owned_private_regular_exact_document(self):
        root,policy,_=self.fixture();self.assertTrue(policy.enabled());policy.path.chmod(0o644)
        with self.assertRaises(m.Unavailable):policy.read()
        policy.path.chmod(0o600);value=json.loads(policy.path.read_text());value['extra']=1;policy.path.write_text(json.dumps(value))
        with self.assertRaises(m.Unavailable):policy.read()
    def test_wrong_database_rejected(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup);root=Path(directory.name)
        with self.assertRaises(ValueError):m.JobStore(root/'benefits.sqlite3')
    def test_journal_singleflight_and_finish(self):
        _,_,store=self.fixture();job,recovery=store.claim(GEN);self.assertIsNone(recovery)
        with self.assertRaises(m.Busy):store.claim(GEN)
        store.finish(job,{'status':'nothing_to_reconcile'});next_job,next_recovery=store.claim(GEN)
        self.assertGreater(next_job,job);self.assertIsNone(next_recovery)
    def test_interrupted_worker_enters_recovery_only(self):
        _,policy,store=self.fixture();job,_=store.claim(GEN)
        with sqlite3.connect(store.path) as db:db.execute("UPDATE jobs SET owner_process='99999999:0' WHERE id=?",(job,))
        called=[]
        def cycle(**kwargs):called.append(kwargs);return {'status':'nothing_to_reconcile'}
        controller=m.Controller(policy,store,cycle);controller.run(GEN)
        self.assertTrue(called[0]['recovery_only']);self.assertLessEqual(called[0]['deadline']-time.monotonic(),110)
        with sqlite3.connect(store.path) as db:self.assertEqual(db.execute('SELECT state FROM jobs WHERE id=?',(job,)).fetchone()[0],'reconciled_interruption')
    def test_customer_or_maintenance_blocks_cycle(self):
        _,policy,store=self.fixture();called=[]
        for keywords in [{'customer_active':lambda:True},{'maintenance':lambda:True}]:
            result=m.Controller(policy,store,lambda **x:called.append(x),**keywords).run(GEN)
            self.assertEqual(result['status'],'postponed')
        self.assertEqual(called,[])
    def test_cycle_exception_is_private_sanitized_and_finishes(self):
        _,policy,store=self.fixture()
        def cycle(**kwargs):raise RuntimeError('never publish this secret message')
        result=m.Controller(policy,store,cycle).run(GEN);self.assertEqual(result,{'status':'cycle_unavailable','error_type':'RuntimeError'})
        with sqlite3.connect(store.path) as db:
            value=db.execute('SELECT result FROM jobs').fetchone()[0];self.assertNotIn('secret',value)
    def test_ASGI_auth_exact_generation_and_passthrough(self):
        _,policy,store=self.fixture();calls=[]
        async def original(scope,receive,send):
            await send({'type':'http.response.start','status':204,'headers':[]});await send({'type':'http.response.body','body':b''})
        app=m.HandoffASGI(original,m.Controller(policy,store,lambda **kwargs:(calls.append(kwargs) or {'status':'no_selection'})))
        async def invoke(token=TOKEN,body=None,path=m.IPC_PATH):
            response=[];request=[{'type':'http.request','body':json.dumps(body if body is not None else {'generation':GEN}).encode()}]
            async def receive():return request.pop(0)
            async def send(message):response.append(message)
            await app({'type':'http','method':'POST','path':path,'headers':[(b'authorization',('Bearer '+token).encode())]},receive,send)
            return response[0]['status']
        self.assertEqual(asyncio.run(invoke(token='x'*64)),401);self.assertEqual(calls,[])
        self.assertEqual(asyncio.run(invoke(body={'generation':GEN,'decision':{}})),400);self.assertEqual(calls,[])
        self.assertEqual(asyncio.run(invoke(path='/')),204);self.assertEqual(calls,[])
        self.assertEqual(asyncio.run(invoke()),200);self.assertEqual(len(calls),1)
    def test_worker_deadline_kills_owned_descendants_and_no_late_effect(self):
        directory=tempfile.TemporaryDirectory(prefix='r4-owned-worker-test-');self.addCleanup(directory.cleanup);root=Path(directory.name);late=root/'late.txt'
        child_code='import time;from pathlib import Path;time.sleep(0.8);Path('+repr(str(late))+').write_text("late")'
        parent_code='import subprocess,sys,time;subprocess.Popen([sys.executable,"-c",'+repr(child_code)+']);time.sleep(10)'
        started=time.monotonic();result=m.run_owned([sys.executable,'-c',parent_code],0.15,root)
        self.assertLess(time.monotonic()-started,2);self.assertEqual(result['status'],'marketing_cycle_timeout')
        time.sleep(0.9);self.assertFalse(late.exists())
    def test_model_budget_actual_once_then_declared_synthetic_sleep(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup);calls=[]
        class Model:
            def complete(self,messages,**kwargs):calls.append(kwargs);return '{"action":"sleep","args":{}}'
        model=m.ForumModel(Model(),Path(directory.name),time.monotonic()+2)
        model.complete([]);second=json.loads(model.complete([]));self.assertEqual(len(calls),1);self.assertEqual(second['action'],'sleep');self.assertEqual(model.synthetic_terminal_calls,1)
        self.assertLessEqual(calls[0]['timeout'],2);self.assertLessEqual(calls[0]['max_tokens'],800)

    def test_policy_chmod_during_read_is_rejected(self):
        from unittest.mock import patch
        _,policy,_=self.fixture();original=m.os.fstat;wanted=policy.path.stat().st_ino
        def changed(fd):
            value=original(fd)
            if value.st_ino==wanted:policy.path.chmod(0o644)
            return value
        with patch.object(m.os,'fstat',changed):
            with self.assertRaises(m.Unavailable):policy.read()
    def test_marketing_identity_has_no_financial_grant(self):
        signer=m.IdentityOnlySigner();self.assertIsNone(signer.grant('forum_marketing',{'identity':['shop'],'pay_limit':0},150))
        for permission in [{'wallet':['shop']},{'pay_limit':1},{'exec':['sh']}]:
            with self.assertRaises(m.Unavailable):signer.grant('forum_marketing',permission,150)

if __name__=='__main__':unittest.main()
