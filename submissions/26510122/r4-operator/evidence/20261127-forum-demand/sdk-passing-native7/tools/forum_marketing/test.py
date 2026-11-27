from contextlib import ExitStack, closing
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import httpx


def test(run, kit):
    assert kit.testing
    assert run({'action':'_test_parent'},kit) == {'status':'parent_verified','sha256':'c15424eacded61da86e9f27303b16a705287cecf81c5254a2da5360db3ee9b48'}
    parent = sys.modules['_outseop_r4_pinned_forum_v5']
    shop = parent.shop
    implementation = parent.render_verified.__globals__
    state = Path('state/r4-benefits')
    state.mkdir(parents=True,exist_ok=True)
    wallet = '0xA123456789abcdef123456789abcdef123456789'
    base = 1795780289
    clock = [base]
    sku, short_sku, appliance_sku = 'F12345678','G12345678','F87654321'
    units = [
        {'unit':'fixture-live','sku':sku,'name':'계란 10구','grade':'A','category':'식품 > 계란','expires_at':base+30000,
         'cert':{'cert':{'unit':'fixture-live','sku':sku,'shop':shop.SHOP}}},
        {'unit':'fixture-short','sku':short_sku,'name':'두유 190ml','grade':'B','category':'음료 > 두유','expires_at':base+600,'cert':{'cert':{}}},
        {'unit':'fixture-appliance','sku':appliance_sku,'name':'두유 메이커','grade':'B','category':'가전 > 주방기기','expires_at':base+30000,'cert':{'cert':{}}},
    ]

    def row(ident, ts, text, role='buyer', author='구매자', round_number=4):
        return {'id':ident,'ts':ts,'text':text,'author':author,'role':role,'round':round_number,'thread':None}

    posts = [row(1,base-22000,'이전 문의'),row(5,base-21900,'이전 문의'),
             row(10,base-400,'달걀 10구 A등급 C등급 제외 2,000크레딧 이하 유통기한 2시간 이상 인증서 필수 구해요'),
             row(11,base-399,'계란 10구 구해요'),row(12,base-398,'계란 10구 구해요'),
             row(13,base-397,'계란 10구 구해요',role='shop'),row(14,base-396,'계란 C등급 구해요'),
             row(15,base-395,'계란 A등급 제외 구해요'),row(16,base-394,'계란 30구 구해요'),
             row(17,base-393,'계란 1,999크레딧 이하 구해요'),row(18,base-392,'계란 10구 또는 두유 구해요'),
             row(19,base-391,'계란 알레르기 있어요 계란 구해요'),row(20,base-390,'계란 구해요 후기'),
             row(21,base-389,'계란 유통기한 2일 이상 구해요'),row(22,base-388,'계란 구해요',author=shop.SHOP),
             row(23,base-387,'계란 구해요',round_number=3),row(24,base-386,'계란 10구 x 2 구해요'),
             row(25,base-385,'계란 10구 구해요 환불 문의'),row(26,base-384,'소이밀크 190ml 구해요'),
             row(27,base-383,'두유 구해요'),row(28,base-382,'소이밀크 구해요'),
             row(29,base-381,'계란 총액 2000크레딧 이하 구해요'),row(30,base-380,'계란 말고 구해요')]
    posts.extend(row(1000+idx*2,base-200+idx,'일반 게시물') for idx in range(120))
    posts.extend([row(1240,base-79,'달걀 10구 A등급 구해요'),
                  dict(row(1241,base-78,'계란 10구 구해요'),hidden=True)])
    sends, scans = [], []
    switches = {'timeout':False,'break_scan':False,'fresh':None}

    class FakeMarket:
        def __init__(self, kit):
            assert kit.testing
            self.kit = SimpleNamespace(name=shop.SHOP,address=lambda role: wallet)
            self.wallet = wallet
            self.shop_url = 'https://example.invalid/outseop-r4'

        def chain(self):
            return None,0,'fixture',None

        def inventory(self):
            return units

        def window_page(self, since, limit, deadline):
            scans.append((since,limit))
            if since and limit==100 and switches['break_scan']:
                raise httpx.ReadTimeout('synthetic scan timeout')
            if since==1239 and limit==1 and switches['fresh']:
                return [dict(posts[-2],**switches['fresh'])]
            return posts[-limit:] if since==0 else [post for post in posts if post['id']>since][:limit]

        def forum(self, since=0):
            return self.window_page(since,100,0)

        def post(self, payload):
            sends.append(payload.copy())
            if switches['timeout']:
                raise httpx.ReadTimeout('synthetic publication timeout')
            public = row(posts[-1]['id']+1,clock[0],payload['text'],'shop',shop.SHOP)
            public['thread'] = payload.get('thread')
            posts.append(public)
            return 200,public['id']

    def publish(action, thread=None):
        decision = {'action':action,'sku':sku,'grade':'A'}
        if thread is not None:
            decision['thread'] = thread
        return run({'action':'publish','decision':decision},kit)

    with TemporaryDirectory(prefix='forum-v7-',dir=state) as fixture, ExitStack() as stack:
        path = Path(fixture)/'dispatcher.sqlite'
        policy = Path(fixture)/'first-purchase-bonus-policy.json'
        original_open = parent.open_forum
        stack.enter_context(patch.object(parent,'open_forum',lambda address:original_open(address,path)))
        stack.enter_context(patch.object(shop,'DB',path))
        stack.enter_context(patch.object(parent,'Market',FakeMarket))
        stack.enter_context(patch.object(parent,'time',SimpleNamespace(time=lambda:clock[0])))
        stack.enter_context(patch.dict(implementation,{'POLICY':policy.relative_to(Path.cwd())}))
        stack.enter_context(patch.object(shop,'usable_units',lambda inventory,now:inventory))
        stack.enter_context(patch.object(shop,'price_terms',lambda unit,bps,network:(4000,1000)))
        stack.enter_context(patch.object(shop,'preferred_sale_price',lambda unit,terms,bps,network,launch:2000))
        stack.enter_context(patch.object(shop.price_policy,'current',lambda now:False))
        with closing(original_open(wallet,path)) as db:
            db.execute(implementation['AWARD_DDL'])
            db.commit()

        legacy = run({'action':'context','preset':'conservative'},kit)
        assert legacy['status']=='options' and 'source' not in legacy, legacy
        assert all('spotlight_eligible' not in item and '_base' not in item for item in legacy['items'])
        assert legacy['request_coverage']['complete'] is True
        scans.clear()
        slate = run({'action':'slate_context'},kit)
        assert set(slate)=={'status','source'} and slate['status']=='options', slate
        source = slate['source']
        assert set(source)=={'schema','observed_at','valid_until','spotlight_allowed','own_spotlight_history','items','reply_options'}
        assert source['schema']=='outseop-r4.forum-candidates.v1'
        assert type(source['observed_at']) is type(source['valid_until']) is int
        assert source['observed_at']==base and source['valid_until']==base+90
        assert set(item['sku'] for item in source['items'])=={sku,appliance_sku}
        egg = next(item for item in source['items'] if item['sku']==sku)
        assert egg['certificate'] and egg['spotlight_eligible'] and egg['price']==2000 and '_base' not in egg
        assert {entry['thread'] for entry in source['reply_options']}=={10,11,12,1240}, source
        assert len([call for call in scans if call[0] and call[1]==100])<=30
        switches['break_scan'] = True
        incomplete = run({'action':'slate_context'},kit)['source']
        assert incomplete['spotlight_allowed'] and [entry['thread'] for entry in incomplete['reply_options']]==[1240]
        partial = run({'action':'context'},kit)['request_coverage']
        assert partial['complete'] is False and base-21600<=partial['since']<=base
        assert publish('reply',10)['status']=='no_fresh_matching_request'
        switches['fresh'] = {'text':'계란 10구 A등급 구해요'}
        assert publish('reply',1240)['status']=='no_fresh_matching_request'
        assert (1239,1) in scans
        switches['fresh'] = {'hidden':True}
        assert publish('reply',1240)['status']=='no_fresh_matching_request'
        switches['fresh'] = None
        switches['break_scan'] = False
        assert publish('reply',18)['status']=='no_fresh_matching_request'
        assert publish('reply',13)['status']=='no_fresh_matching_request'
        assert not sends
        assert run({'action':'publish','decision':{'action':'hold','reason':'fixture'}},kit)['status']=='hold'

        policy_data = {'enabled':True,'id':'fixture','start':base-1,'end':base+850,'lifetime_budget':150}
        def save_policy():
            policy.write_text(json.dumps(policy_data),encoding='utf-8')
            policy.chmod(0o600)

        save_policy()
        market = FakeMarket(kit)
        bonus = '첫 구매 추가 5% 적립'
        with closing(original_open(wallet,path)) as db:
            offer = next(item for item in parent.stock_offers(db,market,base) if item['sku']==sku)
            assert offer['_base']==4000 and offer['price']==2000
            render = parent.render_verified
            original = parent.render(implementation['public_offer'](offer),None,market.shop_url,base)
            assert render(db,market,offer,None,base)==original
            policy_data['lifetime_budget'] = 50000
            save_policy()
            assert bonus in render(db,market,offer,None,base)
            market.kit.name = 'different-shop'
            assert render(db,market,offer,None,base)==original
            market.kit.name = shop.SHOP
            market.wallet = '0x'+'a'*40
            assert render(db,market,offer,None,base)==original
            market.wallet = wallet
            policy.chmod(0o666)
            assert render(db,market,offer,None,base)==original
            policy.chmod(0o600)
            secure = implementation['owned_secure']
            with patch.dict(implementation,{'owned_secure':lambda info,directory: directory and secure(info,directory)}):
                assert render(db,market,offer,None,base)==original
            policy_data['extra'] = True
            save_policy()
            assert render(db,market,offer,None,base)==original
            del policy_data['extra']
            save_policy()
            db.execute('SAVEPOINT malformed_award')
            db.execute('DROP TABLE welcome_award')
            db.execute('CREATE TABLE welcome_award(payer TEXT PRIMARY KEY,amount INTEGER NOT NULL)')
            assert render(db,market,offer,None,base)==original
            db.execute('ROLLBACK TO malformed_award')
            db.execute('RELEASE malformed_award')
            db.execute('SAVEPOINT historical_award')
            db.execute('INSERT INTO welcome_award VALUES (?,?,?,?,?)',('0x'+'b'*40,'older-sale',50,base-86400,'prior-event'))
            policy_data['lifetime_budget'] = 249
            save_policy()
            assert render(db,market,offer,None,base)==original
            policy_data['lifetime_budget'] = 250
            save_policy()
            assert bonus in render(db,market,offer,None,base)
            db.execute('ROLLBACK TO historical_award')
            db.execute('RELEASE historical_award')
        policy_data['lifetime_budget'] = 50000
        save_policy()
        first = publish('spotlight')
        assert first['status']=='posted', first
        assert bonus in sends[-1]['text'] and '50,000' in sends[-1]['text'] and 'KST' in sends[-1]['text']
        assert parent.BENEFITS in sends[-1]['text']
        clock[0] += 331
        refreshed = run({'action':'slate_context'},kit)['source']
        assert refreshed['own_spotlight_history']==[{'grade':'A','category':None,'at':base}], refreshed
        assert refreshed['spotlight_allowed'] is False
        assert not next(item for item in refreshed['items'] if item['sku']==sku)['spotlight_eligible']
        assert publish('reply',10)['status']=='posted'
        clock[0] += 331
        assert publish('reply',10)['status']=='no_fresh_matching_request'
        clock[0] += 331
        assert publish('reply',11)['status']=='posted'
        assert bonus not in sends[-1]['text']
        clock[0] += 331
        switches['timeout'] = True
        assert publish('reply',12)['status']=='unknown'
        assert len(sends)==4
        clock[0] += 35
        assert run({'action':'reconcile'},kit)['status']=='unknown'
        assert publish('reply',12)['status']=='unresolved_publish'
        assert len(sends)==4
