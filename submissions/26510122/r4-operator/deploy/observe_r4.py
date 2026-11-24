"""Read-only deployment evidence. Never forge, quote, procure, sign, or pay."""
from pathlib import Path
from collections import Counter
import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.request

OP = Path(__file__).resolve().parents[1]
AGENT = OP.parent/'round-4'
PRIVATE = OP/'runtime'
NAME = 'outseop-r4'
MARKET = 'https://market.ourolabs.ai'
sys.path.insert(0, str(OP/'kit'))
import maroo


def get(path):
    url = path if path.startswith('https://') else MARKET+path
    with urllib.request.urlopen(url, timeout=15) as response:
        return json.load(response)


def jsonlines(path):
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass
    return rows


def main():
    now = time.time()
    props = subprocess.check_output(['systemctl','--user','show','ourolabs-market-r4.service',
        '-p','ActiveState','-p','SubState','-p','MainPID','-p','NRestarts',
        '-p','MemoryCurrent','-p','MemoryPeak','-p','TasksCurrent'],text=True)
    service = dict(line.split('=',1) for line in props.splitlines() if '=' in line)
    registry = [r for r in get('/api/agents').get('agents',[]) if r.get('name')==NAME]
    assert len(registry)<=1, 'More than one registry identity'
    card, card_error = {}, None
    if registry:
        try:
            card = get(registry[0]['card'])
        except Exception as error:
            card_error = {'type':type(error).__name__,'http_status':getattr(error,'code',None)}
    kitlog = (AGENT/'logs/agent-kit.log').read_text()
    own_urls = {row['card'].removesuffix('/.well-known/agent-card.json') for row in registry}
    own_urls.update(re.findall(r'\[tunnel\] (https://[a-z0-9-]+\.trycloudflare\.com)', kitlog))
    match = re.search(r'shop wallet (0x[0-9a-fA-F]{40})',kitlog)
    wallet = match.group(1) if match else None
    balance = None
    balance_error = None
    if wallet:
        try:
            balance = maroo.balance(wallet)/10**15
        except Exception as error:
            balance_error = type(error).__name__
    forge = jsonlines(AGENT/'logs/forge.jsonl')
    react = jsonlines(AGENT/'logs/react.jsonl')
    tools = []
    for folder in sorted((AGENT/'tools').iterdir()):
        if not folder.is_dir() or folder.name.startswith('.'):
            continue
        proof = folder/'forge.json'
        if not proof.exists():
            tools.append({'name':folder.name,'provenance':False})
            continue
        data = json.loads(proof.read_text())
        tools.append({'name':folder.name,'version':data.get('version'),
            'provenance':True,'hashes_match':all(hashlib.sha256((folder/f).read_bytes()).hexdigest()==h
                for f,h in data['sha256'].items()),
            'passed_forge_record':any(r.get('tool')==folder.name and r.get('version')==data.get('version') and r.get('passed') is True for r in forge)})
    start = json.loads((PRIVATE/'deployment-baseline-20261125.json').read_text())['at']
    saved = PRIVATE/'ledger-observation.json'
    own_rows = []
    if saved.exists() and json.loads(saved.read_text()).get('schema') == 2:
        old = json.loads(saved.read_text())
        cursor = old['cursor']
        own_rows = old['own_rows']
        coverage_start = old['coverage_start_at']
    else:
        if saved.exists():
            backup = saved.with_name('ledger-observation-before-url-index.json')
            if not backup.exists():
                backup.write_bytes(saved.read_bytes())
        tail = get('/api/ledger?after=-1')
        cursor = max(0,tail[-1]['seq']-1000) if tail else 0
        while True:
            batch = get('/api/ledger?after='+str(cursor))
            if not batch or batch[0]['ts']<=start or cursor==0:
                break
            cursor = max(0,cursor-2000)
        coverage_start = batch[0]['ts'] if batch else now
    for _ in range(12):
        batch = get('/api/ledger?after='+str(cursor))
        if not batch:
            break
        for entry in batch:
            encoded = json.dumps(entry.get('data') or {})
            if entry.get('ts',0)>=start and (NAME in encoded or
                    any(url in encoded for url in own_urls) or wallet and wallet.lower() in encoded.lower()):
                own_rows.append(entry)
        cursor = batch[-1]['seq']
        if batch[-1]['ts']>=time.time()-4 or len(batch)<500:
            break
    own_rows = list({r['seq']:r for r in own_rows}.values())
    ledger = {'schema':2,'cursor':cursor,'coverage_start_at':coverage_start,'deployment_start_at':start,
              'own_rows':own_rows}
    saved.write_text(json.dumps(ledger,ensure_ascii=False,indent=2)+'\n')
    paid = [r for r in own_rows if r['kind']=='settle' and
            (r.get('data') or {}).get('shop') in own_urls | {NAME}]
    cfg = json.loads((AGENT/'agent.json').read_text())
    baseline = json.loads((PRIVATE/'deployment-baseline-20261125.json').read_text())
    report = {'observed_at':now,'service':service,'registry':registry,
        'card':{'name':card.get('name'),'skills':card.get('skills',[]),
                'wallets':card.get('wallets',{})},
        'public_card_fetch_error':card_error,
        'wallet':wallet,'wallet_matches_public_card':(bool(wallet and
            str((card.get('wallets') or {}).get('shop','')).lower()==wallet.lower()) if card else None),
        'chain_balance_credits':balance,'chain_read_error_type':balance_error,
        'class_model_configured':cfg.get('llm')=={'base':'market'},
        'class_model_responded':bool(react),
        'agent_config_unchanged':hashlib.sha256((AGENT/'agent.json').read_bytes()).hexdigest()==baseline['agent_config_sha256'],
        'tools':tools,'forge_attempts':len(forge),'forge_passes':sum(r.get('passed') is True for r in forge),
        'forge_failures':sum(r.get('passed') is not True for r in forge),
        'react_actions':dict(Counter(r.get('action') for r in react)),
        'recent_actions':[{'ts':r.get('ts'),'action':r.get('action')} for r in react[-10:]],
        'own_public_ledger_counts':dict(Counter(r['kind'] for r in own_rows)),
        'normal_sales_verified':len(paid),'sale_proofs':paid,
        'settlement_verification_scope':'Official public-ledger entries; individual settlement RPC proofs are not checked by this observer.',
        'public_ledger_covers_deployment_start':coverage_start<=start,
        'operator_business_tools_written':False,
        'scope':'Registry/card/RPC and public-ledger observations only. Grants are not sales. Forge tests are not real trades; human app instructions are not customer orders.'}
    path = PRIVATE/'observed-state.json'
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    temp.replace(path)
    print(json.dumps({k:v for k,v in report.items() if k not in ['sale_proofs']},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
