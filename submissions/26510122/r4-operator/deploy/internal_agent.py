"""Administrative runner for the official R4 agent in a private test workspace.

No market business logic lives here. The agent authors tools through official
forge_tool. There is no public listener or market registration. Tools receive no
live market token, and every tool invocation runs its test rather than live code.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import time
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--operator', type=Path, required=True)
    parser.add_argument('--session', type=Path, required=True)
    parser.add_argument('--task', type=Path, required=True)
    args = parser.parse_args()
    op, session = args.operator.resolve(), args.session.resolve()
    root = session / 'agent-work'
    source = op.parent / 'round-4'
    os.umask(0o077)
    root.mkdir(exist_ok=True)
    (root / 'logs').mkdir(exist_ok=True)
    if not (root / 'tools').exists():
        shutil.copytree(source / 'tools', root / 'tools')
    if not (root / 'docs').exists():
        shutil.copytree(session / 'docs', root / 'docs')
    cfg = json.loads((source / 'agent.json').read_text())
    assignment = args.task.read_text()
    cfg['goal'] = (
        '현재 공개 영업은 중지됐다. 실제 기능을 내부에서 구현·검증하는 유지보수 실행이다. '
        '새 가입·광고·실제 매입·실제 송금·실제 정산은 하지 않는다. 시장 읽기부터 반복하지 말고 '
        '아래 작업을 최우선으로 수행하라. 영업 도구와 테스트 코드는 네가 forge_tool로 직접 작성한다. '
        '운영자는 영업 코드를 제공하지 않는다.\n\n이번 작업:\n' + assignment +
        '\n\n아래 기존 정책의 비율·권리·환불 의무는 유지하라:\n' + cfg['goal']
    )
    (root / 'agent.json').write_text(json.dumps(cfg, ensure_ascii=False, indent=2))
    credentials = json.loads((session / 'model-session.json').read_text())
    sys.path.insert(0, str(op / 'kit'))
    import agent_kit as official
    import maroo

    # Ephemeral signing identities exist only in memory and are never registered.
    # The actual shop/buyer key files are never loaded by this runner.
    keys = {'shop': maroo.Wallet.generate(), 'buyer': maroo.Wallet.generate()}

    class TestOnlySigner(official.Signer):
        def do(self, request):
            if request.get('op') == 'pay' and not request.get('testing'):
                raise PermissionError('internal maintenance forbids live payment')
            return super().do(request)

    signer = TestOnlySigner(keys, root)
    tool_ctx = {'name': credentials['name'], 'market': 'https://market.ourolabs.ai',
                'shop_url': credentials['shop_url'], 'tokens': {},
                'addresses': {k: v.address for k, v in keys.items()}, 'signer': signer}
    model_ctx = {'tokens': {'shop': credentials['token']}}

    class TestOnlyToolbox(official.Toolbox):
        def call(self, name, tool_args):
            # The official test runner sets kit.testing=True. No production
            # operation is executed by a model request to call a tool.
            return self.run(name, 'test', tool_args)

        def run(self, name, mode, tool_args=None, d=None):
            if mode != 'test':
                raise PermissionError('only official test mode is allowed')
            folder = d or self.tools[name]['dir']
            perm = official.forge_runner.parse_permission((folder / 'permission.yml').read_text()).get('permission') or {}
            self.ctx['deny_hosts'] = list(perm.get('network') or [])
            return super().run(name, mode, tool_args, d)

        def forge(self, forge_args):
            perm = forge_args.get('permission') or {}
            if perm.get('exec'):
                return 'internal maintenance: permission.exec is not allowed'
            # Tests must mock external data. The model desk is reached by the
            # parent Model only; forged tools have no external network access.
            if any(host not in ['market.ourolabs.ai', 'rpc-testnet.maroo.io'] for host in perm.get('network') or []):
                return 'internal maintenance: only official market/RPC hosts may be declared; all external networking is blocked during tests, so mock HTTP'
            for path in perm.get('write') or []:
                if path in ['.', ''] or path.startswith(('docs', 'agent.json', 'logs')):
                    return 'internal maintenance: write only specific ledger/test/card paths, not docs/config/logs'
            return super().forge(forge_args)

    toolbox = TestOnlyToolbox(root, tool_ctx)
    class MaintenanceModel(official.Model):
        def complete(self, messages, max_tokens=6000, timeout=240):
            # The original transport has a 60s socket timeout, shorter than the
            # class model's observed code-generation latency. This adapter only
            # changes transport timeout/output budget; the official kit and
            # system instructions remain unchanged.
            key = next(t for t in self.ctx['tokens'].values() if t)
            request = urllib.request.Request(self.base + '/chat/completions',
                data=json.dumps({'model': self.model, 'messages': messages,
                                 'max_tokens': max_tokens}).encode(),
                headers={'authorization': 'Bearer ' + key,
                         'content-type': 'application/json',
                         'user-agent': 'r4-internal-maintenance/1'})
            started = time.time()
            with urllib.request.urlopen(request, timeout=timeout) as response:
                result = json.load(response)
            print(json.dumps({'model_call_seconds': round(time.time()-started, 2),
                              'usage': result.get('usage')}, ensure_ascii=False), flush=True)
            return result['choices'][0]['message'].get('content') or ''

    model = MaintenanceModel(cfg, 'https://market.ourolabs.ai', model_ctx)
    mind = official.Mind(root, cfg, model, toolbox, tool_ctx, ['shop'])
    # Public protocol documents were captured by the operator, not invented.
    mind.directory = {'documentationUrl': 'docs/ROUND4.md',
                      'conventions': 'Read docs/clearing.json, docs/bank.json, docs/customer.py as local reference files.'}
    event = official.Event('human', '가게 주인: 내부 기능 검증', assignment[:1400])
    mind.deliver(event)
    print(json.dumps({'phase': args.task.name, 'started': time.time(),
                      'workspace': str(root), 'public_service_started': False,
                      'real_wallets_loaded': False, 'live_payments_allowed': False}, ensure_ascii=False), flush=True)
    try:
        mind.run_once(mind.fresh())
    finally:
        signer.http.shutdown()
        signer.http.server_close()
    result = {'phase': args.task.name, 'finished': time.time(), 'answer': event.answer,
              'tools': sorted(toolbox.tools), 'live_payments_allowed': False,
              'public_service_started': False}
    (session / (args.task.stem + '-result.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
