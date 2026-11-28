from contextlib import closing
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch


def test(run, kit):
    impl = run.__globals__
    owner = impl['load_owner']()
    v9 = owner.load_v9()
    parent = v9.PARENT
    now = 1795859705
    sku = 'F01234567'
    offer = {'sku': sku, 'name': '두유 200ml 2개입', 'grade': 'A', 'price': 10000, 'category': '식품>음료', 'expiry': now + 14400, 'certificate': True, '_base': 10000, '_unit': 101}
    classify = impl['classify']

    def row(text, **extra):
        return dict({'id': 22, 'ts': now - 10, 'round': 4, 'role': 'buyer', 'author': 'synthetic-buyer', 'thread': None, 'text': text}, **extra)

    def kind(text, **changes):
        return classify(v9, row(text), dict(offer, **changes), now)

    for text in ('두유가 필요해요. A등급 10000크레딧 이하로 가격 문의드립니다', '두유가 필요합니다. 지금 재고와 견적을 알려주실 수 있나요?', '두유가 필요합니다. 두유를 찾고 있어요?', '두유 200ml 2개가 필요해요?', '두유 200ml를 찾아주세요', 'F01234567만 필요해요?'):
        assert kind(text) == 'strict', text
    reference = row('찾는 물건은 두유입니다. 소포장 후보를 보고 싶어요')
    assert classify(v9, reference, offer, now) == 'reference'
    assert kind('두유가 필요해요. 산뜻한 느낌이면 좋겠어요') == 'reference'
    for text in ('두유가 필요해요? https://example.com', '두유가 필요해요? www.example.com', '두유가 필요해요? 주소 문의', '두유가 필요해요? me@example.com', '두유가 필요해요? 환불 문의', '두유가 필요해요? 후기 문의', '두유가 필요해요? 알레르기', '두유가 필요해요? 영수증', '두유를 샀어요. 가격 문의', '두유가 필요해요? 9999크레딧 이하', '두유 B등급이 필요해요', '두유 A등급 제외 필요해요', '두유 5시간 이상 남은 두유를 구해요', '두유 300ml가 필요해요', '두유 3개입 필요해요', '두유 3개가 필요해요', '두유 2개가 아닌 제품을 찾아주세요', '두유 2x200ml가 필요해요', '두유 2박스가 필요해요', '두유 F87654321만 필요해요', '두유 말고 후보를 문의합니다', '두유 소포장만 필요해요'):
        assert kind(text) is None, text
    assert kind('두유가 필요해요. 인증서 필수', certificate=False) is None
    assert classify(v9, row('두유가 필요해요', hidden=True), offer, now) is None
    assert classify(v9, row('두유가 필요해요', round=3), offer, now) is None
    card = 'https://synthetic.invalid/card'
    address = '0x' + '1' * 40
    synthetic_kit = SimpleNamespace(name=parent.shop.SHOP, market='https://market.ourolabs.ai', shop_url=card, address=lambda role: address, testing=True)
    market = SimpleNamespace(kit=synthetic_kit, deadline=float('inf'), shop_url=card, _reply_evidence={22: reference})
    rates = (600, 3600)
    state = impl['CURRENT'].set({'market': market})
    try:
        with closing(sqlite3.connect(':memory:')) as db, patch.object(parent.time, 'time', return_value=now), patch.object(v9, 'read_policy', return_value=None):
            with patch.object(parent, 'stock_offers', return_value=[offer.copy()]), patch.object(market, 'window_page', create=True, return_value=[reference]):
                output = parent._v11_render_publication(db, market, offer, 22, now, rates)
                assert output.startswith(impl['REFERENCE_TITLE']) and sku in output and '10,000' in output and '시장 인증서 있음' in output
            observations = (([], reference), ([dict(offer, _unit=102)], reference), ([dict(offer, price=10001)], reference), ([dict(offer, grade='B')], reference), ([dict(offer, expiry=now-1)], reference), ([offer.copy()], dict(reference, text='두유 환불 문의')), ([offer.copy()], dict(reference, hidden=True)), ([offer.copy()], dict(reference, ts=now-21601)))
            for current, observation in observations:
                market._reply_evidence[22] = reference
                with patch.object(parent, 'stock_offers', return_value=current), patch.object(market, 'window_page', create=True, return_value=[observation]):
                    try:
                        parent._v11_render_publication(db, market, offer, 22, now, rates)
                    except ValueError as error:
                        assert str(error) in ('current offer changed', 'fresh request changed', 'fresh request no longer matches')
                    else:
                        raise AssertionError('changed publication evidence passed')
    finally:
        impl['CURRENT'].reset(state)

    c = dict(offer, grade='C', expiry=now+1200)
    base = parent.offer_fingerprint(c, None)
    epoch = impl['epoch_identity'](v9, sku, now)
    assert epoch != base and epoch != impl['epoch_identity'](v9, sku, now + 86400)
    with closing(sqlite3.connect(':memory:')) as db:
        # The inherited spotlight query selects the publication row ID.
        db.execute('CREATE TABLE forum_publication(id INTEGER PRIMARY KEY, shop TEXT, round INTEGER, thread INTEGER, status TEXT, post INTEGER, content TEXT, created INTEGER, fingerprint TEXT, sku TEXT)')
        shop = parent.shop.SHOP

        def add(target, age, fingerprint, status='posted', post=10, thread=None):
            db.execute('INSERT INTO forum_publication(shop,round,thread,status,post,content,created,fingerprint,sku) VALUES(?,?,?,?,?,?,?,?,?)', (shop, 4, thread, status, post, 'synthetic publication', now-age, fingerprint, target))

        def confirm(since, limit, deadline):
            prior = db.execute('SELECT created FROM forum_publication WHERE fingerprint=?', (base,)).fetchone()
            assert prior is not None and since == 9 and limit == 1
            return [{'id': 10, 'ts': prior[0], 'round': 4, 'role': 'shop', 'author': shop, 'text': 'synthetic publication', 'thread': None}]

        def scenario(rows, wanted, offer_=c, rates_=rates):
            db.execute('SAVEPOINT scenario')
            try:
                for values in rows:
                    add(*values)
                with patch.object(market, 'window_page', create=True, side_effect=confirm):
                    actual = impl['urgent_epoch'](v9, db, market, offer_, now, rates_)
                    assert actual == wanted, (rows, actual, wanted)
            finally:
                db.execute('ROLLBACK TO scenario')
                db.execute('RELEASE scenario')

        prior = (sku, 3600, base)
        assert v9.spotlight_eligible is parent.spotlight_eligible
        state = impl['CURRENT'].set({'market': market})
        try:
            assert parent.spotlight_eligible(db, offer, now, rates)
            assert parent.spotlight_eligible(db, c, now, rates)
        finally:
            impl['CURRENT'].reset(state)
        scenario([prior], epoch)
        scenario([prior, ('F11111111', 600, 'spotlight', 'posted', 11), ('F22222222', 330, 'global', 'posted', 12, 42)], epoch)
        scenario([prior], None, dict(c, expiry=now+1199))
        scenario([prior], None, dict(c, expiry=now+21601))
        scenario([prior], None, offer)
        scenario([], None)
        scenario([(sku, 3599, base)], None)
        scenario([prior], None, c, (600, 3601))
        scenario([prior, ('F11111111', 599, 'spotlight', 'posted', 11)], None)
        scenario([prior, ('F11111111', 329, 'global', 'posted', 11, 42)], None)
        scenario([prior, (sku.lower(), 7200, epoch, 'posted', 11)], None)
        for status in ('unknown', 'pending', 'sending'):
            scenario([prior, (sku, 90000, 'earlier-epoch', status, None)], None)
        scenario([(sku, 3700, base, 'declined', None)], None)
        scenario([(sku, 3700, base, 'posted', None)], None)
        scenario([prior] + [(f'F{i+100:08x}', 4000+i, f'day-{i}', 'posted', i+100, i+100) for i in range(95)], None)
        add(*prior)
        for observation in ([], [dict(confirm(9, 1, 0)[0], author='synthetic-other')], [dict(confirm(9, 1, 0)[0], text='changed')]):
            with patch.object(market, 'window_page', create=True, return_value=observation):
                assert impl['urgent_epoch'](v9, db, market, c, now, rates) is None
        state = impl['CURRENT'].set({'market': market})
        try:
            with patch.object(parent.time, 'time', return_value=now), patch.object(parent, 'stock_offers', return_value=[c.copy()]), patch.object(parent, 'render', return_value='합성 재고 안내'), patch.object(v9, 'read_policy', return_value=None), patch.object(market, 'window_page', create=True, side_effect=confirm):
                assert parent.spotlight_eligible(db, c, now, rates)
                assert parent._v11_publication_fingerprint(db, market, c, None, now, rates) == epoch
                output = parent._v11_render_publication(db, market, c, None, now, rates)
                assert output.startswith(impl['URGENT_TITLE']) and '20분' in output
                add(sku, 90000, 'previous-epoch', 'unknown', None)
                assert not parent.spotlight_eligible(db, c, now, rates)
                try:
                    parent._v11_render_publication(db, market, c, None, now, rates)
                except ValueError as error:
                    assert str(error) == 'urgent spotlight is unavailable'
                else:
                    raise AssertionError('unresolved prior send allowed at render')
        finally:
            impl['CURRENT'].reset(state)

    assert parent.forum_reconcile.__code__.co_filename == parent.__file__
    assert owner.TICK_URL == 'http://127.0.0.1:18812/_internal/r4-marketing/tick'
    generation = 'a'*64
    policy = {'generation': generation, 'token': 'b'*64}
    with patch.object(owner, 'read_policy', return_value=None), patch.object(owner, 'request_tick') as tick, patch.object(owner, 'delegate') as delegate:
        assert owner.run({'action': 'publish'}, kit) == {'status': 'hold'}
        assert owner.run({'action': 'reconcile'}, kit) == {'status': 'hold'}
        assert owner.run({'action': 'publish', 'scheduler_generation': generation, 'operation_timeout': 40}, kit) == {'status': 'hold'}
        tick.assert_not_called()
        delegate.assert_not_called()
    with patch.object(owner, 'read_policy', return_value=policy), patch.object(owner, 'request_tick', return_value={'status': 'marketing_transferred'}) as tick, patch.object(owner, 'delegate', return_value={'status': 'synthetic'}) as delegate:
        assert owner.run({'action': 'reconcile'}, kit) == {'status': 'marketing_transferred'}
        tick.assert_called_once_with(policy)
        assert owner.run({'action': 'publish', 'scheduler_generation': generation, 'operation_timeout': 40}, kit) == {'status': 'synthetic'}
        delegate.assert_called_once_with({'action': 'publish'}, kit, 40)
        for bad in (True, float('inf'), float('nan'), 41, 0):
            assert owner.run({'action': 'publish', 'scheduler_generation': generation, 'operation_timeout': bad}, kit) == {'status': 'hold'}
        assert owner.run({'action': 'publish', 'scheduler_generation': 'c'*64, 'operation_timeout': 40}, kit) == {'status': 'hold'}
        assert owner.run({'action': 'publish', 'scheduler_generation': generation}, kit) == {'status': 'hold'}
        delegate.assert_called_once()
    response = SimpleNamespace(status_code=200, content=b'{"status":"marketing_transferred"}')
    with patch.object(owner.httpx, 'post', return_value=response) as post:
        assert owner.request_tick(policy) == {'status': 'marketing_transferred'}
        post.assert_called_once_with(owner.TICK_URL, json={'generation': generation}, headers={'Authorization': 'Bearer ' + policy['token']}, timeout=130, trust_env=False, follow_redirects=False)
    return {'status': 'passed'}
