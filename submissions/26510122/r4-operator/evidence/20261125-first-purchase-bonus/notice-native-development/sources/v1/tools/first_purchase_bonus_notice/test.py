import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import httpx


def test(run, kit):
    assert kit.testing
    assert run({'mode': 'dispatch'}, kit) == {'status': 'blocked', 'reason': 'offline_development'}
    assert run({'mode': 'dispatch', 'text': 'fixture'}, kit)['reason'] == 'invalid_args'
    assert run({'mode': 'preview', 'url': 'https://invalid.example'}, kit)['reason'] == 'invalid_args'
    logic = run.__globals__
    execute = logic['execute']
    stop = logic['Stop']
    market, shop, wallet = logic['MARKET'], logic['SHOP'], logic['WALLET']
    assert logic['APPROVED_CARD'] is None and logic['APPROVED_FINGERPRINT'] is None
    card_base = market + '/fixtures/shop'
    card_pin = card_base + logic['CARD_SUFFIX']
    now = 1795606112
    clock = [now]
    token_calls = []

    def token(role):
        assert role == 'shop'
        token_calls.append(role)
        return 'synthetic-shop-token'

    fake = SimpleNamespace(name=shop, market=market, shop_url=card_base, address=lambda role: wallet if role == 'shop' else None, token=token)
    state_dir = Path('state/r4-benefits')
    state_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='notice-test-', dir=state_dir) as directory:
        root = Path(directory)
        db_path = root / logic['DB']
        policy_path = root / logic['POLICY']
        policy = {'enabled': True, 'id': 'synthetic-campaign', 'start': now - 60, 'end': now + 7200, 'lifetime_budget': 12300}
        policy_path.write_text(json.dumps(policy), encoding='utf-8')
        text = logic['render'](policy['start'], policy['end'])
        approved = logic['campaign_prefix'](policy['id']) + logic['body_hash'](text)
        flags = {}
        posts = []
        calls = []
        actual_dispatches = []

        def change(sql, values=()):
            with closing(sqlite3.connect(db_path)) as db, db:
                return db.execute(sql, values).fetchall()

        change("CREATE TABLE forum_publication (id TEXT PRIMARY KEY, shop TEXT, round INTEGER, thread INTEGER NULL, sku TEXT, content TEXT, anchor INTEGER, status TEXT CHECK(status IN ('sending','unknown','declined','posted')), fingerprint TEXT, created REAL, post INTEGER UNIQUE NULL, reconcile_after REAL DEFAULT 0)")
        change('CREATE TABLE welcome_award (amount INTEGER)')
        change('INSERT INTO welcome_award(amount) VALUES (300), (2000)')

        def legacy(status, created):
            change('INSERT INTO forum_publication VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', ('legacy', shop, 4, 3, 'legacy-item', 'legacy-body', 1, status, 'legacy-fingerprint', created, None, 0))

        def public(post_id, author='other', ts=None, thread=None, content='fixture'):
            return {'id': post_id, 'author': author, 'role': 'shop', 'shop': author, 'round': 4, 'thread': thread, 'content': content, 'ts': now - 400 if ts is None else ts}

        def handler(request):
            assert request.url.host == 'market.ourolabs.ai'
            calls.append((request.method, request.url.path))
            if request.method == 'GET':
                assert 'authorization' not in request.headers
            if request.url.path == '/api/shops':
                return httpx.Response(200, json={'round': 4, 'shops': [{'name': shop, 'url': flags.get('url', card_base), 'pubkey': 'synthetic'}]})
            if request.url.path == '/fixtures/shop' + logic['CARD_SUFFIX']:
                return httpx.Response(200, json={'supportedInterfaces': [{'url': card_base}], 'roles': {'shop': {'wallet': flags.get('wallet', wallet)}}})
            assert request.url.path == '/api/forum'
            if request.method == 'GET':
                assert request.url.params['limit'] == '100'
                if flags.pop('concurrent_legacy', False):
                    legacy('sending', now)
                since = int(request.url.params['since'])
                rows = posts[-100:] if since == 0 else [row for row in posts if row['id'] > since][:100]
                return httpx.Response(200, json={'posts': rows})
            assert request.method == 'POST'
            assert request.headers['authorization'] == 'Bearer synthetic-shop-token'
            assert json.loads(request.content) == {'text': text}
            assert change('SELECT shop,round,thread,sku,content,status,anchor FROM forum_publication WHERE id=?', (approved,)) == [(shop, 4, None, '__first_purchase_bonus__', text, 'sending', posts[-1]['id'] if posts else 0)]
            actual_dispatches.append(1)
            outcome = flags.get('outcome', 'success')
            if outcome == 'timeout':
                raise httpx.ReadTimeout('fixture-only transport detail', request=request)
            if outcome == 'rate':
                return httpx.Response(429, json={'message': 'fixture-only response detail'})
            if outcome == 'duplicate':
                return httpx.Response(409, json={'code': 'duplicate_post'})
            if outcome == 'ambiguous_conflict':
                return httpx.Response(409, json={'error': 'fixture-only response detail'})
            if outcome == 'server':
                return httpx.Response(500, json={'message': 'fixture-only response detail'})
            if outcome == 'invalid_json':
                return httpx.Response(200, text='fixture-only malformed content')
            if outcome == 'invalid_id':
                return httpx.Response(200, json={'post': True})
            if outcome == 'old_id':
                return httpx.Response(200, json={'post': posts[-1]['id']})
            return httpx.Response(200, json={'post': 222})

        with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False, trust_env=False) as client:
            def invoke(mode, pin=approved, legacy_pin=None):
                return execute(mode, fake, root, client, lambda: clock[0], card_pin, pin, legacy_pin)

            def blocked(mode, reason, pin=approved, legacy_pin=None):
                count = len(actual_dispatches)
                try:
                    invoke(mode, pin, legacy_pin)
                except stop as error:
                    assert str(error) == reason
                else:
                    raise AssertionError('expected blocked fixture')
                assert len(actual_dispatches) == count

            posts[:] = [public(10)]
            preview = invoke('preview')
            assert preview == {'status': 'preview', 'lane': 'eligible', 'remaining_credits': 10000, 'text': text}
            assert all(term in text for term in ('outseop-r4', 'KST', '72시간', '5,000', '50,000', '1%', '5%', '7일', '다음 구매', '재지급하지 않습니다'))
            assert len(text) <= 2000 and 'https://' not in text and not actual_dispatches and not token_calls
            assert change('SELECT * FROM forum_publication') == []
            blocked('dispatch', 'dispatch_unapproved', None)
            flags['url'] = 'https://invalid.example/shop'
            blocked('dispatch', 'registry_unverified')
            del flags['url']
            flags['wallet'] = '0x0000000000000000000000000000000000000000'
            blocked('dispatch', 'card_unverified')
            del flags['wallet']
            change('DROP TABLE welcome_award')
            blocked('preview', 'award_schema_unverified')
            import hashlib
            legacy_pin = logic['digest']([hashlib.sha256(policy_path.read_bytes()).hexdigest(), hashlib.sha256(db_path.read_bytes()).hexdigest()])
            assert invoke('preview', legacy_pin=legacy_pin)['remaining_credits'] == 12300
            change('CREATE TABLE welcome_award (amount INTEGER)')
            change('INSERT INTO welcome_award VALUES (12300)')
            blocked('dispatch', 'budget_exhausted')
            change('DELETE FROM welcome_award')
            bad_policy = dict(policy, end=now + 73 * 3600)
            policy_path.write_text(json.dumps(bad_policy), encoding='utf-8')
            blocked('dispatch', 'policy_inactive')
            policy_path.write_text(json.dumps(policy), encoding='utf-8')
            change('ALTER TABLE forum_publication RENAME TO fixture_saved_publication')
            blocked('dispatch', 'journal_schema_invalid')
            change('ALTER TABLE fixture_saved_publication RENAME TO forum_publication')
            posts[:] = [public(i, ts=now - 100) for i in range(1, 101)]
            blocked('dispatch', 'history_coverage_unverified')
            posts[:] = [public(10), public(11, shop, now - 329, thread=5)]
            blocked('dispatch', 'cooldown')
            posts[:] = [public(10)]
            legacy('posted', now - 329)
            blocked('dispatch', 'cooldown')
            change('DELETE FROM forum_publication WHERE id=?', ('legacy',))
            legacy('unknown', now - 400)
            blocked('dispatch', 'journal_busy')
            change('DELETE FROM forum_publication WHERE id=?', ('legacy',))
            flags['concurrent_legacy'] = True
            blocked('dispatch', 'journal_busy')
            assert change('SELECT status,content FROM forum_publication WHERE id=?', ('legacy',)) == [('sending', 'legacy-body')]
            change('DELETE FROM forum_publication WHERE id=?', ('legacy',))
            assert not actual_dispatches
            assert invoke('dispatch') == {'status': 'posted'}
            assert change('SELECT status,post FROM forum_publication') == [('posted', 222)]
            blocked('dispatch', 'campaign_already_attempted')
            assert len(actual_dispatches) == 1
            for outcome in ('rate', 'duplicate', 'ambiguous_conflict', 'server', 'invalid_json', 'invalid_id', 'old_id', 'timeout'):
                # Each iteration is a fresh synthetic database state for the same campaign.
                change('DELETE FROM forum_publication')
                flags['outcome'] = outcome
                posts[:] = [public(10)]
                before = len(actual_dispatches)
                status = 'declined' if outcome in ('rate', 'duplicate') else 'unknown'
                assert invoke('dispatch') == {'status': status}
                stored = change('SELECT status,post,reconcile_after FROM forum_publication')[0]
                assert stored == (status, None, 0 if status == 'declined' else now + 330)
                blocked('dispatch', 'campaign_already_attempted' if status == 'declined' else 'journal_busy')
                assert len(actual_dispatches) == before + 1
            assert invoke('reconcile') == {'status': 'unknown', 'resolution': 'pending'}
            clock[0] = now + 330
            assert invoke('reconcile') == {'status': 'unknown', 'resolution': 'unobserved'}
            blocked('dispatch', 'journal_busy')
            posts.extend([public(11, shop, now - 3, content=text), public(12, 'other', now, content=text), public(13, shop, now, thread=5, content=text), public(14, shop, now, content=text + ' '), public(15, shop, now, content=text)])
            posts[4]['round'] = 3
            posts.append(public(16, shop, now + 1, content=text))
            assert invoke('reconcile') == {'status': 'unknown', 'resolution': 'multiple_matches'}
            posts.pop()
            assert invoke('reconcile') == {'status': 'posted', 'resolution': 'observed'}
            assert change('SELECT status,post FROM forum_publication') == [('posted', 15)]
            assert invoke('reconcile') == {'status': 'no_pending_notice'}
            assert len(actual_dispatches) == 9
            assert all(path in ('/api/shops', '/fixtures/shop' + logic['CARD_SUFFIX'], '/api/forum') for _, path in calls)
    print('first_purchase_bonus_notice synthetic selftest passed: offline entry, preview and blocked dispatch zero POSTs, approved attempt one mock POST, shared journal concurrency, identity and permission scope, ambiguity without automatic resend')
