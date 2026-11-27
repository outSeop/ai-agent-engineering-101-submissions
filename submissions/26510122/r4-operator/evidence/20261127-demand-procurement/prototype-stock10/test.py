import json


def test(run, kit):
    ns = run.__globals__
    active = ns['active']
    data = {'campaign_id': 'test', 'starts_at': 100, 'ends_at': 21700}
    assert active(data, 100) == ('test', 100, 21700)
    assert active(data, 99) is None and active(data, 21700) is None
    assert active(dict(data, ends_at=21701), 101) is None
    assert active(dict(data, wallet='extra'), 101) is None
    base = {'cash': 20500, 'equity_at_cost': 100000, 'stock_cost': 79500, 'pending_cost': 0, 'cash_reserve': 12600}
    inv = {'storage_per_day': .10, 'storage_due_with_next_lot': 900, 'next_dislike_fee': 100}
    facts = ns['campaign_facts'](base, inv, [{'kind': 'goods', 'cost': 40000}], int, 0)
    approve = ns['approve_campaign']
    assert facts['reserve6'] == 5600 and facts['cap'] == 5000
    assert approve(facts, (900,100), (900,100), 4000, 5000, 50, 100) == (4150, 5050)
    assert (79500+4000)*100 > 80*(100000-1000-50)
    assert (79500+4000)*100 <= 85*(100000-1000-50)
    assert approve(facts, (899,100), (900,100), 4000, 5000, 50, 100) is None
    assert approve(facts, (900,100), (900,100), 4000, 5001, 50, 100) is None
    assert approve(dict(facts, spent=900), (900,100), (900,100), 4000, 5000, 50, 100) is None
    assert approve(dict(facts, cash=9500), (900,100), (900,100), 4000, 5000, 50, 100) is None
    assert approve(dict(facts, stock_cost=81000), (900,100), (900,100), 4000, 5000, 50, 100) is None
    assert not ns['is_new']({'choices': json.dumps({'finance': {}})})
    assert ns['is_new']({'choices': json.dumps({'stock_overlay': 10})})
    now = 50000
    events = [dict(seq=i, ts=now-10, kind='settle', round=4, sku='test-sku', grade='A', amount=100+i,
                   shop='other', broken=False, sealed=False, order_ref=str(i)) for i in range(5)]
    feed = {'observed_at': now-1, 'valid_until': now+100, 'round': 4,
            'coverage': {'since': now-22000, 'complete': True}, 'events': events+[events[0]]}
    comparable = ns['comparables']
    rows = comparable(feed, now, {'own'})['test-sku','A']
    assert len(rows) == 5
    ceiling = ns['safe_ceiling']
    assert 0 < ceiling(rows, 100, 'goods', .1, 6, (1, 200, 2, 'recipient'), 1, now) <= 80
    assert ceiling(rows, 100, 'food', .1, 6, (1, 200, 2, 'recipient'), 1, now, 180) == 0
    assert comparable(feed, now+100, {'own'}) == {}
    refund = dict(events[0], seq=9, kind='refund')
    assert comparable(dict(feed, events=events+[refund]), now, {'own'}) == {}
    assert comparable(feed, now, {'other'}) == {}
    assert comparable(dict(feed, events=events+[dict(events[0], amount=999)]), now, {'own'}) == {}
    public = ns['public_context']({'status':'draft','plan':'test','context':{'choices':[], 'finance':{'cash':42},
                                   'opens_at':1,'closes_at':2,'limits':{'lines':5}}})
    assert 'finance' not in json.dumps(public)
    fixture_ns = run.__globals__
    loader, policy_reader = fixture_ns['load_original'], fixture_ns['read_json']
    calls = []
    class Conn:
        def close(self):
            pass
    class Market:
        def __init__(self, kit):
            self.wallet = 'derived-wallet'
        def snapshot(self):
            return {}
    class Sales:
        Unavailable = RuntimeError
        @staticmethod
        def one(db, query, *params):
            return {'choices': '{}', 'status': 'ready'}
    class Kit:
        name = 'synthetic-shop'
        def pay(self, *args, **kw):
            raise AssertionError('synthetic rejection reached wallet')
    def original(args, kit):
        calls.append(args['action'])
        return {'status': 'legacy_80_48'}
    def fake_load():
        return dict(run=original, Market=Market, ledger=lambda wallet: Conn(), sales=Sales,
                    capacity=None, validate_quote=None, log=None, window=lambda inv: ('w', 1, 2))
    try:
        fixture_ns.update(load_original=fake_load, read_json=lambda path, size: None)
        assert run({'action':'execute'}, Kit()) == {'status':'legacy_80_48'}
        assert run({'action':'reconcile'}, Kit()) == {'status':'legacy_80_48'}
        assert run({'action':'plan','plan':'old'}, Kit()) == {'status':'invalid_plan'}
        assert calls == ['execute','reconcile']
    finally:
        fixture_ns.update(load_original=loader, read_json=policy_reader)
