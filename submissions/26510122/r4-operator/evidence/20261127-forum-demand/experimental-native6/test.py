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
    state = Path('state/r4-benefits')
    state.mkdir(parents=True,exist_ok=True)
    wallet = '0xF37173b89fc9da7AA3f42fCF839E7cd611548f38'
    base = 1795780289
    clock = [base]
    sku, short_sku = 'F12345678','G12345678'
    units = [
        {'unit':'fixture-live','sku':sku,'name':'계란 10구','grade':'A','category':'식품 > 계란','expires_at':base+30000,
         'cert':{'cert':{'unit':'fixture-live','sku':sku,'shop':shop.SHOP}}},
        {'unit':'fixture-short','sku':short_sku,'name':'두유 190ml','grade':'B','category':'음료 > 두유','expires_at':base+600,'cert':{'cert':{}}},
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
             row(25,base-385,'계란 10구 구해요 환불 문의'),row(26,base-384,'소이밀크 190ml 구해요')]
    posts.extend(row(1000+idx*2,base-200+idx,'일반 게시물') for idx in range(120))
    sends, scans = [], []
    switches = {'timeout':False,'break_scan':False}

    class FakeMarket:
        def __init__(self, kit):
            assert kit.testing
            self.kit = SimpleNamespace(address=lambda role: wallet)
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

    with TemporaryDirectory(prefix='forum-v6-',dir=state) as fixture, ExitStack() as stack:
        path = Path(fixture)/'dispatcher.sqlite'
        policy = Path(fixture)/'first-purchase-bonus-policy.json'
        original_open = parent.open_forum
        stack.enter_context(patch.object(parent,'open_forum',lambda address:original_open(address,path)))
        stack.enter_context(patch.object(shop,'DB',path))
        stack.enter_context(patch.object(parent,'Market',FakeMarket))
        stack.enter_context(patch.object(parent,'time',SimpleNamespace(time=lambda:clock[0])))
        stack.enter_context(patch.dict(parent.render_verified.__globals__,{'POLICY':policy}))
        stack.enter_context(patch.object(shop,'usable_units',lambda inventory,now:inventory))
        stack.enter_context(patch.object(shop,'price_terms',lambda unit,bps,network:(2000,1000)))
        stack.enter_context(patch.object(shop,'preferred_sale_price',lambda unit,terms,bps,network,launch:terms[0]))
        stack.enter_context(patch.object(shop.price_policy,'current',lambda now:False))
        with closing(original_open(wallet,path)) as db:
            db.execute('CREATE TABLE IF NOT EXISTS welcome_award(payer TEXT PRIMARY KEY,amount INTEGER NOT NULL)')
            db.commit()

        legacy = run({'action':'context','preset':'conservative'},kit)
        assert legacy['status']=='options' and 'source' not in legacy, legacy
        assert all('spotlight_eligible' not in item for item in legacy['items'])
        scans.clear()
        slate = run({'action':'slate_context'},kit)
        assert slate['status']=='options', slate
        source = slate['source']
        assert source['schema']=='outseop-r4.forum-candidates.v1'
        assert source['observed_at']==base and source['valid_until']==base+90
        assert [item['sku'] for item in source['items']]==[sku]
        assert source['items'][0]['certificate'] and source['items'][0]['spotlight_eligible']
        assert {entry['thread'] for entry in source['reply_options']}=={10,11,12}, source
        assert len([call for call in scans if call[0] and call[1]==100])<=30
        switches['break_scan'] = True
        incomplete = run({'action':'slate_context'},kit)['source']
        assert incomplete['spotlight_allowed'] and incomplete['reply_options']==[]
        assert publish('reply',10)['status']=='no_fresh_matching_request'
        switches['break_scan'] = False
        assert publish('reply',18)['status']=='no_fresh_matching_request'
        assert publish('reply',13)['status']=='no_fresh_matching_request'
        assert not sends
        assert run({'action':'publish','decision':{'action':'hold','reason':'fixture'}},kit)['status']=='hold'

        policy.write_text(json.dumps({'enabled':True,'id':'fixture','start':base-1,'end':base+850,'lifetime_budget':50000}),encoding='utf-8')
        first = publish('spotlight')
        assert first['status']=='posted', first
        assert '첫 구매 추가 5% 적립' in sends[-1]['text'] and 'KST' in sends[-1]['text']
        assert parent.BENEFITS in sends[-1]['text']
        clock[0] += 331
        refreshed = run({'action':'slate_context'},kit)['source']
        assert refreshed['own_spotlight_history']==[{'post':first['post'],'sku':sku,'grade':'A','category':'식품 > 계란','ts':base}]
        assert not refreshed['items'][0]['spotlight_eligible']
        assert publish('reply',10)['status']=='posted'
        clock[0] += 331
        assert publish('reply',10)['status']=='no_fresh_matching_request'
        clock[0] += 331
        assert publish('reply',11)['status']=='posted'
        assert '첫 구매 추가 5% 적립' not in sends[-1]['text']
        clock[0] += 331
        switches['timeout'] = True
        assert publish('reply',12)['status']=='unknown'
        assert len(sends)==4
        clock[0] += 35
        assert run({'action':'reconcile'},kit)['status']=='unknown'
        assert publish('reply',12)['status']=='unresolved_publish'
        assert len(sends)==4
