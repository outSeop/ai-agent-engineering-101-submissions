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
    assert run({'mode': 'dispatch'}, kit)['reason'] == 'offline_development'
    for field in ('text', 'url', 'amount', 'approval'):
        assert run({'mode': 'dispatch', field: 'fixture'}, kit)['reason'] == 'invalid_args'
    logic = run.__globals__
    execute, stop = logic['execute'], logic['Stop']
    market, shop, wallet = logic['MARKET'], logic['SHOP'], logic['WALLET']
    assert wallet == '0x5FDC134D790EFB72DF1bbb922F2b49fcADe349C6'
    now = 1795606517
    base = 'https://quiet-paper-cedar.trycloudflare.com'
    card = base + '/.well-known/agent-card.json'
    direct_card = {'roles': ['shop'], 'wallets': {'shop': wallet}, 'supportedInterfaces': [{'url': base}]}
    state = Path('state/r4-benefits')
    state.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix='notice-v2-test-', dir=state) as directory:
        root = Path(directory)
        path = root / logic['DB']
        policy_path = root / logic['POLICY']
        approval_path = root / logic['APPROVAL']
        policy = {'enabled': True, 'id': 'synthetic-campaign', 'start': now - 60, 'end': now + 40, 'lifetime_budget': 50000}
        policy_raw = json.dumps(policy).encode()
        policy_path.write_bytes(policy_raw)
        snapshot = {'shop': shop, 'round': 4, 'wallet': direct_card['wallets']['shop'], 'shop_url': direct_card['supportedInterfaces'][0]['url'], 'card_url': card, 'observed_at': now - 5, 'valid_until': now + 100, 'policy_sha256': hashlib.sha256(policy_raw).hexdigest(), 'approved_fingerprint': None}
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

        query("CREATE TABLE forum_publication (id TEXT PRIMARY KEY, shop TEXT, round INTEGER, thread INTEGER NULL, sku TEXT, content TEXT, anchor INTEGER, status TEXT CHECK(status IN ('sending','unknown','declined','posted')), fingerprint TEXT, created REAL, post INTEGER UNIQUE NULL, reconcile_after REAL DEFAULT 0)")
        query('PRAGMA journal_mode=WAL')

        def legacy(status, created, post=None):
            query('INSERT INTO forum_publication VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', ('legacy', shop, 4, 3, 'legacy-item', 'legacy-body', 1, status, 'legacy-fingerprint', created, post, created + 330 if status == 'unknown' else 0))

        def public(post_id, name='other', ts=None, thread=None, role='shop'):
            return {'id': post_id, 'name': name, 'role': role, 'round': 4, 'thread': thread, 'content': 'fixture', 'ts': now - 400 if ts is None else ts}

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
            posts[:] = [public(10)]
            preview = invoke('preview')
            assert set(preview) == {'status', 'lane', 'fingerprint', 'text'}
            assert preview['status'] == 'preview' and preview['lane'] == 'eligible'
            fingerprint, text = preview['fingerprint'], preview['text']
            assert all(term in text for term in ('outseop-r4', 'KST', '1%', '5%', '5,000', '50,000', '7일', '다음 구매', '재지급하지 않습니다'))
            assert wallet not in str(preview) and 'https://' not in str(preview)
            assert not sends and not tokens and query('SELECT * FROM forum_publication') == []
            blocked('dispatch', 'dispatch_unapproved')
            approve(approved_fingerprint=fingerprint[:-1] + ('0' if fingerprint[-1] != '0' else '1'))
            blocked('dispatch', 'approval_fingerprint_changed')
            approve(approved_fingerprint=fingerprint)
            for key, value, reason in (
                ('pubkey', '0x' + '0' * 40, 'shop_registry_unverified'),
                ('shop_url', 'https://new.trycloudflare.com', 'shop_registry_unverified'),
                ('roles', ['buyer', 'shop'], 'agent_registry_unverified'),
                ('card', 'https://new.trycloudflare.com/.well-known/agent-card.json', 'agent_registry_unverified'),
            ):
                flags[key] = value
                blocked('dispatch', reason)
                del flags[key]
            flags['forum_shape'] = {'posts': []}
            blocked('dispatch', 'history_unverified')
            del flags['forum_shape']
            for key, value in (('ts', True), ('ts', str(now)), ('round', '4'), ('role', 'merchant'), ('thread', False), ('id', True)):
                posts[:] = [dict(public(10), **{key: value})]
                blocked('dispatch', 'history_unverified')
            posts[:] = [public(i, ts=now - 100) for i in range(1, 101)]
            blocked('dispatch', 'history_coverage_unverified')
            posts[:] = [public(i, ts=now - 400 if i == 1 else now - 100) for i in range(1, 101)]
            assert invoke('preview')['lane'] == 'eligible'
            posts[:] = [public(10), public(11, shop, now - 329, thread=5, role='buyer')]
            blocked('dispatch', 'cooldown')
            posts[:] = [public(10)]
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
            query('CREATE TABLE old_award (amount INTEGER)')
            blocked('preview', 'award_schema_unverified')
            query('DROP TABLE old_award')
            query('CREATE TABLE welcome_award (amount INTEGER)')
            query('INSERT INTO welcome_award VALUES (50000)')
            assert invoke('preview')['lane'] == 'budget_exhausted'
            blocked('dispatch', 'budget_exhausted')
            query('UPDATE welcome_award SET amount=300')
            assert invoke('preview') == preview and query('SELECT amount FROM welcome_award') == [(300,)]
            for status, created, post, reason in (
                ('posted', now - 1, 7, 'cooldown'),
                ('unknown', now - 400, None, 'journal_busy'),
                ('sending', now, None, 'journal_busy'),
            ):
                flags['after_forum'] = lambda: legacy(status, created, post)
                blocked('dispatch', reason)
                assert query('SELECT id,status,post FROM forum_publication') == [('legacy', status, post)]
                query('DELETE FROM forum_publication')
            flags['after_forum'] = lambda: approve(approved_fingerprint=None)
            blocked('dispatch', 'approval_changed')
            approve(approved_fingerprint=fingerprint)
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
            assert not sends and query('SELECT * FROM forum_publication') == []
            assert invoke('dispatch') == {'status': 'posted'}
            assert len(sends) == 1 and query('SELECT status,post FROM forum_publication') == [('posted', 222)]
            blocked('dispatch', 'campaign_already_attempted')
            assert len(sends) == 1
            query('DELETE FROM forum_publication')
            flags['post_timeout'] = True
            assert invoke('dispatch') == {'status': 'unknown'} and len(sends) == 2
            assert query('SELECT shop,round,anchor,thread,content,created,status,reconcile_after FROM forum_publication') == [(shop, 4, 10, None, text, now, 'unknown', now + 330)]
            blocked('dispatch', 'journal_busy')
            assert invoke('preview')['lane'] == 'journal_busy' and len(sends) == 2
            assert set(gets) == {'/api/shops', '/api/agents', '/api/forum'}
            assert query('SELECT amount FROM welcome_award') == [(300,)]
    print('v2 mock selftest passed')
