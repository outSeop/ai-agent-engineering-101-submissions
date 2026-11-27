import copy
import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path


class World:
    def __init__(self, path, campaign=True):
        self.db_path = Path(path)
        self.wallet = '0x' + '1' * 40
        self.recipient = '0x' + '2' * 40
        self.now = 1795769359
        self.policy = {'campaign_id':'synthetic-v13','starts_at':self.now-120,'ends_at':self.now+3600} if campaign else None
        self.payments = []
        self.quote_requests = 0
        self.stamp = self.now
        self.cash = 1200000 if campaign else 2000000
        self.dues = 600000 if campaign else 0
        self.stock = [{'sku':'G99999999','kind':'goods','unit':'u-999999999999','cost':3000000,'category':'Other'}] if campaign else []
        self.items = {}
        self.events = []
        self.refs = ['c'*64]
        self.excluded = []
        self.expect_audit = True
        self.expire_before_send = False
        self.stale_before_send = False
        self.tx = '0x'+'a'*64
        for sku, name, kind, listed in (('F11111111','Green Tea','food',50000),
                                        ('G22222222','Loose Tea Tin','goods',50000),
                                        ('G33333333','Tea Strainer','goods',50000),
                                        ('G44444444','Steam Kettle','goods',50000)):
            self.items[sku] = {'sku':sku,'name':name,'kind':kind,'category':'Kitchen','list_price':listed,'shelf_hours':12}
            for grade, amount in [('A',40000),('B',6000)]:
                for _ in range(5):
                    seq = len(self.events)+1
                    self.events.append({'seq':seq,'ts':self.now-12,'round':4,'kind':'settle','sku':sku,'grade':grade,
                                        'amount':amount,'shop':'https://public-comparable.example/shop','broken':None,
                                        'sealed':None,'order_ref':f'{seq:064x}'})
        self.quote = self.make_quote('F11111111' if campaign else 'G33333333','A',10000)

    def make_quote(self, sku, grade, cost):
        item = self.items[sku]
        qid = 'q-0123456789abcdef'
        unit = {key:item[key] for key in ('sku','kind','category','list_price')}
        unit.update(unit='u-0123456789ab',grade=grade,cost=cost,
                    expires_at=self.now+10000 if item['kind']=='food' else None)
        total = self.dues+cost
        return {'quote':qid,'goods':cost,'storage':self.dues,'forum_fees':0,'total':total,'expires_in':120,
                'pay':{'to':self.recipient,'wei':str(total),'data':'0x'+hashlib.sha256(qid.encode()).hexdigest()},'units':[unit]}

    def clock(self):
        return self.now

    def gas(self, network):
        return 210

    def read(self, path):
        name = path.name
        if name == 'stock-campaign-policy.json':
            assert path == Path('host_inputs/stock-campaign-policy.json'), path
            if self.policy is None:
                raise FileNotFoundError(name)
            return copy.deepcopy(self.policy)
        if name == 'stock-demand-signals.json':
            return {'round':4,'observed_at':self.stamp,'valid_until':self.stamp+140,
                    'coverage':{'since':self.stamp-3600,'complete':True},'events':copy.deepcopy(self.events)}
        if name == 'stock-demand-exclusions.json':
            return {'round':4,'observed_at':self.stamp,'valid_until':self.stamp+140,'event_refs':list(self.excluded)}
        raise AssertionError(name)

    def rows(self, now):
        return [(ref,None,'tea',now-10,'public_term') for ref in self.refs]

    def snapshot(self):
        return {'balance':self.cash,'bankrupt_line':8334,'units':self.stock,'storage_per_day':.12,
                'storage_due_with_next_lot':self.dues,'next_dislike_fee':0,'surge':[],
                'restock':{'opens_at':self.stamp-10,'closes_at':self.stamp+200,'open':True}}

    def chain(self):
        return 1,100,420,self.recipient

    def catalog(self):
        return self.items

    def supply(self,payload):
        assert payload == {'sku':self.quote['units'][0]['sku'],'qty':1},payload
        self.quote_requests += 1
        return 402,copy.deepcopy(self.quote)

    def rpc(self, method, *args):
        assert method == 'eth_blockNumber'
        if self.expire_before_send:
            self.policy['ends_at'] = self.now
        if self.stale_before_send:
            assert self.quote_requests == 1 and self.now < self.stamp+140
            self.now = self.stamp+140
        return '0x20'

    def get(self,path,params=None):
        assert path == '/api/ledger'
        return []

    def transaction(self,*args):
        return None

    def pay(self,to,wei,marker):
        assert to == self.recipient and wei == self.quote['total'] and marker == self.quote['pay']['data']
        with sqlite3.connect(self.db_path) as db:
            state = db.execute('SELECT state FROM stock_intent ORDER BY created DESC LIMIT 1').fetchone()[0]
            assert state == 'sending'
            audits = db.execute('SELECT detail FROM stock_risk_v13 WHERE intent_id IN '
                                "(SELECT id FROM stock_intent WHERE state='sending')").fetchall()
            if self.expect_audit:
                assert len(audits) == 1
                audit = json.loads(audits[0][0])
                assert audit['full_quote'] == wei and audit['full_cash_outflow'] == wei+210
                assert audit['old_dues_paid'] == self.dues and audit['old_storage_paid'] == self.dues
                assert audit['old_forum_paid'] == audit['new_fees'] == 0
                assert audit['new_goods'] == self.quote['goods'] and audit['acquisition_gas_reserve'] == 210
                assert audit['plan_id'] and audit['intent_id'] and audit['policy']['mode'] in ('campaign','normal')
                if self.policy:
                    assert audit['new_carry'] == 0 and audit['new_risk'] == 10210
            else:
                assert audits == []
        self.payments.append((to,wei,marker))
        return self.tx


def test(run,kit):
    env = run.__globals__
    assert kit.testing
    with tempfile.TemporaryDirectory() as directory:
        def use(name,campaign=True):
            world = World(Path(directory)/(name+'.sqlite3'),campaign)
            env['_TEST_WORLD'] = world
            return world

        def call(action,**args):
            return run(dict(args,action=action),kit)

        def ready(sku,cap=5):
            draft = call('context',line_cap=cap)
            assert draft['status'] == 'draft',draft
            public = draft['context']
            assert type(public['limits']['lines']) is int and public['limits']['lines'] == cap
            assert 'finance' not in public
            selected = next(row for row in public['choices'] if row['sku'] == sku)
            assert set(selected) == {'sku','name','category','kind','list_price','options'},selected
            assert selected['name'] and selected['category'] and selected['list_price'] > 0
            assert selected['options'][0]['qty'] == 1 and selected['options'][0]['scenario']
            result = call('plan',plan=draft['plan'],decision={'action':'buy','lines':[{'sku':sku,'qty':1}], 'reason':'synthetic integration'})
            assert result == {'status':'ready','lines':1},result
            return draft['plan']

        try:
            world = use('raw_settle',False)
            own = env['shop_identity'](kit.shop_url)
            template = world.events[0]
            for amount in (39000,41000,42000,43000,44000,45000,7000,8000):
                seq = len(world.events)+1
                world.events.append(dict(template,seq=seq,amount=amount,order_ref=f'{seq:064x}'))
            assert env['evidence'](world.read,world.now,own)['F11111111'] == {'A':8000,'B':6000}
            world.events[-2]['broken'] = True
            assert env['evidence'](world.read,world.now,own)['F11111111'] == {'A':39000,'B':6000}
            world.events.append(dict(world.events[-1],seq=len(world.events)+1,kind='refund'))
            assert env['evidence'](world.read,world.now,own)['F11111111'] == {'A':40000,'B':6000}

            world = use('campaign')
            ready('F11111111')
            with sqlite3.connect(world.db_path) as db:
                context = json.loads(db.execute('SELECT choices FROM stock_plan').fetchone()[0])
                finance = context['finance']
                assert finance['cash_reserve'] == 700000 and finance['fresh_room'] == 500000,finance
                assert finance['released'] == 630000 and finance['campaign_cap'] == 100000,finance
            q = 610000
            equity_after = 4200000-600000-210
            assert 1200000-q-210 == 589790 and 589790 >= 700000-600000
            assert 80*equity_after < 100*3010000 <= 85*equity_after
            result = call('execute')
            assert result['status'] == 'paid_pending_confirmation' and len(world.payments) == 1,result
            assert call('execute')['status'] == 'unresolved_prior_payment'
            assert call('reconcile')['status'] == 'payment_receipt_pending'
            assert len(world.payments) == 1

            world = use('wrong_grade',False)
            world.quote = world.make_quote('G33333333','B',10000)
            ready('G33333333')
            assert call('execute')['status'] == 'no_purchase'
            assert world.quote_requests == 1 and world.payments == []
            with sqlite3.connect(world.db_path) as db:
                assert db.execute('SELECT count(*) FROM stock_risk_v13').fetchone()[0] == 0

            world = use('normal_valid',False)
            ready('G33333333')
            assert call('execute')['status'] == 'paid_pending_confirmation'
            assert len(world.payments) == 1

            world = use('bad_marker')
            ready('F11111111')
            world.quote['pay']['data'] = '0x'+'0'*64
            assert call('execute')['status'] == 'no_purchase' and not world.payments

            world = use('oversized')
            ready('F11111111')
            world.quote['total'] = 1000001
            assert call('execute')['status'] == 'no_purchase' and not world.payments

            world = use('spent')
            ready('F11111111')
            with sqlite3.connect(world.db_path) as db:
                db.execute('INSERT INTO stock_risk_v13 VALUES(?,?,?,?,?)',
                           ('prior','prior-plan',world.policy['campaign_id'],world.now-50,json.dumps({'new_risk':95000})))
            assert call('execute')['status'] == 'fresh_cash_limit' and not world.payments

            world = use('expired')
            ready('F11111111')
            world.expire_before_send = True
            assert call('execute')['status'] == 'authoritative_check_unavailable' and not world.payments
            with sqlite3.connect(world.db_path) as db:
                assert db.execute('SELECT state FROM stock_intent').fetchone()[0] == 'reserved'
                assert db.execute('SELECT count(*) FROM stock_risk_v13').fetchone()[0] == 0

            for name, campaign, sku in (('stale_campaign',True,'F11111111'),('stale_normal',False,'G33333333')):
                world = use(name,campaign)
                ready(sku)
                world.stale_before_send = True
                result = call('execute')
                assert result['status'] == 'authoritative_check_unavailable',result
                assert world.now == world.stamp+140 and world.quote_requests == 1 and not world.payments
                with sqlite3.connect(world.db_path) as db:
                    assert db.execute('SELECT state FROM stock_intent').fetchone()[0] == 'reserved'
                    assert db.execute('SELECT count(*) FROM stock_risk_v13').fetchone()[0] == 0

            world = use('bad_scope')
            ready('F11111111')
            world.policy['ends_at'] = world.now+21601
            assert call('execute')['status'] == 'authoritative_check_unavailable' and not world.payments

            world = use('term',False)
            picker = env['priorities']
            expected = {'F11111111':1,'G22222222':1,'G33333333':1}
            world.refs *= 2
            assert picker(world.read,world.rows,world.items,world.now) == expected
            draft = call('context',line_cap=2)
            assert [row['sku'] for row in draft['context']['choices']] == ['F11111111','G22222222']
            world.excluded = list(world.refs)
            assert picker(world.read,world.rows,world.items,world.now) == {}
            world.excluded = []
            world.stamp -= 151
            assert picker(world.read,world.rows,world.items,world.now) == {}

            world = use('untagged',False)
            ident = ready('G33333333')
            with sqlite3.connect(world.db_path) as db:
                db.execute('DELETE FROM stock_scope_v13 WHERE plan_id=?',(ident,))
            world.expect_audit = False
            assert call('execute')['status'] == 'paid_pending_confirmation'
            assert len(world.payments) == 1
        finally:
            env.pop('_TEST_WORLD',None)
