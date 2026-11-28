from contextlib import closing
import re
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch


def test(run, kit):
    scope_globals = run.__globals__
    assert r'\w' not in scope_globals['MORE_INTENT']
    original_compile = re.compile
    wrapper = scope_globals['load_wrapper']()
    assert wrapper.CACHE_LIMIT == 8192
    assert wrapper.V11[1] == 'd4297f458ea0bcbc98c18a621ded5c834d191323e25f34f3361212dd3f9942ed'
    assert wrapper.V10[1] == 'bd80f8236c415ffc962b5b651f24232e8e34320a621145954abbbf0bedca073a'
    assert wrapper.V9[1] == 'b2edc8dba8c214a22074eb1f3db35ce5eb8234f444cf22710f025078b64e48e9'
    impl = wrapper.optimize_classifier(wrapper.load_verified11())
    assert isinstance(impl.classify.__globals__['re'], wrapper.ClassifierRegex)
    v9 = impl.load_owner().load_v9()
    parent = v9.PARENT
    now = 1795859705
    sku = 'F01234567'
    offer = {'sku': sku, 'name': '두유 200ml 2개입', 'grade': 'A', 'price': 10000, 'category': '식품>음료', 'expiry': now + 14400, 'certificate': True, '_base': 10000, '_unit': 101}
    egg = dict(offer, sku='F87654321', name='계란 10개입', category='식품>계란', _unit=102)
    other_soy = dict(offer, sku='F12345678', name='두유 300ml 3개입', _unit=103)
    regression = dict(offer, name='두유190ml1개입', category='두유', price=8000, _base=8000)

    def row(text, **changes):
        return dict({'id': 22, 'ts': now - 10, 'round': 4, 'role': 'buyer', 'author': 'synthetic-buyer', 'thread': None, 'text': text}, **changes)

    def kind(text, candidate=offer, **changes):
        return impl.classify(v9, row(text, **changes), candidate, now)

    compiler = wrapper.new_compiler()
    scope = wrapper.COMPILER.set(compiler)
    try:
        for text in ('두유를 구할 수 있나요500ml', '두유를 구할 수 있어요500ml', '두유를 구매 원해요500ml', '두유 500ml가 필요해요', '두유를 구할 수 있나요7999크레딧 이하. 가격 문의합니다.', '두유를 구매하려고요7999크레딧 이하. 가격 문의합니다.', '두유를 찾고 있어요123. 견적 문의합니다.', '두유를 찾고 싶어요USB. 문의합니다.', '두유를 구매하고 싶어요2x500ml. 가격 문의합니다.', '두유를 구매할 수 있나요500ml2개입', '두유를 구매 가능해요5kg. 가격 문의합니다.', '두유를 구매 원해요ABC. 가격 문의합니다.', '두유를 구할 수 있어요500ml 인증서 필수'):
            assert kind(text, regression) is None, text
        for text in ('두유를 구할 수 있나요?', '두유를 구할 수 있어요?', '두유를 구매 원해요.', '두유를 구매하려고 합니다.', '두유를 구매 가능할까요?'):
            assert kind(text) in ('strict', 'reference'), text
        assert kind('계란이 필요한 상황이에요. 집에서 쓰기 편한 후보를 보고 싶어요.', egg) == 'reference'
        preference = '찾는 상품은 두유예요. 아침에 간편하게 쓸 수 있는 후보가 궁금해요.'
        assert kind(preference) == 'reference'
        assert kind(preference, egg) is None
        assert kind('두유가 필요') == 'strict'
        assert kind('두유를 구할 수 있을까요? 지금 재고와 상품가를 문의합니다.') in ('strict', 'reference')
        assert kind('두유가 필요해요. A등급 10000크레딧 이하로 가격 문의드립니다.') == 'strict'
        assert kind('두유가 필요해요. 책 읽을 때 곁들이기 편하면 좋겠어요.') == 'reference'
        assert kind('찾는 물건은 두유입니다. 소포장 후보를 보고 싶어요') == 'reference'
        assert kind('두유가 필요해요. C등급 제외') in ('strict', 'reference')
        assert kind('두유가 필요해요. C등급 제외', dict(offer, grade='C')) is None
        assert kind('두유 300ml가 필요해요', other_soy) == 'strict'
        assert kind('두유 3개가 필요해요', other_soy) == 'strict'
        assert kind('두유 B등급이 필요해요', dict(offer, grade='B')) == 'strict'
        assert kind('두유가 필요해요? 9999크레딧 이하', dict(offer, price=9999)) == 'strict'
        assert kind('두유 5시간 이상 남은 두유를 구해요', dict(offer, expiry=now+21600)) == 'strict'
        assert kind('F01234567만 필요해요?') == 'strict'
        assert kind('F01234567만 필요해요?', other_soy) is None
        assert kind('두유가 필요해요. 인증서 필수', dict(offer, certificate=False)) is None
        for text in ('두유 300ml가 필요해요', '두유 3개가 필요해요', '두유 2x200ml가 필요해요', '두유 B등급이 필요해요', '두유 A등급 제외 필요해요', '두유가 필요해요? 9999크레딧 이하', '두유 5시간 이상 남은 두유를 구해요', '두유 F87654321만 필요해요', '두유 말고 후보를 문의합니다', '두유 2개가 아닌 제품을 찾아주세요', '두유가 불필요해요', '두유 필요없어요', '두유는 필요하지 않아요', '두유 구매하지않음', '두유 구매했어요. 가격 문의합니다', '두유를 샀어요. 가격 문의', '두유가 필요해요. 후기 문의', '두유가 필요해요. 알레르기', '두유가 필요해요. 당뇨 환자용', '두유가 필요해요. 비건 제품', '두유가 필요해요. 아이폰 전용', '두유가 필요해요. 특정 기기와 호환', '두유가 필요해요. 공식 인증이 되어야 해요', '두유가 필요해요. 대안은 사절이에요', '두유가 필요해요. me@example.com', '두유가 필요해요? www.example.com', '두유가 필요해요? 주소 문의', '두유가 필요해요? 환불 문의', '두유가 필요해요? 영수증'):
            assert kind(text) is None, text
        assert kind(preference, hidden=True) is None
        assert kind(preference, round=3) is None
        assert kind(preference, round='4') is None
        assert kind(preference, role='shop') is None
        assert kind(preference, ts=True) is None
        assert kind(preference, ts=now-21601) is None
        assert kind(preference, ts=now+1) is None
        previous = compiler.cache_info()
        assert previous.misses > 0 and 0 < previous.currsize <= 8192
        assert kind(preference) == 'reference'
        current = compiler.cache_info()
        assert current.hits > previous.hits and current.misses == previous.misses
        assert current.maxsize == 8192

        reference = row(preference)
        card = 'https://synthetic.invalid/card'
        synthetic_kit = SimpleNamespace(name=parent.shop.SHOP, market='https://market.ourolabs.ai', shop_url=card, address=lambda role: '0x'+'1'*40, testing=True)
        market = SimpleNamespace(kit=synthetic_kit, deadline=float('inf'), shop_url=card, _reply_evidence={22: reference})
        state = impl.CURRENT.set({'market': market})
        try:
            with closing(sqlite3.connect(':memory:')) as db, patch.object(parent.time, 'time', return_value=now), patch.object(v9, 'read_policy', return_value=None):
                with patch.object(parent, 'stock_offers', return_value=[offer.copy()]), patch.object(market, 'window_page', create=True, return_value=[reference]):
                    output = parent._v11_render_publication(db, market, offer, 22, now, (600, 3600))
                    assert output.startswith('관련 재고 참고 안내입니다. 요청하신 전체 조건의 충족 여부는 확인되지 않았습니다. 주문 수락, 조건 보장 또는 예약의 의미는 없습니다.')
                    assert sku in output and '10,000' in output and '시장 인증서 있음' in output and preference not in output
                observations = (([], reference), ([dict(offer, _unit=104)], reference), ([dict(offer, price=10001)], reference), ([offer.copy()], dict(reference, text='두유가 필요해요. 아이폰 전용')), ([offer.copy()], dict(reference, text='두유를 구할 수 있나요500ml')), ([offer.copy()], dict(reference, hidden=True)), ([offer.copy()], dict(reference, ts=now-21601)))
                for inventory, live_row in observations:
                    market._reply_evidence[22] = reference
                    with patch.object(parent, 'stock_offers', return_value=inventory), patch.object(market, 'window_page', create=True, return_value=[live_row]):
                        try:
                            parent._v11_render_publication(db, market, offer, 22, now, (600, 3600))
                        except ValueError as error:
                            assert str(error) in ('current offer changed', 'fresh request changed', 'fresh request no longer matches')
                        else:
                            raise AssertionError('changed publication evidence passed')
        finally:
            impl.CURRENT.reset(state)
    finally:
        wrapper.COMPILER.reset(scope)
        compiler.cache_clear()
    assert compiler.cache_info().currsize == 0
    with patch.object(wrapper, 'load_verified11', return_value=SimpleNamespace(classify=impl.classify, run=lambda args, sample_kit: {'status': 'synthetic'})):
        assert wrapper.run({'action': 'context'}, kit) == {'status': 'synthetic'}
    assert wrapper.COMPILER.get() is None and re.compile is original_compile
    return {'status': 'passed'}
