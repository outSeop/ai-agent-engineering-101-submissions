"""Independent ordinary-SDK QA, original synthetic legacy settlement schema only."""
from first_purchase_bonus_qa_support import *
from concurrent.futures import ThreadPoolExecutor
import traceback
OUT=Path(os.environ['BONUS_QA_ROOT']).resolve();OUT.mkdir(parents=True,exist_ok=False)
SOURCE=Path(__file__).parent/'source';RESULT=[]
def new(name):return BonusCase(OUT/('case-'+name),SOURCE)
def change(c,sql,args=()):
    with closing(c.f.open()) as db:db.execute(sql,args);db.commit()
def status(c,t):return c.invoke(t['id'])['status']
def run(name,fn):
    try:fn();RESULT.append({'case':name,'pass':True})
    except Exception as e:
        RESULT.append({'case':name,'pass':False,'error_type':type(e).__name__});traceback.print_exc()
    print(json.dumps(RESULT[-1]),flush=True)
def first():
    c=new('first');t=c.buy();before=fingerprint(c.f,('lot',));lot=c.lot(t['id']);assert type(t['row']['settled']) is float and type(lot['expires']) is float
    assert status(c,t)=='granted';assert c.lot(t['id'])['amount']==270 and c.lot(t['id'])['expires']==lot['expires'];assert fingerprint(c.f,('lot','welcome_award'))==before
    assert status(c,t)=='already_awarded';c.write_policy(id='renamed');other=c.buy(payer=wallet(1));assert status(c,other)=='already_awarded' and len(c.awards())==1
    assert c.invoke(other['id'],payer=wallet(2),settled=True,amount=999)['status']=='invalid_args'
def history(mode):
    c=new('history-'+mode);a=c.buy();b=c.buy()
    if mode=='missing':change(c,"DELETE FROM event WHERE kind='settled_and_earned' AND reference=?",(a['id'],))
    else:change(c,"UPDATE event SET details=? WHERE kind='settled_and_earned' AND reference=?",(json.dumps({'order':'contradictory','earned':45}),a['id']))
    before=fingerprint(c.f);assert status(c,b)=='unverified_history';assert fingerprint(c.f)==before
def returner():
    c=new('returner');a=c.buy();c.write_policy(start=a['row']['settled']+0.5,end=a['row']['settled']+0.5+72*3600);b=c.buy();assert status(c,b)=='ineligible'
def never_settled():
    c=new('never-settled');a=c.buy();b=c.buy();change(c,"DELETE FROM event WHERE kind='settled_and_earned' AND reference=?",(a['id'],));change(c,"UPDATE sale SET status='refunded',settled=NULL WHERE id=?",(a['id'],));assert status(c,b)=='granted'
def policy():
    c=new('policy');t=c.buy();before=fingerprint(c.f)
    c.policy.unlink();assert status(c,t)=='inactive'
    c.write_policy(enabled=False);assert status(c,t)=='inactive'
    c.write_policy(start=t['row']['settled']-72*3600-2,end=t['row']['settled']-2);assert status(c,t)=='ineligible'
    c.write_policy();change(c,'UPDATE sale SET settled=settled-? WHERE id=?',(8*86400,t['id']));assert status(c,t)=='ineligible'
    assert len(c.awards())==0

def floor():
    c=new('floor');t=c.buy(price=20,cost=0,zero_network=True);assert t['row']['base']==20 and c.lot(t['id']) is None
    assert status(c,t)=='granted';assert c.lot(t['id'])['amount']==1 and c.lot(t['id'])['expires']==t['row']['settled']+604800

def fifo():
    c=new('fifo');a=c.buy();b=c.buy(payer=wallet(2));assert status(c,b)=='defer';assert status(c,a)=='granted';assert status(c,b)=='granted'
def budget():
    c=new('budget')
    for i in range(1,10):
        t=c.buy(payer=wallet(i),price=100000,cost=1000);assert status(c,t)=='granted';assert c.awards()[-1]['amount']==5000
    a=c.buy(payer=wallet(10),price=100000,cost=1000);b=c.buy(payer=wallet(11),price=100000,cost=1000)
    with ThreadPoolExecutor(2) as pool:out=list(pool.map(lambda t:status(c,t),[a,b]))
    if out[1]=='defer':out[1]=status(c,b)
    assert out==['granted','budget_exhausted'];assert sum(x['amount'] for x in c.awards())==50000
    c.write_policy(id='new-campaign');assert status(c,b)=='budget_exhausted'
    d=new('partial-budget');t=d.buy();d.write_policy(lifetime_budget=224);assert status(d,t)=='budget_exhausted' and len(d.awards())==0 and d.lot(t['id'])['amount']==45

def duplicate_race():
    c=new('duplicate-race');t=c.buy()
    with ThreadPoolExecutor(4) as pool:r=list(pool.map(lambda _:status(c,t),range(4)))
    assert r.count('granted')==1 and r.count('already_awarded')==3 and len(c.awards())==1 and c.lot(t['id'])['amount']==270

def policy_race():
    c=new('policy-race');t=c.buy();db=c.f.open();db.execute('BEGIN IMMEDIATE');info=c.policy.stat();os.utime(c.policy,ns=(1,info.st_mtime_ns))
    with ThreadPoolExecutor(1) as pool:
        future=pool.submit(status,c,t);deadline=time.monotonic()+3
        while c.policy.stat().st_atime_ns==1 and time.monotonic()<deadline:time.sleep(.01)
        assert c.policy.stat().st_atime_ns>1;time.sleep(.15);c.policy.unlink();db.rollback();db.close();assert future.result()=='inactive'
    assert len(c.awards())==0 and c.lot(t['id'])['amount']==45

def rollback():
    c=new('rollback');t=c.buy();module={};exec((SOURCE/'logic.py').read_text(),module)
    with closing(c.f.open()) as db:
        db.execute(module['AWARD_SCHEMA']);db.execute("CREATE TRIGGER synthetic_abort BEFORE INSERT ON welcome_award BEGIN SELECT RAISE(ABORT,'synthetic test');END");db.commit()
    before=fingerprint(c.f);assert status(c,t)=='unavailable';assert fingerprint(c.f)==before

def refund():
    c=new('refund-second');a=c.buy();assert status(c,a)=='granted';second=c.buy(right=a['right']);b=c.buy(payer=wallet(2));assert status(c,b)=='granted';other=c.lot(b['id']).copy();awards=deepcopy(c.awards())
    assert sql_rows(c.f,"SELECT SUM(amount) n FROM allocation WHERE lot_id=? AND status='spent'",(a['id'],))[0]['n']==270
    result=complete_synthetic_refund(c,a);assert result['status']=='completed';assert c.lot(a['id'])['revoked'] is not None;assert c.lot(b['id'])==other;assert c.awards()==awards
    with closing(c.f.open()) as db:
        owner=a['row']['owner'];assert legacy.debt_amount(db,owner)==270;assert legacy.balance(db,owner,c.f.now)==0
        assert legacy.reallocate_debt(db,owner,c.f.now)==225;db.commit()
    assert status(c,a)=='already_awarded';later=c.buy(right=a['right']);assert status(c,later)=='already_awarded'

if __name__=='__main__':
    for name,fn in [('first-real-expiry-idempotence',first),('missing-prior-proof',lambda:history('missing')),('contradictory-prior-proof',lambda:history('contradictory')),('prepolicy-returner',returner),('never-settled-refund',never_settled),('inactive-expired-policy-lot',policy),('no-base-lot-floor',floor),('event-order',fifo),('global-budget-concurrency-cap',budget),('duplicate-concurrency',duplicate_race),('afterlock-policy-revoke',policy_race),('atomic-rollback',rollback),('full-lot-refund-debt-unrelated-owner',refund)]:run(name,fn)
    result={'method':'ordinary official Toolbox.run; original tracked dispatcher/Fixture; synthetic only','source_pins':{n:sha256((SOURCE/n).read_bytes()).hexdigest() for n in ['logic.py','test.py','permission.yml','forge.json']},'total':len(RESULT),'passed':sum(x['pass'] for x in RESULT),'cases':RESULT,'financial_real_calls':0,'model_calls':0,'production_modified':False,'manual_testing_flag':False,'refund_proof':'synthetic closed host confirmation; bookkeeping only, not operational receipt authority'}
    (OUT/'safe-results.json').write_text(json.dumps(result,indent=2));print(json.dumps({'total':result['total'],'passed':result['passed']}))
