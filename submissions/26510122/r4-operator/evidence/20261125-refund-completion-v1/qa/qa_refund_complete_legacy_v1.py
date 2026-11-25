"""Independent synthetic old-schema QA. No production reads, network or payments."""
from contextlib import closing, contextmanager
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json, os, socket, sqlite3, unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch
from legacy_refund_fixture import existing_refund_case, source_contract
import dispatcher as legacy

HERE=Path(__file__).resolve().parent
OUT=HERE/'validation/refund-complete-v1-independent-20261125'
SNAP=OUT/'source'
PIN='6b11e5e3cf16bdbf1e3a178669861017368d8169513de57098904dd35b3c3233'
CASE='a'*64
TX='0x'+'9'*64

def canon(x):
    return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()

def load(name='logic'):
    path=SNAP/(name+'.py'); scope={}
    exec(compile(path.read_bytes(),str(path),'exec'),scope)
    return scope

@contextmanager
def scenario():
    with existing_refund_case() as (f,case), TemporaryDirectory(prefix='r4-confirm-host-') as tmp:
        sid=case['claim']['sale_id']
        with closing(f.open()) as db:
            db.execute("UPDATE refund SET status='pending_unknown',outgoing=? WHERE sale_id=?",(TX,sid)); db.commit()
        host=Path(tmp)/'receipt.sqlite3'
        with sqlite3.connect(host) as h:
            h.execute('CREATE TABLE refund_receipt_confirmation(case_id TEXT PRIMARY KEY,sale_id TEXT,tx TEXT,snapshot TEXT)')
        f.kit.canon=canon
        current=Path.cwd()
        os.chdir(case['root'])
        try:
            with patch.dict(os.environ,{'R4_REFUND_CONFIRMATION_DB':str(host)}):
                def bind(cid=CASE,sale_id=sid,tx=TX):
                    with closing(f.open()) as db:
                        sale=dict(db.execute('SELECT * FROM sale WHERE id=?',(sale_id,)).fetchone())
                        refund=dict(db.execute('SELECT * FROM refund WHERE sale_id=?',(sale_id,)).fetchone())
                    digest=sha256(canon({'purpose':'refund_completion_v1','case_id':cid,'tx':tx,'sale':sale,'refund':refund})).hexdigest()
                    with sqlite3.connect(host) as h:
                        h.execute('INSERT OR REPLACE INTO refund_receipt_confirmation VALUES(?,?,?,?)',(cid,sale_id,tx,digest))
                bind()
                yield SimpleNamespace(f=f,case=case,sid=sid,host=host,bind=bind,run=load()['run'])
        finally: os.chdir(current)

def rows(f,sql,args=()):
    with closing(f.open()) as db: return [tuple(x) for x in db.execute(sql,args)]

def state(f):
    with closing(f.open()) as db:
        return '\n'.join(db.iterdump())

def mutate(s,sql,args=()):
    with closing(s.f.open()) as db: db.execute(sql,args); db.commit()

def clone_sale(s,newid,owner=None,status='settled'):
    with closing(s.f.open()) as db:
        row=dict(db.execute('SELECT * FROM sale WHERE id=?',(s.sid,)).fetchone())
        row.update(id=newid,owner=owner or row['owner'],unit=newid,digest=newid,jwt=newid,spent=0,
                   price=row['base']-row['discount'],status=status,market_order=newid,payment=None,fee_payment=None)
        db.execute('INSERT INTO sale('+','.join(row)+') VALUES('+','.join('?' for _ in row)+')',tuple(row.values())); db.commit()

class CompletionQA(unittest.TestCase):
    def test_manifest_and_original_selftest(self):
        self.assertEqual(sha256((SNAP/'logic.py').read_bytes()).hexdigest(),PIN)
        forge=json.loads((SNAP/'forge.json').read_text())
        self.assertEqual((forge['tool'],forge['version']),('refund_complete_legacy',1))
        for name,digest in forge['sha256'].items(): self.assertEqual(sha256((SNAP/name).read_bytes()).hexdigest(),digest)
        with TemporaryDirectory() as tmp:
            cwd=Path.cwd(); os.chdir(tmp)
            try: load('test')['test'](load()['run'],SimpleNamespace(canon=canon))
            finally: os.chdir(cwd)

    def test_actual_schema_baseline_and_idempotence(self):
        with scenario() as s:
            before=rows(s.f,'SELECT * FROM lot WHERE sale_id<>?',(s.sid,))
            self.assertEqual(s.run({'case_id':CASE},s.f.kit),{'status':'completed'})
            self.assertEqual(rows(s.f,'SELECT status FROM sale WHERE id=?',(s.sid,)),[('refunded',)])
            self.assertEqual(rows(s.f,'SELECT status FROM refund WHERE sale_id=?',(s.sid,)),[('refunded',)])
            self.assertIsNotNone(rows(s.f,'SELECT revoked FROM lot WHERE sale_id=?',(s.sid,))[0][0])
            self.assertEqual(rows(s.f,'SELECT status FROM allocation WHERE sale_id=?',(s.sid,)),[('released',)])
            self.assertEqual(rows(s.f,'SELECT * FROM lot WHERE sale_id<>?',(s.sid,)),before)
            completed=state(s.f)
            self.assertEqual(s.run({'case_id':CASE},s.f.kit),{'status':'completed'})
            self.assertEqual(state(s.f),completed)
            self.assertEqual(s.f.sends,0)

    def test_rejects_caller_flags_without_mutation(self):
        with scenario() as s:
            before=state(s.f)
            for field in ('success','receipt','amount','payee','outgoing','snapshot','verified'):
                with self.subTest(field=field):
                    self.assertEqual(s.run({'case_id':CASE,field:True},s.f.kit)['status'],'invalid_request')
            self.assertEqual(state(s.f),before)

    def test_confirmation_absent(self):
        with scenario() as s:
            before=state(s.f)
            with patch.dict(os.environ,{},clear=True): self.assertEqual(s.run({'case_id':CASE},s.f.kit)['status'],'confirmation_required')
            self.assertEqual(state(s.f),before)

    def test_case_binding(self):
        with scenario() as s:
            with sqlite3.connect(s.host) as h:
                h.execute('UPDATE refund_receipt_confirmation SET case_id=?',('b'*64,))
            self.assertEqual(s.run({'case_id':'b'*64},s.f.kit)['status'],'evidence_mismatch')

    def test_known_outgoing_required(self):
        with scenario() as s:
            mutate(s,'UPDATE refund SET outgoing=NULL'); s.bind()
            self.assertEqual(s.run({'case_id':CASE},s.f.kit)['status'],'known_transfer_required')

    def test_stale_snapshot_rejected(self):
        with scenario() as s:
            mutate(s,'UPDATE refund SET gas_wei=CAST(CAST(gas_wei AS INTEGER)+1 AS TEXT)')
            before=state(s.f)
            self.assertEqual(s.run({'case_id':CASE},s.f.kit)['status'],'evidence_mismatch')
            self.assertEqual(state(s.f),before)

    def test_mismatched_confirmation_tx(self):
        with scenario() as s:
            with sqlite3.connect(s.host) as h: h.execute('UPDATE refund_receipt_confirmation SET tx=?',('0x'+'8'*64,))
            self.assertEqual(s.run({'case_id':CASE},s.f.kit)['status'],'evidence_mismatch')

    def test_identity_mismatch(self):
        with scenario() as s:
            mutate(s,'UPDATE identity SET wallet=?',('0x'+'8'*40,))
            self.assertEqual(s.run({'case_id':CASE},s.f.kit)['status'],'identity_mismatch')

    def test_internal_host_db_rejected(self):
        with scenario() as s:
            internal=Path.cwd()/'untrusted.sqlite3'; internal.write_bytes(s.host.read_bytes())
            with patch.dict(os.environ,{'R4_REFUND_CONFIRMATION_DB':str(internal)}):
                self.assertEqual(s.run({'case_id':CASE},s.f.kit)['status'],'confirmation_required')

    def test_atomic_rollback_each_write_phase(self):
        for table,event in (('lot','UPDATE'),('allocation','UPDATE'),('refund','UPDATE'),('sale','UPDATE'),('refund_completion','INSERT')):
            with self.subTest(table=table),scenario() as s:
                with closing(s.f.open()) as db:
                    if table=='refund_completion': db.execute('CREATE TABLE refund_completion(case_id TEXT PRIMARY KEY,sale_id TEXT NOT NULL UNIQUE,tx TEXT NOT NULL UNIQUE,snapshot TEXT NOT NULL)')
                    db.execute('CREATE TRIGGER inject BEFORE '+event+' ON '+table+" BEGIN SELECT RAISE(ABORT,'injected'); END"); db.commit()
                before=state(s.f)
                self.assertEqual(s.run({'case_id':CASE},s.f.kit)['status'],'completion_blocked')
                self.assertEqual(state(s.f),before)

    def test_two_concurrent_calls_once(self):
        with scenario() as s:
            gate=Barrier(2,timeout=5)
            def call(): gate.wait(); return s.run({'case_id':CASE},s.f.kit)
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures=[pool.submit(call) for _ in range(2)]
                self.assertEqual([x.result() for x in futures],[{'status':'completed'}]*2)
            self.assertEqual(rows(s.f,'SELECT count(*) FROM refund_completion'),[(1,)])

    def test_paid_non_delivery_held_spend_accepted(self):
        with scenario() as s:
            mutate(s,"UPDATE sale SET status='paid' WHERE id=?",(s.sid,))
            mutate(s,"UPDATE refund SET reason='paid_no_delivery'")
            mutate(s,"UPDATE allocation SET status='held' WHERE sale_id=?",(s.sid,)); s.bind()
            self.assertEqual(s.run({'case_id':CASE},s.f.kit)['status'],'completed','OLD_SCHEMA_HELD_ALLOCATION_MUST_COMPLETE')

    def test_consumed_earned_debt_immediately_offset(self):
        with scenario() as s:
            clone_sale(s,'same-owner-later')
            with closing(s.f.open()) as db:
                owner=db.execute('SELECT owner FROM sale WHERE id=?',(s.sid,)).fetchone()[0]
                amount=db.execute('SELECT amount FROM lot WHERE sale_id=?',(s.sid,)).fetchone()[0]
                db.execute("INSERT INTO allocation(sale_id,lot_id,amount,status) VALUES(?,?,?,'spent')",('same-owner-later',s.sid,amount)); db.commit()
            self.assertEqual(s.run({'case_id':CASE},s.f.kit)['status'],'completed')
            with closing(s.f.open()) as db:
                debt=legacy.debt_amount(db,owner)
                self.assertGreater(debt,0)
                before=legacy.balance(db,owner,s.f.now)
                legacy.reallocate_debt(db,owner,s.f.now)
                after=legacy.balance(db,owner,s.f.now)
                self.assertEqual(before,after,'COMPLETION_LEFT_SPENDABLE_POINTS_WITH_UNOFFSET_DEBT')

    def test_promotion_loss_state_refunded_amount_preserved(self):
        with scenario() as s:
            mutate(s,"INSERT INTO promotion_loss VALUES(?,'fixture-policy',7,9,'settled',1)",(s.sid,))
            self.assertEqual(s.run({'case_id':CASE},s.f.kit)['status'],'completed')
            self.assertEqual(rows(s.f,'SELECT reserved,amount FROM promotion_loss'),[(7,9)])
            self.assertEqual(rows(s.f,'SELECT state FROM promotion_loss'),[('refunded',)],'PROMOTION_LIFECYCLE_MUST_RESOLVE_REFUNDED')

    def test_unrelated_customer_and_stock_rows_preserved(self):
        with scenario() as s:
            with closing(s.f.open()) as db: db.execute("INSERT INTO account VALUES('unrelated-owner',1)"); db.commit()
            clone_sale(s,'unrelated-sale','unrelated-owner')
            with closing(s.f.open()) as db:
                db.execute("INSERT INTO lot VALUES('unrelated-sale','unrelated-owner',13,9999999999,NULL)")
                db.execute("INSERT INTO stock_plan VALUES('fixture-window','p','scope',1,2,1,2,'[]',NULL,'planned')")
                db.execute("INSERT INTO stock_intent(id,plan_id,sku,qty,quote,total,marker,recipient,wei,units,tx,chain_anchor,ledger_anchor,state,created,retry_at,delivered) VALUES('synthetic-stock','p','sku',1,'q',1,'m','r','1','[]',NULL,0,0,'unknown',1,0,NULL)"); db.commit()
            qs=[("SELECT * FROM sale WHERE id='unrelated-sale'",()),("SELECT * FROM lot WHERE sale_id='unrelated-sale'",()),('SELECT * FROM stock_intent',())]
            before=[rows(s.f,q,a) for q,a in qs]
            self.assertEqual(s.run({'case_id':CASE},s.f.kit)['status'],'completed')
            self.assertEqual([rows(s.f,q,a) for q,a in qs],before)

    def test_official_toolbox_call_host_confirmation_wired(self):
        import sys, shutil
        kitdir=HERE.parents[3]/'kit'
        sys.path.insert(0,str(kitdir))
        import agent_kit
        with scenario() as s:
            target=Path.cwd()/'tools/refund_complete_legacy'; target.mkdir(parents=True)
            for name in ('logic.py','test.py','forge.json','permission.yml'): shutil.copyfile(SNAP/name,target/name)
            signer=SimpleNamespace(grant=lambda *a:None,revoke=lambda *a:[],url=None)
            ctx={'tokens':{},'addresses':{'shop':s.f.kit.address('shop')},'market':'https://fixture.invalid',
                 'name':s.f.kit.name,'signer':signer,'shop_url':'https://fixture.invalid'}
            toolbox=agent_kit.Toolbox(Path.cwd(),ctx)
            before=state(s.f)
            result=toolbox.run('refund_complete_legacy','call',{'case_id':CASE})
            (OUT/'official-toolbox-call-result.json').write_text(json.dumps(result,indent=2)+'\n')
            self.assertEqual(state(s.f),before)
            self.assertEqual(result,{'ok':True,'result':{'status':'completed'}},'OFFICIAL_TOOLBOX_DROPS_HOST_CONFIRMATION_ENV')

    def test_paid_non_delivery_held_ticket_released(self):
        with scenario() as s:
            with closing(s.f.open()) as db:
                sale=db.execute('SELECT * FROM sale WHERE id=?',(s.sid,)).fetchone()
                db.execute("INSERT INTO ticket VALUES('fixture-ticket',?,?,1,9999999999,0,1,'held')",(sale['sku'],sale['owner']))
                db.execute("UPDATE sale SET status='paid',ticket='fixture-ticket' WHERE id=?",(s.sid,))
                db.execute("UPDATE refund SET reason='paid_no_delivery'"); db.commit()
            s.bind()
            self.assertEqual(s.run({'case_id':CASE},s.f.kit)['status'],'completed')
            self.assertEqual(rows(s.f,"SELECT status FROM ticket WHERE key='fixture-ticket'"),[('released',)],'HELD_TICKET_MUST_RELEASE_ON_NON_DELIVERY_REFUND')

    def test_invalid_allocation_owner_blocks_atomically(self):
        with scenario() as s:
            mutate(s,"INSERT INTO account VALUES('unrelated-owner',1)")
            prior=rows(s.f,'SELECT lot_id FROM allocation WHERE sale_id=?',(s.sid,))[0][0]
            mutate(s,"UPDATE lot SET owner='unrelated-owner' WHERE sale_id=?",(prior,))
            before=state(s.f)
            self.assertEqual(s.run({'case_id':CASE},s.f.kit)['status'],'completion_blocked')
            self.assertEqual(state(s.f),before)

if __name__=='__main__':
    (OUT/'legacy-schema-source-contract.json').write_text(json.dumps(source_contract(HERE),indent=2)+'\n')
    # Block real sockets even if a generated candidate unexpectedly tries network.
    with patch.object(socket.socket,'connect',side_effect=AssertionError('NETWORK_FORBIDDEN')):
        suite=unittest.defaultTestLoader.loadTestsFromTestCase(CompletionQA)
        with (OUT/'unittest-original.log').open('w') as log:
            result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
        report={'source_sha256':PIN,'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
                'failed_tests':[x.id().split('.')[-1] for x,_ in result.failures],
                'error_tests':[x.id().split('.')[-1] for x,_ in result.errors],
                'synthetic_only':True,'real_payments':0,'network_allowed':False,'kit_testing_bypass':False,
                'operational_readiness':False}
        (OUT/'summary.json').write_text(json.dumps(report,indent=2)+'\n'); print(json.dumps(report))
        raise SystemExit(not result.wasSuccessful())
