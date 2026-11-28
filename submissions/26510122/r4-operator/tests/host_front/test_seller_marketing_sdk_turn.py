"""Offline SDK one-turn smoke with the original Mind and a stubbed publisher."""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import time

import catalogue_asgi_support as support


def exercise(operator, built):
    import agent_kit
    import forum_campaign_operator as campaign

    release, runtime, frontend, *_ = built
    host = support.module('tested_seller_marketing_turn', frontend / 'seller_marketing_host.py')
    binding = json.loads(support.protected(frontend / 'MARKETING-BINDING.json'))
    sku, grade = 'G00000001', 'C'
    decision = {'action': 'spotlight', 'sku': sku, 'grade': grade}
    requests = []
    model_requests = []
    source = {'schema': 'synthetic turn smoke', 'valid_until': time.time() + 100,
              'items': [{'sku': sku, 'grade': grade, 'spotlight_eligible': True}],
              'spotlight_allowed': True, 'reply_options': []}

    class PublisherStub:
        def run(self, name, mode, args, *, d):
            if name != 'forum_marketing' or mode != 'call' or d != runtime / 'forum_marketing':
                raise AssertionError('unexpected native dispatch')
            requests.append(args['action'])
            if args['action'] == 'reconcile':
                return {'ok': True, 'result': {'status': 'nothing_to_reconcile'}}
            if args['action'] == 'slate_context':
                return {'ok': True, 'result': source}
            if args['action'] == 'publish' and args['decision'] == decision:
                return {'ok': True, 'result': {'status': 'synthetic_selected', 'sku': sku, 'grade': grade}}
            raise AssertionError('unexpected publication call')

    class SelectionStub:
        def complete(self, messages, **kwargs):
            model_requests.append([item['content'] for item in messages])
            return json.dumps({'thought': 'Synthetic selection only.', 'action': 'forum_marketing',
                               'args': {'action': 'publish', 'decision': decision}})

    with tempfile.TemporaryDirectory(prefix='sdk-seller-turn-') as tmp:
        root = Path(tmp)
        fixtures = {'campaign': campaign,
                    'privacy': SimpleNamespace(public_source=lambda envelope, now: envelope),
                    'scope': SimpleNamespace(ordinary_context=lambda official, source_dir, pins, native: native,
                                             validate_scope=lambda full, visible: visible)}
        components = (
            agent_kit, root, {'llm': {'base': 'market'}}, SelectionStub(), PublisherStub(),
            {'name': 'outseop-r4', 'market': 'https://fixture.invalid', 'tokens': {}, 'addresses': {}},
        )
        cycle = host.SDKForumCycle(
            root, runtime, components, fixtures, binding, SimpleNamespace(generation=binding['generation'], enabled=lambda: True),
            customer_active=lambda: False, maintenance=lambda: False, refresh=lambda: None)
        result = cycle(job=1, recovery_only=False, deadline=time.monotonic() + 10)
        session, = cycle.sessions.iterdir()
        sdk_actions = [json.loads(line)['action'] for line in (session/'logs/react.jsonl').read_text().splitlines()]
        if any('This run is almost over' in msg for req in model_requests for msg in req):
            raise AssertionError('SDK nudged the selection model to sleep before its first decision')
        assert len(model_requests) == result['model_calls'] == result['synthetic_terminal_calls'] == 1
        assert requests == ['reconcile', 'slate_context', 'publish']
        assert sdk_actions == ['forum_marketing', 'sleep'] and result['publication_attempts'] == 1
        assert result['status'] == 'synthetic_selected'
    return {'release': release['release_id'], 'original_sdk_actions': sdk_actions, 'model_stub_decisions': 1,
            'actual_model_calls': 0, 'synthetic_terminal_calls': 1, 'publishing_calls_to_stub': 1,
            'actual_posts': 0, 'premature_end_nudge': False, 'production_modified': False}


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument('--operator', type=Path, required=True)
    cli.add_argument('--build-receipt', type=Path, required=True)
    cli.add_argument('--build-sha256', required=True)
    cli_args = cli.parse_args()
    operator = cli_args.operator.resolve(strict=True)
    build = support.verify_build(operator, cli_args.build_receipt.resolve(strict=True),
                                 cli_args.build_sha256, expected_semantic=19)
    sys.path.insert(0, str(operator / 'deploy'))
    print(json.dumps(exercise(operator, build), sort_keys=True))


if __name__ == '__main__':
    main()
