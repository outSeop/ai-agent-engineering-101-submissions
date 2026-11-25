"""Synthetic actual-schema support; never uses production DB, wallet or network."""
from pathlib import Path
from hashlib import sha256
from contextlib import closing
from copy import deepcopy
import ast,json,os,sqlite3,sys,time
OP=next(p for p in Path(__file__).resolve().parents if (p/'kit/agent_kit.py').exists())
PROD=OP.parent/'round-4/codex-r4';WORK=OP/'runtime/r3-stock-20261124-204104/agent-work/codex-r4'
sys.path[:0]=[str(PROD),str(WORK),str(OP/'kit')]
from fixture import Fixture,MOCK_SKU,MOCK_MARKET
import dispatcher as legacy
import agent_kit as official


def canonical(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
def wallet(index):return '0x'+format(index,'040x')
def sql_rows(f,sql,args=()):
    with closing(f.open()) as db:return [dict(r) for r in db.execute(sql,args)]

def fingerprint(f,exclude=()):
    with closing(f.open()) as db:
        out={}
        for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            if name in exclude:continue
            rows=[canonical([list(r)]) for r in db.execute('SELECT * FROM "'+name.replace('"','""')+'"')]
            out[name]=sha256(b'\n'.join(sorted(rows))).hexdigest()
        return out


class NoWallet:
    def grant(self,name,permission,timeout):
        if any(permission.get(k) for k in ['network','wallet','exec','handles']):raise AssertionError('unexpected capability')
        return None


class BonusCase:
    def __init__(self,root,source):
        self.root=Path(root);self.root.mkdir(mode=0o700,parents=True)
        self.f=Fixture(self.root,run=legacy.run);self.f.db_path=self.root/'state/r4-benefits/benefits.sqlite3';self.f.now=float(time.time()-7200)
        with closing(self.f.open()) as db:
            text=(PROD/'procurement.py').read_text()
            for n in ast.parse(text).body:
                if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SCHEMA' for t in n.targets):db.executescript(ast.literal_eval(n.value))
        self.policy=self.f.db_path.parent/'first-purchase-bonus-policy.json';self.write_policy()
        target=self.root/'tools/first_purchase_bonus';target.mkdir(parents=True)
        self.pins={}
        for n in ['logic.py','test.py','permission.yml','forge.json']:
            data=(Path(source)/n).read_bytes();(target/n).write_bytes(data);(target/n).chmod(0o400);self.pins[n]=sha256(data).hexdigest()
        forge=json.loads((target/'forge.json').read_bytes())
        assert forge['sha256']=={n:d for n,d in self.pins.items() if n!='forge.json'}
        (self.root/'logs').mkdir();official.mk.LOG_FILE=self.root/'logs/SDK-private.log'
        self.box=official.Toolbox(self.root,{'name':self.f.kit.name,'market':MOCK_MARKET,'tokens':{},'addresses':{},'signer':NoWallet()})
        self.counter=0
    def write_policy(self,**overrides):
        start=int(time.time())-10800
        value={'enabled':True,'id':'synthetic-first-purchase','start':start,'end':start+72*3600,'lifetime_budget':50000};value.update(overrides)
        self.policy.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        if self.policy.exists():self.policy.chmod(0o600)
        self.policy.write_text(json.dumps(value));self.policy.chmod(0o400);return value
    def buy(self,payer=None,*,right=None,price=4500,cost=1200,zero_network=False):
        payer=payer or wallet(1);self.counter+=1;unit='synthetic-bonus-unit-'+str(self.counter)
        self.f.add_unit(unit,price=price,cost=cost)
        if zero_network and not getattr(self,'_zero_network',False):
            original=self.f.get
            def low_chain(url,**kwargs):
                response=original(url,**kwargs)
                if url.endswith('/api/chain'):
                    facts=response.json();facts['network_fee_credits']=0
                    return self.f.response(url,facts)
                return response
            self.f.get=low_chain;self._zero_network=True
        reply=self.f.call({'text':'구매 '+MOCK_SKU+(' 권리 '+right if right else '')})
        if 'data' not in reply or 'checkout_jwt' not in reply['data']:raise AssertionError('original checkout unavailable')
        owner_right=right or self.f.right(reply)
        with closing(self.f.open()) as db:sale=dict(db.execute('SELECT * FROM sale WHERE unit=?',(unit,)).fetchone())
        if zero_network:
            marker='0x'+sale['digest'];payment=self.f.transfer(payer,self.f.kit.address('shop'),int(sale['expected_wei']),marker)
            self.f.receipts[payment]['effectiveGasPrice']='0x0'
            fee=self.f.transfer(payer,sale['fee_wallet'],int(sale['fee_wei']),marker) if int(sale['fee_wei']) else None
            if fee:self.f.receipts[fee]['effectiveGasPrice']='0x0'
            settlement=self.f.settle(reply,buyer=payer,payment=payment,fee=fee)
        else:settlement=self.f.settle(reply,buyer=payer)
        assert self.f.sync()['current']
        self.f.advance(1)
        with closing(self.f.open()) as db:sale=dict(db.execute('SELECT * FROM sale WHERE id=?',(sale['id'],)).fetchone())
        assert sale['status']=='settled' and sale['payer']==payer.lower()
        return {'id':sale['id'],'row':sale,'right':owner_right,'checkout':reply,'settlement':settlement}
    def invoke(self,sale_id,**extra):
        result=self.box.run('first_purchase_bonus','call',{'sale_id':sale_id,**extra})
        if result.get('ok') is not True:raise AssertionError('SDK failed: '+str(result.get('error')))
        return result['result']
    def lot(self,sale_id):
        rows=sql_rows(self.f,'SELECT * FROM lot WHERE sale_id=?',(sale_id,));return rows[0] if rows else None
    def awards(self):
        with closing(self.f.open()) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='welcome_award'").fetchone():return []
            return [dict(x) for x in db.execute('SELECT * FROM welcome_award')]


def complete_synthetic_refund(case,target):
    """Actual generated v3 completion with a closed synthetic host receipt-confirmation DB.
    This tests bookkeeping integration, not real payment/receipt operational authority.
    """
    f=case.f;f.advance(3600);f.breakage(target['settlement'])
    response=f.call({'text':'환불 '+target['row']['payment']+' 권리 '+target['right']})
    assert '검토를 접수' in response['reply']
    outgoing='0x'+'9'*64
    with closing(f.open()) as db:
        db.execute("UPDATE refund SET status='pending_unknown',outgoing=? WHERE sale_id=?",(outgoing,target['id']));db.commit()
        sale=dict(db.execute('SELECT * FROM sale WHERE id=?',(target['id'],)).fetchone())
        claim=dict(db.execute('SELECT * FROM refund WHERE sale_id=?',(target['id'],)).fetchone())
    encoded=json.dumps([f.kit.name,target['id'],claim['requested'],sale['jwt']],ensure_ascii=True,separators=(',',':')).encode('ascii')
    caseid=sha256(b'r4/refund-review/v1\x00'+encoded).hexdigest()
    proof=case.root/'state/r4-benefits/refund-confirmations.sqlite3'
    with closing(sqlite3.connect(proof)) as db:
        db.execute('CREATE TABLE refund_receipt_confirmation(case_id TEXT PRIMARY KEY,sale_id TEXT,tx TEXT,snapshot TEXT)')
        snap=sha256(official.mk.canon({'sale':sale,'refund':claim})).hexdigest()
        db.execute('INSERT INTO refund_receipt_confirmation VALUES(?,?,?,?)',(caseid,target['id'],outgoing,snap));db.commit()
    source=OP/'evidence/20261125-refund-completion-v3/generated/refund_complete_legacy'
    assert sha256((source/'logic.py').read_bytes()).hexdigest()=='6d2c0f9a8237216ff2fa43b7f4bf45739a1779f13eee505115578e1715b0f0e6'
    dest=case.root/'tools/refund_complete_legacy';dest.mkdir()
    for name in ['logic.py','permission.yml','test.py','forge.json']:(dest/name).write_bytes((source/name).read_bytes())
    # Synthetic identity address only; no wallet key or authentication token.
    refund_box=official.Toolbox(case.root,{'name':f.kit.name,'market':MOCK_MARKET,'tokens':{},'addresses':{'shop':f.kit.address('shop')},'signer':NoWallet()})
    envelope=refund_box.run('refund_complete_legacy','call',{'case_id':caseid})
    assert envelope.get('ok') is True
    return envelope['result']
