"""Small, expiring operator-bounded policy overrides; no network or model calls."""
import json,math
from pathlib import Path
PATH=Path('state/seller-meta-policy.json')
DEFAULT={'window_budget':12_000_000,'target_capital_share':.65,'epsilon':.30,'focus':'balanced'}
BOUNDS={'window_budget':(1_200_000,12_000_000),'target_capital_share':(.50,.70),'epsilon':(.20,.40)}
FOCUS=('balanced','replenishment','discovery')

def validate(config):
    if set(config)!=set(DEFAULT):raise ValueError('unknown or missing policy key')
    for key,(low,high) in BOUNDS.items():
        v=config[key]
        if type(v) not in (int,float) or not math.isfinite(v) or not low<=v<=high:raise ValueError('policy range: '+key)
    if type(config['window_budget']) is not int:raise ValueError('integer budget required')
    if config['focus'] not in FOCUS:raise ValueError('unknown focus')
    return config

def active(now,path=None):
    try:
        d=json.loads((path or PATH).read_text())
        if d.get('schema_version')!=1 or not d['at']<=now<d['expires_at'] or d['expires_at']-d['at']>14400:raise ValueError('expired or invalid policy')
        return {**validate(d['config']),'meta_version':d['version'],'meta_status':'active'}
    except (OSError,ValueError,KeyError,TypeError):
        return {**DEFAULT,'meta_version':None,'meta_status':'operator_default'}
