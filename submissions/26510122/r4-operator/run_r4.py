#!/usr/bin/env python3
"""Administrative launcher only; market tools remain the agent's own work."""
import argparse
import ast
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import sys
import types

ROOT = Path(__file__).resolve().parent
SHOP_NAME = 'outseop-r4'
KIT = ROOT / 'kit'
AGENT = ROOT.parent / 'round-4'
PYTHON = ROOT / '.venv/bin/python'
OWNER = Path(os.environ.get('MARKET_OWNER_FILE') or (Path.home() / '.config/ourolabs-market/owner-code'))


def check():
    meta = json.loads((ROOT / 'sources/upstream.json').read_text())
    for row in meta['files']:
        blob = (KIT / row['name']).read_bytes()
        digest = hashlib.sha1(b'blob ' + str(len(blob)).encode() + b'\0' + blob).hexdigest()
        if digest != row['upstream_git_blob_sha']:
            raise RuntimeError('Official kit file differs from upstream: ' + row['name'])
    parsed = ast.parse((KIT / 'agent_kit.py').read_text())
    baseline = next(ast.literal_eval(n.value) for n in parsed.body if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == 'STARTER_AGENT' for t in n.targets))
    config = json.loads((AGENT / 'agent.json').read_text())
    changed = sorted(k for k in baseline if baseline[k] != config.get(k))
    if set(config) != set(baseline) or set(changed) != {'persona', 'goal', 'llm'}:
        raise RuntimeError('Human edits must be limited to persona, goal and model')
    if config['llm'] != {'base': 'market'}:
        raise RuntimeError('This prepared launch uses the class model desk only')
    ignores = (AGENT / '.gitignore').read_text().splitlines()
    if not all(x in ignores for x in ['*.key', '.market/', '.kit/', 'meshkit.json']):
        raise RuntimeError('Official private-file exclusions missing')
    if any(x.strip() in ['logs', 'logs/', '*.log', '*.jsonl'] for x in ignores):
        raise RuntimeError('Required agent and forge logs must remain submit-able')
    if '<script src="/miniapp.js"></script>' not in (AGENT / 'app/index.html').read_text():
        raise RuntimeError('Official mini app SDK script missing')
    sys.path.insert(0, str(KIT))
    import agent_kit
    ctx = {'tokens': {}, 'addresses': {}}
    # Build routes only: no serving, joining, model request or wallet creation.
    app = agent_kit.agent_app(AGENT, SHOP_NAME, None, types.SimpleNamespace(ctx=ctx), [None])
    tools = []
    for folder in sorted((AGENT / 'tools').iterdir()):
        if not folder.is_dir() or folder.name.startswith('.'):
            continue
        provenance = folder / 'forge.json'
        if not provenance.is_file():
            raise RuntimeError('Tool lacks agent forge provenance: ' + folder.name)
        record = json.loads(provenance.read_text())
        for filename, expected in record['sha256'].items():
            if hashlib.sha256((folder / filename).read_bytes()).hexdigest() != expected:
                raise RuntimeError('Tool changed after forge: ' + folder.name)
        tools.append(folder.name)
    return {'official_kit': agent_kit.KIT_VERSION, 'upstream_files_verified': len(meta['files']),
            'human_changed_fields': changed, 'model': 'class market model desk; no personal API key',
            'market_default': 'https://market.ourolabs.ai', 'shop_name_default': SHOP_NAME,
            'a2a_sdk': importlib.metadata.version('a2a-sdk'), 'a2a_routes_constructed': bool(app),
            'agent_directory': '../round-4', 'operator_directory': '.', 'paths_relative_to_operator': True,
            'cloudflared_present': bool(shutil.which('cloudflared')), 'saved_owner_code_present': OWNER.is_file(),
            'agent_generated_tools': tools, 'logs_excluded_from_submission': False,
            'market_registered_or_model_called_by_check': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['check', 'run'])
    parser.add_argument('--name', default=SHOP_NAME)
    parser.add_argument('--market', default='https://market.ourolabs.ai')
    parser.add_argument('--owner-file', type=Path, default=OWNER)
    parser.add_argument('--public-url', help='Existing HTTPS endpoint forwarded to this process; otherwise use cloudflared')
    parser.add_argument('--port', type=int, help='A2A local port, useful with an existing server reverse proxy')
    parser.add_argument('--app-port', type=int, default=8800)
    parser.add_argument('--app-tunnel', action='store_true')
    parser.add_argument('--enable-procurement', action='store_true', help='Enable validated R3-method stock planning and execution')
    parser.add_argument('--procurement-lines', type=int, choices=range(1,11), default=10, help='Operator line limit per supply window; start with 3 for a canary')
    args = parser.parse_args()
    result = check()
    if args.command == 'check':
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if not PYTHON.is_file():
        raise SystemExit('Install this folder\'s virtual environment before running')
    if not args.public_url and not shutil.which('cloudflared'):
        raise SystemExit('A public URL or cloudflared is required before opening the shop')
    if not args.owner_file.is_file():
        raise SystemExit('Market owner credential missing. Sign in at https://market.ourolabs.ai/join and save the claim code locally, never in chat or this repository.')
    owner = args.owner_file.read_text().strip()
    if not owner:
        raise SystemExit('Market owner credential is empty')
    # Never copy the owner code into the submission, arguments or logs.
    env = dict(os.environ)
    env.pop('MARKET_OWNER', None)
    env['AGENT_LLM_BASE'] = 'market'
    env.pop('AGENT_LLM_KEY', None)
    env.pop('AGENT_LLM_MODEL', None)
    os.umask(0o077)
    if args.name != SHOP_NAME or args.market.rstrip('/') != 'https://market.ourolabs.ai':
        raise SystemExit('The preserved R4 identity and market cannot be changed by this launcher')
    managed = AGENT / 'codex-r4/managed_launcher.py'
    if not managed.is_file():
        raise SystemExit('The verified managed runtime has not been installed')
    command = [str(PYTHON), str(managed), 'run', '--operator-dir', str(ROOT),
               '--agent-root', str(AGENT), '--owner-file', str(args.owner_file)]
    command += ['--public-url', args.public_url] if args.public_url else ['--tunnel']
    if args.port:
        command += ['--port', str(args.port)]
    if args.enable_procurement:
        command += ['--enable-procurement', '--procurement-lines', str(args.procurement_lines)]
    if args.app_tunnel:
        raise SystemExit('The managed runtime keeps private app and financial paths separate')
    print('보존된 R4 가게를 시작합니다. 도구 구현은 Codex GPT-6.2 Sol, 운영 판단은 수업 모델입니다.', flush=True)
    print('Ctrl-C로 종료합니다. 가게 지갑과 상태 폴더를 유지해야 같은 가게로 다시 실행할 수 있습니다.', flush=True)
    os.execve(str(PYTHON), command, env)


if __name__ == '__main__':
    main()
