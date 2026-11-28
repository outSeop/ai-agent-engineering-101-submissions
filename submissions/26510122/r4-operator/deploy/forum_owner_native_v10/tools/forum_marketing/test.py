import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx


def test(run, kit):
    scope = run.__globals__
    generation, token = 'a' * 64, 'b' * 64
    policy = {'schema': 'outseop-r4.marketing-owner.v1', 'active': True, 'generation': generation, 'token': token}
    held = {'status': 'hold'}
    transferred = {'status': 'marketing_transferred'}
    reconcile = {'action': 'reconcile'}
    publish = {'action': 'publish', 'decision': {'action': 'hold'}}
    markers = {'scheduler_generation': generation, 'operation_timeout': 4}
    fixture_parent = Path('state/r4-benefits')
    fixture_parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with TemporaryDirectory(dir=fixture_parent) as tmp:
        root = Path(tmp)
        relative = scope['POLICY']
        leaf = root / relative
        leaf.parent.mkdir(mode=0o700, parents=True)
        target = leaf.with_name('fixture.json')
        read_at = scope['read_policy_at']

        def put(path, value, mode=0o600):
            with path.open('w', encoding='utf-8') as handle:
                handle.write(value if isinstance(value, str) else json.dumps(value))
            path.chmod(mode)

        def fixture_reader():
            try:
                return read_at(root, relative)
            except (OSError, ValueError):
                return None

        fake_post = Mock(return_value=httpx.Response(200, json=transferred))
        fake_get = Mock(side_effect=AssertionError('unexpected synthetic GET'))
        with patch.dict(scope, {'read_policy': fixture_reader}), patch.object(httpx, 'post', fake_post), patch.object(httpx, 'get', fake_get):
            assert run(reconcile, kit) == held, 'missing policy'
            for malformed in ({**policy, 'active': False}, {**policy, 'active': 1}, '{',
                              {**policy, 'extra': 0}, {**policy, 'generation': 'A' * 64},
                              json.dumps(policy)[:-1] + ',"active":true}'):
                put(leaf, malformed)
                assert run(reconcile, kit) == held, 'inactive or malformed policy'
            put(leaf, policy, 0o644)
            assert run(reconcile, kit) == held, 'wrong policy mode'
            leaf.unlink()
            put(target, policy)
            leaf.symlink_to(target.name)
            assert run(reconcile, kit) == held, 'symlink policy'
            leaf.unlink()
            os.link(target, leaf)
            assert run(reconcile, kit) == held, 'hardlinked policy'
            leaf.unlink()
            alias = root / 'alias'
            alias.symlink_to(relative.parent, target_is_directory=True)
            try:
                assert read_at(root, Path('alias') / target.name) is None, 'symlink parent accepted'
            except OSError:
                pass
            fake_post.assert_not_called()
            put(leaf, policy)
            assert fixture_reader() == policy, 'secure synthetic policy fixture was not read'
            assert scope['request_tick'](policy) == transferred, 'synthetic HTTP 200 response rejected'
            fake_post.reset_mock()
            assert run({**reconcile, 'url': 'https://example.invalid', 'headers': {}, 'generation': 'ignored'}, kit) == transferred, 'reconcile dispatch failed'
            fake_post.assert_called_once_with('http://127.0.0.1:18812/_internal/r4-marketing/tick',
                                              json={'generation': generation},
                                              headers={'Authorization': 'Bearer ' + token},
                                              timeout=130, trust_env=False, follow_redirects=False)
            for response in (httpx.Response(201, json=transferred), httpx.Response(302, json=transferred),
                             httpx.Response(200, json={**transferred, 'extra': 1}),
                             httpx.Response(200, json={'status': 'nothing_to_reconcile'}),
                             httpx.Response(200, json={'status': 'unknown'}),
                             httpx.Response(200, content=b'{'),
                             httpx.Response(200, content=b'{"status":"unknown","status":"marketing_transferred"}')):
                fake_post.return_value = response
                assert run(reconcile, kit) == held, 'invalid IPC response accepted'
            fake_post.side_effect = httpx.ReadTimeout('synthetic timeout')
            assert run(reconcile, kit) == held
            fake_post.reset_mock()
            previous = scope['load_v9']()
            if previous.PARENT is None:
                previous.PARENT = previous.load_parent()
            parent = previous.PARENT
            original_market = parent.Market
            fake_kit = SimpleNamespace(name=parent.shop.SHOP, market='https://market.ourolabs.ai',
                                       shop_url='https://example.invalid', address=lambda role: '0x' + '1' * 40,
                                       testing=True)
            with patch.object(previous, 'run', side_effect=AssertionError('unexpected delegation')) as parent_run:
                assert run(publish, fake_kit) == held
                assert run({'action': 'mutate'}, fake_kit) == held
                assert run({**publish, **markers, 'scheduler_generation': 'c' * 64}, fake_kit) == held
                assert run({**publish, 'scheduler_generation': generation}, fake_kit) == held
                assert run({**publish, 'operation_timeout': 4}, fake_kit) == held
                assert run({'action': 'context', 'scheduler_extra': True}, fake_kit) == held
                for invalid in (True, False, float('nan'), float('inf'), float('-inf'), -1, 0, 41, 10**500, '4'):
                    assert run({**publish, **markers, 'operation_timeout': invalid}, fake_kit) == held
                parent_run.assert_not_called()
            fake_post.assert_not_called()

            def exercise_parent(args, supplied_kit):
                assert supplied_kit is fake_kit
                assert 'scheduler_generation' not in args and 'operation_timeout' not in args
                market = parent.Market(supplied_kit)
                assert isinstance(market, original_market)
                now = scope['monotonic']()
                if args.get('preset') == 'conservative':
                    assert type(market) is original_market and market.deadline > now + 30
                else:
                    assert type(market) is not original_market and now < market.deadline <= now + 4
                    with patch.object(original_market, 'window_page', autospec=True, return_value=[]) as page:
                        assert market.window_page(2, 1, now + 20) == []
                        page.assert_called_once_with(market, 2, 1, market.deadline)
                    market.deadline = now - 1
                    try:
                        market.timeout()
                    except parent.shop.Unavailable:
                        pass
                    else:
                        raise AssertionError('inherited timeout ignored clamp')
                return {'status': 'synthetic_' + args['action']}

            with patch.object(previous, 'run', side_effect=exercise_parent) as parent_run:
                for action in ('context', 'slate_context'):
                    public = {'action': action, 'preset': 'conservative'}
                    assert run(public, fake_kit) == {'status': 'synthetic_' + action}, 'public read delegation failed'
                    parent_run.assert_called_with(public, fake_kit)
                for original in (reconcile, publish, {'action': 'context'}, {'action': 'slate_context'}):
                    assert run({**original, **markers}, fake_kit) == {'status': 'synthetic_' + original['action']}, 'bounded parent delegation failed'
                    parent_run.assert_called_with(original, fake_kit)
                    assert parent.Market is original_market
            with patch.object(previous, 'run', side_effect=ValueError('synthetic parent error')):
                assert run({**publish, **markers}, fake_kit) == held
                assert parent.Market is original_market
            fake_get.assert_not_called()
            fake_post.assert_not_called()
