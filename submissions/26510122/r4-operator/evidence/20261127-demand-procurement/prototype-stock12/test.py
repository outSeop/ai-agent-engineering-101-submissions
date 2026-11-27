from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import json
import sqlite3
import tempfile


NOW=1795768739
WALLET='0x1111111111111111111111111111111111111111'
BANK='0x2222222222222222222222222222222222222222'
SKU='G33333333'
FOOD='F44444444'
TX='0x'+'4'*64
POLICY={'campaign_id':'synthetic-6h','starts_at':NOW-10,'ends_at':NOW+21590}
MODEL_SALE={'sku':SKU,'name':'Synthetic Catalogue Goods','category':'Synthetic > Goods','kind':'goods','list_price':50000,
            'options':[{'qty':1,'scenario':'novel'}]}


class World:
    def __init__(self,root,mode,case,namespace):
        self.root=root
        self.db=root/'synthetic-original.sqlite3'
        self.mode=mode
        self.case=case
        self.namespace=namespace
        self.wallet=WALLET
        self.now=NOW
        self.policy=deepcopy(POLICY) if mode=='campaign' else None
        self.payments=[]
        self.verified_sends=[]
        self.supply_requests=[]
        self.prior_intent=None
        self.chain_terms=None
        self.sku=FOOD if mode=='campaign' else SKU
        self.inv={'round':4,'wallet':WALLET,'balance':1200000,'bankrupt_line':8334,'storage_per_day':.12,
                  'storage_due_with_next_lot':590000 if mode=='campaign' else 0,
                  'next_dislike_fee':10000 if mode=='campaign' else 0,
                  'restock':{'opens_at':NOW-5,'closes_at':NOW+100,'open':True},'surge':[],'units':[]}
        if mode=='campaign':
            self.inv['units']=[{'sku':'G77777777','unit':'u-'+'7'*12,'kind':'goods','category':'Bulk', 'cost':3000000}]
        self.catalog_items={SKU:{'sku':SKU,'name':MODEL_SALE['name'],'kind':'goods','category':MODEL_SALE['category'],'list_price':50000},
                            FOOD:{'sku':FOOD,'name':'Synthetic Catalogue Food','kind':'food','category':'Synthetic > Food','list_price':50000,'shelf_hours':12}}
        self.quote=None

    def configure(self,ns):
        sales=ns['sales']
        buffer=sales.acquisition_network_buffer
        network=next(value for value in range(20001) if buffer(value)==210)
        self.chain_terms=(10**12,100,network,BANK)
        item=self.catalog_items[self.sku]
        amount=10000 if self.case!='oversized' else 1000001
        if self.case=='oversized':
            amount=400001
        storage=self.inv['storage_due_with_next_lot']
        forum=self.inv['next_dislike_fee']
        total=amount+storage+forum
        quote_id='q-'+'a'*16
        marker='0x'+sha256(quote_id.encode()).hexdigest()
        unit={'unit':'u-'+'5'*12,'sku':self.sku,'kind':item['kind'],'category':item['category'],
              'grade':'A','list_price':item['list_price'],'cost':amount,
              'expires_at':NOW+10800 if item['kind']=='food' else None}
        self.quote={'quote':quote_id,'goods':amount,'storage':storage,'forum_fees':forum,'total':total,
                    'expires_in':60,'pay':{'to':BANK,'data':marker,'wei':str(total*self.chain_terms[0])},'units':[unit]}
        if self.case=='inexact_dues':
            self.quote['storage']-=1
            self.quote['total']-=1
            self.quote['pay']['wei']=str(self.quote['total']*self.chain_terms[0])

    def snapshot(self):
        return deepcopy(self.inv)

    def chain(self):
        return self.chain_terms

    def catalog(self):
        return deepcopy(self.catalog_items)

    def supply(self,payload):
        assert payload=={'sku':self.sku,'qty':1},payload
        self.supply_requests.append(payload)
        if self.case=='lower_cap':
            with sqlite3.connect(self.db) as db:
                db.execute('INSERT INTO stock12_risk VALUES(?,?,?,?)',(self.prior_intent,WALLET,POLICY['campaign_id'],90000))
        if self.case=='expired_pre_send':
            self.policy={**POLICY,'ends_at':NOW}
        return 402,deepcopy(self.quote)

    def rpc(self,method,*params):
        assert method=='eth_blockNumber'
        if self.case=='changed_at_arm':
            self.policy={**POLICY,'campaign_id':'other'}
        return '0x20'

    def get(self,path,params=None):
        assert path=='/api/ledger'
        return []

    def transaction(self,tx,sender,recipient,wei,marker):
        assert tx==TX and sender==WALLET and recipient==BANK
        assert wei==int(self.quote['pay']['wei']) and marker==self.quote['pay']['data']
        return None

    def feed(self):
        events=[]
        for index,sku in enumerate((SKU,FOOD)):
            for offset,amount in enumerate((40000,43000,44000,45000,46000,1,2,3)):
                seq=index*10+offset+1
                events.append({'seq':seq,'ts':NOW-20-offset,'round':4,'kind':'settled','sku':sku,'grade':'A','amount':amount,
                               'shop':'HTTPS://SYNTHETIC.SHOP:443/' if offset==5 else 'https://comparable.example/',
                               'broken':True if offset==6 else None,'sealed':True if offset==7 else None,
                               'order_ref':sha256(str(seq).encode()).hexdigest()})
        events.append(deepcopy(events[0]))
        return {'round':4,'observed_at':NOW-10,'valid_until':NOW+100,
                'coverage':{'since':NOW-10-3600,'complete':True},'events':events}

    def inputs(self,name,limit):
        if name=='stock-campaign-policy.json':
            if self.policy is None:
                raise FileNotFoundError(name)
            return deepcopy(self.policy)
        if name=='stock-demand-signals.json':
            return self.feed()
        if name=='stock-demand-exclusions.json':
            return {'round':4,'observed_at':NOW-10,'valid_until':NOW+100,'event_refs':['a'*64]}
        raise AssertionError(name)

    def pay(self,to,wei,data_hex,role):
        assert (to,wei,data_hex,role)==(BANK,int(self.quote['pay']['wei']),self.quote['pay']['data'],'shop')
        with sqlite3.connect(self.db) as db:
            state,quote,amount=db.execute('SELECT state,quote,total FROM stock_intent WHERE quote=?',(self.quote['quote'],)).fetchone()
            assert (state,quote,amount)==('sending',self.quote['quote'],self.quote['total'])
            risk=db.execute('SELECT amount FROM stock12_risk WHERE wallet=?',(WALLET,)).fetchall()
            assert risk==([(10210,)] if self.mode=='campaign' else []),risk
        self.verified_sends.append(state)
        self.payments.append((to,wei,data_hex,role))
        return TX


def test(run,kit):
    env=run.__globals__
    saved={key:env[key] for key in ('read_input','request_path','_TEST_SETUP')}
    try:
        with tempfile.TemporaryDirectory(prefix='stock12-sdk-') as directory:
            root=Path(directory)
            for mode,case,expected in [('normal','valid','paid_pending_confirmation'),
                    ('campaign','valid','paid_pending_confirmation'),('campaign','lower_cap','no_purchase'),
                    ('campaign','oversized','no_purchase'),('campaign','inexact_dues','no_purchase'),
                    ('campaign','malformed_scope','invalid_policy_scope'),('campaign','expired_pre_send','no_purchase'),
                    ('campaign','changed_at_arm','prepayment_policy_recheck_failed'),
                    ('campaign','bad_wallet_scope','no_approved_open_plan')]:
                case_root=root/(mode+'-'+case)
                case_root.mkdir()
                world=World(case_root,mode,case,env)
                recorder=case_root/'requests.sqlite3'
                with sqlite3.connect(recorder) as db:
                    db.execute('CREATE TABLE request(event_hash,sku,term,observed_at,confidence)')
                    if mode=='normal':
                        db.executemany('INSERT INTO request VALUES(?,?,?,?,?)',[
                            ('1'*64,SKU,None,NOW-1,'exact_name'),('2'*64,SKU,None,NOW-1,'exact_sku'),
                            ('3'*64,None,'Synthetic Catalogue Goods',NOW-1,'public_term'),('a'*64,FOOD,None,NOW-1,'exact_sku')])
                    else:
                        db.execute('INSERT INTO request VALUES(?,?,?,?,?)',('1'*64,None,'Synthetic Catalogue Food',NOW-1,'public_term'))
                def setup(ns,synthetic_kit):
                    world.configure(ns)
                    ns['time']=SimpleNamespace(time=lambda:world.now,monotonic=lambda:0)
                    ns['quality']=lambda inv,now:inv['units']
                    return lambda supplied_kit:world,world.db
                env.update(read_input=world.inputs,request_path=lambda:recorder,_TEST_SETUP=setup)
                kit=SimpleNamespace(testing=True,shop_url='https://synthetic.shop',pay=world.pay)
                args={'action':'context','line_cap':1}
                draft=run(args,kit)
                assert draft['status']=='draft',draft
                assert draft['context']['limits']=={'lines':1},draft
                assert set(draft['context'])=={'opens_at','closes_at','limits','choices'}
                choice=draft['context']['choices'][0]
                if mode=='normal':
                    assert draft['context']['choices']==[MODEL_SALE],draft
                    assert env['request_boost'](world.catalog_items,NOW)=={SKU:3}
                else:
                    assert choice=={'sku':FOOD,'name':'Synthetic Catalogue Food','category':'Synthetic > Food',
                                    'kind':'food','list_price':50000,'options':[{'qty':1,'scenario':'novel'}]},choice
                with sqlite3.connect(world.db) as db:
                    assert 'unit' in {row[1] for row in db.execute('PRAGMA table_info(sale)')}
                    assert 'wei' in {row[1] for row in db.execute('PRAGMA table_info(refund)')}
                    assert 'revoked' in {row[1] for row in db.execute('PRAGMA table_info(lot)')}
                    stored=json.loads(db.execute('SELECT choices FROM stock_plan WHERE id=?',(draft['plan'],)).fetchone()[0])
                    if mode=='campaign':
                        finance=stored['finance']
                        assert (finance['equity_at_cost'],finance['cash_reserve'],finance['released'],finance['freshroom'],finance['campaign_cap'],finance['campaign_spent'])==(4200000,700000,630000,500000,100000,0),finance
                        assert 589790>=700000-600000
                        assert 3010000*100<=85*3599790 and 3010000*100>80*3599790
                args={'action':'plan','plan':draft['plan'],'decision':{'action':'buy','lines':[{'sku':choice['sku'],'qty':1}],'reason':'Synthetic integration'}}
                approval=run(args,kit)
                assert approval=={'status':'ready','lines':1},approval
                if case=='lower_cap':
                    world.prior_intent='past-campaign-intent'
                    with sqlite3.connect(world.db) as db:
                        original=db.execute('SELECT * FROM stock_plan WHERE id=?',(draft['plan'],)).fetchone()
                        past=list(original)
                        past[0]='previous-window'
                        past[1]='previous-plan'
                        past[-1]='attempted'
                        db.execute('INSERT INTO stock_plan VALUES(?,?,?,?,?,?,?,?,?,?)',past)
                        db.execute("INSERT INTO stock_intent(id,plan_id,sku,qty,total,state,created) VALUES(?,?,?,?,?,'arrived',?)",
                                   (world.prior_intent,'previous-plan',SKU,1,89790,NOW-900))
                if case=='malformed_scope':
                    world.policy={'campaign_id':POLICY['campaign_id'],'starts_at':NOW-1,'ends_at':NOW+21600}
                if case=='bad_wallet_scope':
                    with sqlite3.connect(world.db) as db:
                        db.execute('UPDATE stock_plan SET scope=? WHERE id=?',(BANK,draft['plan']))
                args={'action':'execute'}
                result=run(args,kit)
                assert result['status']==expected,(mode,case,result)
                assert len(world.payments)==(1 if case=='valid' else 0),(mode,case,world.payments)
                if case in ('malformed_scope','bad_wallet_scope'):
                    assert not world.supply_requests
                if case=='valid':
                    assert world.verified_sends==['sending']
                    assert world.quote['total']==(610000 if mode=='campaign' else 10000)
                    args={'action':'reconcile'}
                    assert run(args,kit)=={'status':'payment_receipt_pending'}
                    assert len(world.payments)==1
    finally:
        env.update(saved)
