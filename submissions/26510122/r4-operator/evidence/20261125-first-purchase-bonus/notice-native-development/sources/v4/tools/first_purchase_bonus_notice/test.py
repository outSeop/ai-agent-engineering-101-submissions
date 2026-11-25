import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import httpx


def test(run, kit):
    assert kit.testing
    logic = run.__globals__
    execute, stop = logic['execute'], logic['Stop']
    market, shop, wallet = logic['MARKET'], logic['SHOP'], logic['WALLET']
    assert wallet == '0x5FDC134D790EFB72DF1bbb922F2b49fcADe349C6'
    offline_kit = SimpleNamespace(testing=True)
    assert run({'mode': 'dispatch'}, offline_kit)['reason'] == 'offline_development'
    for field in ('text', 'url', 'amount', 'approval'):
        assert run({'mode': 'dispatch', field: 'fixture'}, offline_kit)['reason'] == 'invalid_args'
    now = 1795606517
    base = 'https://quiet-paper-cedar.trycloudflare.com'
    card = base + '/.well-known/agent-card.json'
    direct_card = {'name': 'outseop-r4', 'roles': ['shop'], 'wallets': {'shop': wallet}, 'supportedInterfaces': [{'url': base, 'protocolBinding': 'JSONRPC', 'protocolVersion': '1.0'}]}
    interface, = direct_card['supportedInterfaces']
    assert direct_card['name'] == shop and direct_card['roles'] == ['shop']
    assert direct_card['wallets'] == {'shop': wallet}
    assert interface == {'url': base, 'protocolBinding': 'JSONRPC', 'protocolVersion': '1.0'}
    assert logic['public_base'](interface['url']) + logic['CARD_SUFFIX'] == card
    state = Path('state/r4-benefits')
    state.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix='notice-v3-test-', dir=state) as directory:
        root = Path(directory)
        path = root / logic['DB']
        policy_path = root / logic['POLICY']
        approval_path = root / logic['APPROVAL']
        policy = {'enabled': True, 'id': 'synthetic-campaign', 'start': now - 60, 'end': now + 40, 'lifetime_budget': 49987}
        policy_raw = json.dumps(policy).encode()
        policy_path.write_bytes(policy_raw)
        snapshot = {'shop': direct_card['name'], 'round': 4, 'wallet': direct_card['wallets']['shop'], 'shop_url': interface['url'], 'card_url': card, 'observed_at': now - 5, 'valid_until': now + 100, 'policy_sha256': hashlib.sha256(policy_raw).hexdigest(), 'approved_fingerprint': None}
        clock = [now]
        flags = {}
        gets = []
        sends = []
        tokens = []
        posts = []

        def approve(**changes):
            approval_path.write_text(json.dumps(dict(snapshot, **changes)), encoding='utf-8')

        def query(sql, values=()):
            with closing(sqlite3.connect(path)) as db, db:
                return db.execute(sql, values).fetchall()

        with closing(sqlite3.connect(path)) as db, db:
            db.executescript(logic['BASELINE_SCHEMA'])
            db.execute('INSERT INTO identity VALUES (1,?,?)', (shop, wallet))
        query('PRAGMA journal_mode=WAL')
        tables = set(query("SELECT name FROM sqlite_master WHERE type='table'"))
        assert tables == {(name,) for name in ('identity account customer_profile visit visit_session_transport profile_fact ticket sale sale_category sale_buyer lot allocation refund event removal stock_signal stockout_observation broker_commit broker_offer cursor promotion_loss stock_observation stock_plan stock_intent stock_audit forum_publication').split()}
        for table, names in {'identity': 'singleton shop wallet', 'account': 'key created', 'sale': 'id owner base status payer settled', 'lot': 'sale_id owner amount expires revoked', 'allocation': 'id sale_id lot_id amount status', 'refund': 'sale_id payer status', 'event': 'id kind reference details'}.items():
            assert set(names.split()) <= {column[1] for column in query('PRAGMA table_info(' + table + ')')}

        def award_absent():
            return query("SELECT name FROM sqlite_master WHERE lower(name)='welcome_award'") == []

        def legacy(status, created, post=None, prefix=None):
            sku = 'legacy-item' if prefix is None else logic['SKU']
            fingerprint = 'legacy-fingerprint' if prefix is None else prefix + 'a' * 64
            query('INSERT INTO forum_publication VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', ('legacy', shop, 4, 3, sku, 'legacy-body', 1, status, fingerprint, created, post, created + 330 if status == 'unknown' else 0))

        def public(post_id, author='other', ts=None, thread=None, role='shop', round_number=4, text='fixture'):
            return {'id': post_id, 'ts': now - 400 if ts is None else ts, 'round': round_number, 'author': author, 'role': role, 'owner': None, 'thread': thread, 'text': text, 'refs': [], 'likes': 0, 'dislikes': 0, 'score': 0.0}

        def token(role):
            assert role == 'shop'
            tokens.append(role)
            operation = flags.pop('after_forum', None)
            if operation:
                operation()
            return 'synthetic-token'

        fake = SimpleNamespace(name=shop, market=market, shop_url=base, address=lambda role: wallet if role == 'shop' else None, token=token)

        def handler(request):
            assert request.url.host == 'market.ourolabs.ai'
            endpoint = request.url.path
            if request.method == 'GET':
                assert 'authorization' not in request.headers
                gets.append(endpoint)
                if endpoint == '/api/shops':
                    row = {'name': shop, 'url': flags.get('shop_url', base), 'pubkey': flags.get('pubkey', wallet)}
                    return httpx.Response(200, json={'round': 4, 'shops': [row]})
                if endpoint == '/api/agents':
                    row = {'name': shop, 'roles': flags.get('roles', direct_card['roles']), 'card': flags.get('card', card)}
                    return httpx.Response(200, json={'round': 4, 'agents': [row]})
                assert endpoint == '/api/forum' and dict(request.url.params) == {'since': '0', 'limit': '100'}
                if flags.get('get_timeout'):
                    raise httpx.ReadTimeout('fixture GET timeout', request=request)
                return httpx.Response(200, json=flags.get('forum_shape', posts[-100:]))
            assert endpoint == '/api/forum' and request.method == 'POST'
            assert request.headers['authorization'] == 'Bearer synthetic-token'
            assert json.loads(request.content) == {'text': text}
            with closing(sqlite3.connect(path, isolation_level=None)) as legacy_writer:
                legacy_writer.execute('BEGIN IMMEDIATE')
                visible = legacy_writer.execute("SELECT shop,round,thread,content,anchor,created,reconcile_after FROM forum_publication WHERE status='sending'").fetchall()
                assert visible == [(shop, 4, None, text, posts[-1]['id'] if posts else 0, now, now + 330)]
                legacy_writer.rollback()
            sends.append(endpoint)
            if flags.get('post_timeout'):
                raise httpx.ReadTimeout('fixture POST timeout', request=request)
            return httpx.Response(200, json={'post': 222})

        with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False, trust_env=False) as client:
            def invoke(mode):
                return execute(mode, fake, root, client, lambda: clock[0])

            def blocked(mode, reason):
                before = len(sends)
                try:
                    invoke(mode)
                except stop as error:
                    assert str(error) == reason, (str(error), reason)
                else:
                    raise AssertionError('expected guarded fixture')
                assert len(sends) == before

            blocked('preview', 'approval_missing')
            approve(observed_at=now - 100, valid_until=now)
            blocked('preview', 'approval_stale')
            approve(observed_at=now - 151, valid_until=now + 1)
            blocked('preview', 'approval_stale')
            approve(policy_sha256='0' * 64)
            blocked('preview', 'approval_policy_changed')
            approve(round=True)
            blocked('preview', 'approval_invalid')
            approve(watch='unexpected')
            blocked('preview', 'approval_invalid')
            approve(card_url=card + '?x=1')
            blocked('preview', 'card_unverified')
            approve(shop_url='https://rotated.trycloudflare.com')
            blocked('preview', 'approval_changed')
            approve()
            approval_path.chmod(0o666)
            blocked('preview', 'state_owner_invalid')
            approval_path.chmod(0o600)
            linked = root / 'linked-approval.json'
            os.link(approval_path, linked)
            blocked('preview', 'state_path_invalid')
            linked.unlink()
            approval_path.rename(linked)
            approval_path.symlink_to(linked.name)
            blocked('preview', 'state_path_invalid')
            approval_path.unlink()
            linked.rename(approval_path)
            assert not gets and not tokens

            listing = public(10, 'market', role='market', text='R4 공지')
            assert listing['author'] == 'market' and listing['role'] == 'market' and listing['text'] == 'R4 공지'
            assert set(listing) == {'id', 'ts', 'round', 'author', 'role', 'owner', 'thread', 'text', 'refs', 'likes', 'dislikes', 'score'}
            posts[:] = [listing]
            assert award_absent()
            preview = invoke('preview')
            assert set(preview) == {'status', 'lane', 'fingerprint', 'text'}
            assert preview['status'] == 'preview' and preview['lane'] == 'eligible'
            fingerprint, text = preview['fingerprint'], preview['text']
            assert fingerprint.startswith('first_purchase_bonus:v3:')
            assert all(term in text for term in ('outseop-r4', 'KST', '1%', '5%', '5,000', '50,000', '7일', '다음 구매', '재지급하지 않습니다', 'https://market.ourolabs.ai/board', '최신 Agent Card'))
            assert '추가 보너스는 최초 정상 정산 시각부터 7일 동안 유효하며 (기존 적립 기한 유지) 다음 구매부터 사용할 수 있습니다.' in text
            assert '발급일부터 7일' not in text
            assert all(value not in str(preview) for value in (wallet, 'trycloudflare', '49,987', '49987'))
            assert not sends and not tokens and award_absent() and query('SELECT * FROM forum_publication') == []
            blocked('dispatch', 'dispatch_unapproved')
            approve(approved_fingerprint=fingerprint[:-1] + ('0' if fingerprint[-1] != '0' else '1'))
            blocked('dispatch', 'approval_fingerprint_changed')
            approve(approved_fingerprint=fingerprint)
            for key, value, reason in (
                ('pubkey', '0x' + '0' * 40, 'shop_registry_unverified'),
                ('shop_url', 'https://new.trycloudflare.com', 'shop_registry_unverified'),
                ('roles', ['buyer'], 'agent_registry_unverified'),
                ('roles', ['shop', 4], 'agent_registry_unverified'),
                ('roles', 'shop', 'agent_registry_unverified'),
                ('card', 'https://new.trycloudflare.com/.well-known/agent-card.json', 'agent_registry_unverified'),
            ):
                flags[key] = value
                blocked('dispatch', reason)
                del flags[key]
            flags['roles'] = ['buyer', 'shop']
            assert invoke('preview') == preview

            flags['forum_shape'] = {'posts': []}
            blocked('dispatch', 'history_unverified')
            flags['forum_shape'] = [public(i) for i in range(1, 102)]
            blocked('dispatch', 'history_unverified')
            del flags['forum_shape']
            for key, value in (('ts', True), ('ts', str(now)), ('ts', float(now)), ('round', '4'), ('role', 'merchant'), ('thread', False), ('id', True), ('refs', None), ('likes', False), ('dislikes', -1), ('score', '0')):
                posts[:] = [dict(public(10), **{key: value})]
                blocked('dispatch', 'history_unverified')
            for actual, alias in (('author', 'name'), ('text', 'content')):
                row = public(10)
                row[alias] = row.pop(actual)
                posts[:] = [row]
                blocked('dispatch', 'history_unverified')
            posts[:] = [public(11), public(10)]
            blocked('dispatch', 'history_unverified')
            posts[:] = [public(10, ts=now - 100), public(11, ts=now - 101)]
            blocked('dispatch', 'history_unverified')
            posts[:] = [public(i, ts=now - 100) for i in range(1, 101)]
            blocked('dispatch', 'history_coverage_unverified')
            posts[:] = [public(i, ts=now - (330 if i == 1 else 100)) for i in range(1, 101)]
            assert invoke('preview')['lane'] == 'eligible'
            posts[:] = [listing, public(11, shop, now - 329, thread=5, role='buyer'), public(12, shop, now - 328, role='market'), public(13, shop, now - 327, round_number=3)]
            assert invoke('preview')['lane'] == 'eligible'
            posts.append(public(14, shop, now - 326, thread=5))
            blocked('dispatch', 'cooldown')
            posts[:] = [listing, public(11, shop, now - 330, thread=5)]
            assert invoke('preview')['lane'] == 'eligible'
            posts[:] = [listing]
            flags['get_timeout'] = True
            before = gets.count('/api/forum')
            try:
                invoke('dispatch')
            except httpx.ReadTimeout:
                pass
            else:
                raise AssertionError('expected GET timeout')
            assert gets.count('/api/forum') == before + 1 and not sends
            del flags['get_timeout']

            query('DELETE FROM identity')
            blocked('preview', 'award_schema_unverified')
            query('INSERT INTO identity VALUES (1,?,?)', (shop, '0x' + '0' * 40))
            blocked('preview', 'award_schema_unverified')
            query('UPDATE identity SET wallet=?', (wallet,))
            query('ALTER TABLE event RENAME COLUMN details TO legacy_details')
            blocked('preview', 'award_schema_unverified')
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('DROP TABLE event')
                db.executescript(logic['BASELINE_SCHEMA'])
            for alias in ('old_award', 'first_purchase_bonus_grant'):
                query('CREATE TABLE ' + alias + ' (amount INTEGER)')
                blocked('preview', 'award_schema_unverified')
                query('DROP TABLE ' + alias)
            query('INSERT INTO account VALUES (?,?)', ('fixture-owner', now))
            query('''INSERT INTO sale (id, owner, unit, sku, base, cost, price, discount, spent, shop_url, wallet, created,
                     digest, jwt, expected_wei, fee_wei, gas_cap_wei, fee_wallet, grade, status)
                     VALUES ('fixture-sale','fixture-owner','fixture-unit','fixture-sku',10,0,10,0,0,?,?,?,'fixture-digest',
                     'fixture-jwt','1','0','0',?,'fixture-grade','issued')''', (base, wallet, now, wallet))
            assert award_absent() and invoke('preview') == preview
            for status in ('settled', 'refunded'):
                query('UPDATE sale SET status=?', (status,))
                blocked('preview', 'award_schema_unverified')
                blocked('dispatch', 'award_schema_unverified')
                assert award_absent()
            query('CREATE TABLE welcome_award (amount INTEGER)')
            query('INSERT INTO welcome_award VALUES (5000)')
            blocked('preview', 'award_schema_unverified')
            query('DROP TABLE welcome_award')
            query(logic['AWARD_SCHEMA'])
            assert invoke('preview') == preview
            with closing(sqlite3.connect(path)) as db, db:
                db.executemany('INSERT INTO welcome_award VALUES (?,?,?,?,?)', [(f'0x{i:040x}', f'fixture-sale-{i}', 5000, now, i) for i in range(10)])
            assert invoke('preview')['lane'] == 'budget_exhausted'
            blocked('dispatch', 'budget_exhausted')
            query('DELETE FROM welcome_award WHERE earned_event_id<>0')
            query('UPDATE welcome_award SET amount=300')
            assert invoke('preview') == preview and query('SELECT amount FROM welcome_award') == [(300,)]
            for invalid_amount in (0, -1, 5001, 1.25):
                with closing(sqlite3.connect(path)) as db, db:
                    db.execute('PRAGMA ignore_check_constraints=ON')
                    db.execute('UPDATE welcome_award SET amount=?', (invalid_amount,))
                blocked('preview', 'award_state_invalid')
                blocked('dispatch', 'award_state_invalid')
            query('UPDATE welcome_award SET amount=300')
            assert query('SELECT amount FROM welcome_award') == [(300,)]
            query('UPDATE sale SET status=?', ('issued',))
            query('DROP TABLE welcome_award')
            assert award_absent() and invoke('preview') == preview

            for status, created, post, reason in (
                ('posted', now - 1, 7, 'cooldown'),
                ('unknown', now - 400, None, 'journal_busy'),
                ('sending', now, None, 'journal_busy'),
            ):
                flags['after_forum'] = lambda: legacy(status, created, post)
                blocked('dispatch', reason)
                assert query('SELECT id,status,post FROM forum_publication') == [('legacy', status, post)]
                query('DELETE FROM forum_publication')
            for version in ('v1', 'v2'):
                legacy('declined', now - 400, prefix=logic['campaign_prefix'](policy['id'], version))
                blocked('dispatch', 'campaign_already_attempted')
                query('DELETE FROM forum_publication')
            flags['after_forum'] = lambda: approve(approved_fingerprint=None)
            blocked('dispatch', 'approval_changed')
            approve(approved_fingerprint=fingerprint)
            flags['after_forum'] = lambda: policy_path.write_bytes(policy_raw + b' ')
            blocked('dispatch', 'policy_changed')
            policy_path.write_bytes(policy_raw)
            short_policy = dict(policy, end=now + 2)
            short_raw = json.dumps(short_policy).encode()
            policy_path.write_bytes(short_raw)
            snapshot['policy_sha256'] = hashlib.sha256(short_raw).hexdigest()
            approve()
            short_fingerprint = invoke('preview')['fingerprint']
            approve(approved_fingerprint=short_fingerprint)
            flags['after_forum'] = lambda: clock.__setitem__(0, now + 2)
            blocked('dispatch', 'policy_inactive')
            clock[0] = now
            policy_path.write_bytes(policy_raw)
            snapshot['policy_sha256'] = hashlib.sha256(policy_raw).hexdigest()
            approve(approved_fingerprint=fingerprint, valid_until=now + 2)
            flags['after_forum'] = lambda: clock.__setitem__(0, now + 2)
            blocked('dispatch', 'approval_stale')
            clock[0] = now
            approve(approved_fingerprint=fingerprint)
            assert award_absent() and not sends and query('SELECT * FROM forum_publication') == []
            assert invoke('dispatch') == {'status': 'posted'}
            assert award_absent() and len(sends) == 1 and query('SELECT status,post FROM forum_publication') == [('posted', 222)]
            blocked('dispatch', 'campaign_already_attempted')
            assert len(sends) == 1
            query('DELETE FROM forum_publication')
            flags['post_timeout'] = True
            assert invoke('dispatch') == {'status': 'unknown'} and len(sends) == 2
            journal, = query('SELECT shop,round,anchor,thread,content,created,status,reconcile_after,post FROM forum_publication')
            assert journal == (shop, 4, 10, None, text, now, 'unknown', now + 330, None)
            blocked('dispatch', 'journal_busy')
            assert invoke('preview')['lane'] == 'journal_busy' and len(sends) == 2

            # Exercise the legacy reconciliation key against official forum records.
            matching = public(222, shop, now, text=text)
            candidates = [
                public(10, shop, now, text=text), public(11, 'other', now, text=text),
                public(12, shop, now, role='buyer', text=text), public(13, shop, now, role='market', text=text),
                public(14, shop, now, round_number=3, text=text), public(15, shop, now, thread=5, text=text),
                public(16, shop, now), public(17, shop, now - 1, text=text), matching,
            ]
            expected_shop, expected_round, anchor, thread, content, created, _, _, _ = journal
            matches = [row['id'] for row in candidates if (row['author'], row['role'], row['round'], row['thread'], row['text']) == (expected_shop, 'shop', expected_round, thread, content) and row['id'] > anchor and row['ts'] >= created]
            assert matches == [222]
            assert set(gets) == {'/api/shops', '/api/agents', '/api/forum'}
            assert award_absent() and query('SELECT status FROM sale') == [('issued',)]
    print('v3 mock selftest passed')
