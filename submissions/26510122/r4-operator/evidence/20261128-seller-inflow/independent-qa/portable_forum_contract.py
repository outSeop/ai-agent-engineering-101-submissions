"""External TEST ONLY: full original ForumFixture and real core bonus schema.
No matching, business rendering, posting, wallet or network implementation here.
"""
from pathlib import Path
from hashlib import sha256
from contextlib import closing
import ast,json,sys,re,time
OP=Path(json.loads((Path.cwd()/'qa-binding.json').read_bytes())['operator']).resolve(strict=True)
CODE=OP.parent/'round-4/codex-r4';PINS={'forum.py': 'c15424eacded61da86e9f27303b16a705287cecf81c5254a2da5360db3ee9b48', 'test_forum.py': '42e9e0f4ace30819a61b7240ced435160bc37f1efd3cb295572d1ef63cc54970', 'fixture.py': '3583926d5154ede9bbc6330103930967b452c04546a19a6078864abfe931b012', 'dispatcher.py': '84e0eca3a0211e80772ed78f2ba3c166902ba0125577e7153b06cc5bb13de0cd'}
BONUS=OP.parent/'round-4/tools/first_purchase_bonus/logic.py';BONUS_PIN='0ac466eb47f8a237829ae034dab949b964c372dc4327591ce92a07b965902887'

def original_fixture(root, *, now=None):
    for name,digest in PINS.items():assert sha256((CODE/name).read_bytes()).hexdigest()==digest
    sys.path.insert(0,str(CODE))
    from test_forum import ForumFixture
    fixture=ForumFixture(root)
    fixture.db_path=Path(root)/'state/r4-benefits/benefits.sqlite3'
    fixture.db_path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    if now is not None:fixture.now=now
    fixture.get_calls=[]
    original_get=fixture.get
    def spy_get(url,*,params=None,**kwargs):
        if url==fixture.kit.market+'/api/forum':fixture.get_calls.append(dict(params or {}))
        return original_get(url,params=params,**kwargs)
    fixture.get=spy_get
    return fixture

def bonus_schema():
    raw=BONUS.read_bytes();assert sha256(raw).hexdigest()==BONUS_PIN
    for node in ast.parse(raw).body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='AWARD_SCHEMA' for t in node.targets):return ast.literal_eval(node.value)
    raise AssertionError('actual core award schema missing')

def install_bonus_schema(fixture):
    import forum
    with closing(forum.open_forum(fixture.kit.address('shop').lower(),fixture.db_path)) as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='welcome_award'").fetchone() is None:db.executescript(bonus_schema())
        assert db.execute("SELECT sql FROM sqlite_master WHERE name='welcome_award'").fetchone()[0]==bonus_schema()

def seed_award_budget(fixture, amounts, *, before_policy_start=True):
    """Synthetic arithmetic bookkeeping in actual core DDL; never customer eligibility proof."""
    install_bonus_schema(fixture)
    import sqlite3
    with sqlite3.connect(fixture.db_path) as db:
        for index,amount in enumerate(amounts):
            db.execute('INSERT INTO welcome_award VALUES(?,?,?,?,?)',('0x'+format(index+1,'040x'),'synthetic-award-'+str(index),amount,int(fixture.now-86400 if before_policy_start else fixture.now-30),index+1))

def owned_policy(fixture, **changes):
    policy={'enabled':True,'id':'synthetic-marketing-policy','start':int(fixture.now-3600),'end':int(fixture.now+3600),'lifetime_budget':50000}
    policy.update(changes)
    path=fixture.db_path.parent/'first-purchase-bonus-policy.json'
    if path.exists():path.chmod(0o600)
    path.write_text(json.dumps(policy));path.chmod(0o400)
    return policy

def owned_offer(fixture, *, sku='G159be1f8', name='들녘 쌀 5kg', category='식품>쌀', grade='A', price=10000, cost=1000, life=86400, proof=True):
    item=fixture.add_unit('u-'+format(len(fixture.units)+1,'012x'),sku=sku,price=price,cost=cost,grade=grade)
    item.update(name=name,category=category,kind='food' if life is not None else 'goods',expires_at=None if life is None else fixture.now+life)
    if proof:item['cert']['cert'].update(shop='outseop-r4')
    return item

def assert_reply_eligible(menu,thread,sku,grade):
    assert menu.get('status')=='options'
    assert any(row['thread']==thread and {'sku':sku,'grade':grade} in row['eligible'] for row in menu['reply_options'])

def assert_no_reply(menu,thread):
    assert all(row['thread']!=thread for row in menu.get('reply_options',[]))

def fake_payload(fixture):
    assert len(fixture.calls)==1,'original fake forum POST must be exactly once'
    payload=fixture.calls[0]
    assert set(payload)<= {'thread','text'} and isinstance(payload.get('text'),str) and len(payload['text'])<=2000
    assert 'checkout_jwt' not in payload['text'] and '0x' not in payload['text']
    return payload

def bonus_mentioned(text):return bool(re.search(r'5\s*%|5\s*퍼센트',text))

def assert_bonus_copy(text):
    assert bonus_mentioned(text)
    for pattern in [r'추가',r'정산',r'기준가',r'5[,]?000|5천',r'지갑',r'1회|한\s*번',r'예산',r'7일|7\s*일',r'다음\s*(?:구매|거래)',r'환불',r'회수|철회|취소']:
        assert re.search(pattern,text),pattern
    assert not re.search(r'즉시\s*5\s*%|5\s*%\s*(?:즉시\s*)?할인',text)
