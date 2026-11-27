"""External TEST-ONLY original runtime/fixture contract guards. No business implementation.
Load with importlib from the staged selftest. No Model/network/wallet/runtime mutation.
"""
from pathlib import Path
from hashlib import sha256
import ast
import inspect
from contextlib import closing
import json
import re
import sqlite3

OP=next(p for p in Path(__file__).resolve().parents if (p/'kit/agent_kit.py').exists())
ORIGINAL_CODE=OP.parent/'round-4/codex-r4'
SOURCE_PINS={'stock_runtime.py': 'f44540cbd525ccb9cf67371a7363c45a912bfe2cfb661ca93726f5c338e44388', 'test_procurement.py': 'a0e6e4c13724d2b582e4e2c4000851793190d8987c87601072b5f59434f486dc', 'fixture.py': '3583926d5154ede9bbc6330103930967b452c04546a19a6078864abfe931b012'}

def _exact_source(name,path=None):
    path=Path(path) if path is not None else ORIGINAL_CODE/name
    raw=path.read_bytes()
    assert sha256(raw).hexdigest()==SOURCE_PINS[name], 'original source contract changed'
    return path,raw

def legacy_public_model_view(context, *, source_path=None):
    """Execute the exact original public_model_view AST, without replacing it with a stub.
    The function only depends on real re and builtins; importing the whole runtime
    would add unrelated broker loader dependencies inside the isolated SDK root.
    """
    path,raw=_exact_source('stock_runtime.py',source_path)
    tree=ast.parse(raw,filename=str(path))
    node,=[x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='public_model_view']
    ns={'re':re}
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),ns)
    return ns['public_model_view'](context)

def assert_legacy_context(result, *, expected_sku=None, expected_qty=1, source_path=None):
    assert isinstance(result,dict) and result.get('status')=='draft', 'no genuine draft returned'
    context=result.get('context')
    assert isinstance(context,dict), 'draft context missing'
    view=legacy_public_model_view(context,source_path=source_path)
    assert 1<=view.get('line_limit',0)<=5, 'native limits not visible to actual runtime'
    assert view.get('choices'), 'actual legacy public_model_view drops all candidate rows'
    selected=[row for row in view['choices'] if expected_sku is None or row['sku']==expected_sku]
    assert selected, 'expected actual eligible SKU dropped by legacy runtime'
    assert any(row['kind'] in ('food','goods') and any(o.get('qty')==expected_qty for o in row['options']) for row in selected), 'kind/qty lost at actual runtime boundary'
    return view

def assert_original_stock_fixture(fixture):
    assert type(fixture).__name__=='StockFixture', 'use complete original StockFixture, not reduced World stub'
    path=Path(inspect.getfile(type(fixture)))
    assert sha256(path.read_bytes()).hexdigest()==SOURCE_PINS['test_procurement.py'], 'fixture class must come from exact original test_procurement source'
    assert all(hasattr(fixture,k) for k in ['patches','open_proc','pay','advance','get','post','db_path','kit','units','catalog','sends'])

def assert_real_parent_phase(fixture, invoke, *, expected_sku=None, expected_payment_status='paid_pending_confirmation'):
    """Caller binds actual native/parent namespace to full Fixture and owns temp CWD.
    invoke must call the genuine run, not manufacture result objects. This helper
    checks the visible output, original SQLite intent and original fake pay count.
    Inputs/campaign/public snapshots are installed by the selftest before calling.
    """
    assert_original_stock_fixture(fixture)
    start_sends=fixture.sends
    draft=invoke({'action':'context'})
    view=assert_legacy_context(draft,expected_sku=expected_sku)
    choice=next(row for row in view['choices'] if expected_sku is None or row['sku']==expected_sku)
    assert any(o['qty']==1 for o in choice['options'])
    decision={'action':'buy','lines':[{'sku':choice['sku'],'qty':1}],'reason':'Independent synthetic original-runtime contract'}
    approved=invoke({'action':'plan','plan':draft['plan'],'decision':decision})
    assert approved.get('status')=='ready', 'genuine plan did not accept actual visible choice'
    fixture.advance(max(0,fixture.start-fixture.now+1))
    paid=invoke({'action':'execute'})
    assert paid.get('status')==expected_payment_status, 'actual parent execute did not pass synthetic quote/payment gate'
    assert fixture.sends==start_sends+1, 'original fixture fake pay not called exactly once'
    with closing(fixture.open_proc()) as db:
        intent=db.execute('SELECT * FROM stock_intent ORDER BY created DESC LIMIT 1').fetchone()
        assert intent is not None and intent['sku']==choice['sku'] and intent['qty']==1 and intent['state'] in ('paid','accepted','unknown')
    repeated=invoke({'action':'execute'})
    assert fixture.sends==start_sends+1, 'repeat execute called fake pay twice'
    return {'legacy_visible_choices':len(view['choices']),'parent_fake_pay_calls':1,'repeat_pay_calls':0,'status':paid['status']}

def actual_request_rows(db_path):
    """Read only rows actually produced by genuine recorder SDK; do not seed enums."""
    with sqlite3.connect(Path(db_path).resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        return [dict(r) for r in db.execute('SELECT event_hash,sku,term,observed_at,confidence FROM request ORDER BY observed_at,event_hash')]

def write_exclusions(root,rows,observed_at,valid_until):
    """Native expects actual DB hash domain. Never rehash event_hash values."""
    refs=[r['event_hash'] for r in rows]
    assert all(type(v) is str and re.fullmatch('[0-9a-f]{64}',v) for v in refs)
    folder=Path(root)/'host_inputs';folder.mkdir(exist_ok=True)
    path=folder/'stock-demand-exclusions.json'
    if path.exists():path.chmod(0o600)
    path.write_text(json.dumps({'observed_at':observed_at,'valid_until':valid_until,'round':4,'event_refs':refs}))
    path.chmod(0o400)
    return refs

def assert_typed_publisher_feed(document):
    """Validate actual publisher-shaped fixture types; never invent source eligibility."""
    assert isinstance(document,dict) and set(document)=={'observed_at','valid_until','round','coverage','events'}
    assert document['round']==4 and isinstance(document['coverage'],dict) and set(document['coverage'])=={'since','complete'}
    assert type(document['coverage']['complete']) is bool
    for row in document['events']:
        assert {'seq','ts','round','kind','sku','grade','amount','shop','broken','sealed','order_ref'}<=row.keys()
        assert type(row['seq']) is int and type(row['amount']) in (int,float) and type(row['amount']) is not bool
        assert type(row['broken']) is bool and type(row['sealed']) is bool
    return document
