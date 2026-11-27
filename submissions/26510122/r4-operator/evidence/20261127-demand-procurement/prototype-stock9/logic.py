import hashlib
import hmac
import json
import time
from pathlib import Path
from types import SimpleNamespace

LEGACY = Path('host_inputs/legacy-stock8.py')
DIGEST = '675bdaa2942f7bdf3d119d10c6e1176f790ae0bacbb22a32cf77ae82de0628c6'
SIGNALS = Path('host_inputs/stock-demand-signals.json')
WALLET = '0x59b66e793f74dd3fb70d4eafcf86c28bcab63b0f'
SIX_HOURS = 21600


def _legacy(kit):
    source = LEGACY.read_bytes()
    if not hmac.compare_digest(hashlib.sha256(source).hexdigest(), DIGEST):
        raise RuntimeError('stock8 digest mismatch')
    namespace = {'__name__': 'stock8', '__file__': str(LEGACY)}
    exec(compile(source, str(LEGACY), 'exec'), namespace)
    return namespace['run']


def _integer(value):
    return type(value) is int and value >= 0


def _identifier(value):
    return type(value) is str and bool(value.strip())


def _campaign(policy, now):
    if not isinstance(policy, dict) or policy.get('version') != 9 or policy.get('reviewed') is not True:
        return 'invalid'
    wallet = policy.get('wallet')
    start, end, reviewed = (policy.get(key) for key in ('start', 'end', 'reviewed_at'))
    if not (_identifier(wallet) and wallet.lower() == WALLET and _identifier(policy.get('campaign_id'))):
        return 'invalid'
    if not all(map(_integer, (start, end, reviewed))) or not reviewed <= start <= reviewed + 900 or end - start != SIX_HOURS:
        return 'invalid'
    return 'active' if start <= now < end else 'legacy'


def _recent(record, now, age):
    stamp = record.get('at')
    return _integer(stamp) and now - age <= stamp <= now


def _evidence(row, now):
    sku, grade = row.get('sku'), row.get('grade')
    population = row.get('observed_count')
    if not all(map(_identifier, (sku, grade))) or not _integer(population) or population < 3:
        return None
    settlements, demand = row.get('settlements'), row.get('demand')
    if not isinstance(settlements, list) or not isinstance(demand, list):
        return None
    prices = {}
    for receipt in settlements:
        if not isinstance(receipt, dict) or not _recent(receipt, now, SIX_HOURS):
            continue
        if any(receipt.get(key) is not True for key in ('verified', 'public', 'settled', 'nonsealed', 'unbroken')):
            continue
        seller, buyer, unit, price = (receipt.get(key) for key in ('seller', 'buyer', 'unit_id', 'unit_price'))
        if not all(map(_identifier, (seller, buyer, unit))) or WALLET in (seller.lower(), buyer.lower()) or seller.lower() == buyer.lower():
            continue
        if (receipt.get('sku'), receipt.get('grade')) != (sku, grade) or not _integer(price) or price == 0:
            continue
        if unit in prices and prices[unit] != price:
            return None
        prices[unit] = price
    count = len(prices)
    if count < 3 or count > population or count * 100 < population * 80:
        return None
    customers = set()
    request_owners = {}
    for request in demand:
        if not isinstance(request, dict) or not _recent(request, now, 3600):
            continue
        if any(request.get(key) is not True for key in ('verified', 'public', 'qualified', 'open')):
            continue
        who, request_id = request.get('customer'), request.get('request_id')
        if request.get('sku') != sku or not all(map(_identifier, (who, request_id))) or who.lower() == WALLET:
            continue
        who = who.lower()
        if request_id in request_owners and request_owners[request_id] != who:
            return None
        request_owners[request_id] = who
        customers.add(who)
    if not customers:
        return None
    return sorted(prices.values())[(count - 1) // 10], len(customers)


def _ordered(policy, now):
    rows, rotated = policy.get('candidates'), policy.get('rotated_skus')
    if not isinstance(rows, list) or not isinstance(rotated, list) or not all(map(_identifier, rotated)):
        return []
    if any(not isinstance(row, dict) or not _identifier(row.get('sku')) for row in rows):
        return []
    if len({row['sku'] for row in rows}) != len(rows):
        return []
    positions = {}
    for index, sku in enumerate(rotated):
        positions.setdefault(sku, index)
    ranked = []
    for row in rows:
        if any(row.get(key) is not False for key in ('held', 'pending', 'prior_unproven')):
            continue
        if not all(map(_identifier, (row.get('name'), row.get('category')))) or not _integer(row.get('price')) or not row['price']:
            continue
        evidence = _evidence(row, now)
        if evidence is not None:
            ranked.append((row, evidence))
    ranked.sort(key=lambda entry: (-entry[1][1], positions.get(entry[0]['sku'], len(positions)), entry[0]['sku']))
    return ranked[:5]


def _finance(facts):
    fields = ('cash equity_before_arrears_and_gas stock_pending_exposure new_goods quote_total dues earmarked_dues mandatory future_6h new_carry gas fees soft_freed fresh_room durable_spent').split()
    if not all(_integer(facts.get(key)) for key in fields):
        return False
    if facts.get('authoritative') is not True or facts.get('ledger_current') is not True:
        return False
    cash, equity, exposure, goods, total, dues, earmarked, mandatory, carry, new_carry, gas, fees, freed, room, spent = (facts[key] for key in fields)
    if total != goods + dues + fees or total > 1_000_000 or not goods or dues > earmarked or earmarked > mandatory:
        return False
    postpay_equity = equity - dues - gas
    limit = min(100_000, equity // 20, freed, room)
    return (limit > 0 and spent + goods + gas + fees <= limit
            and cash - total - gas >= mandatory - dues + carry + new_carry
            and postpay_equity > 0 and 100 * (exposure + goods) <= 85 * postpay_equity)


def _margin(row, evidence, exact_unit, actual_grade):
    fields = ('buy_fee', 'buy_gas', 'sell_fee', 'sell_gas', 'storage', 'new_expenses', 'expiry', 'waste_bp')
    if evidence is None or actual_grade != row.get('grade') or not _integer(exact_unit) or not exact_unit:
        return False
    if not all(_integer(row.get(key)) for key in fields) or not 0 < row['waste_bp'] <= 10000:
        return False
    p10 = evidence[0]
    haircut = (p10 * row['waste_bp'] + 9999) // 10000
    benefits = (p10 * 7 + 99) // 100
    refunds = (p10 * 5 + 99) // 100
    return p10 - haircut - benefits - refunds - exact_unit - sum(row[key] for key in fields[:-1]) > 0


def _dispatch(args, kit, policy, now, legacy):
    state = 'legacy' if policy is None else _campaign(policy, now)
    if state == 'legacy' or args.get('action') == 'reconcile':
        return legacy(kit)(args, kit)
    if state == 'invalid':
        return {'status': 'hold', 'reason': 'invalid_reviewed_campaign', 'finance_ready': False}
    if args.get('action') == 'context':
        return legacy(kit)(args, kit)
    result = {'status': 'hold', 'reason': 'finance_unready', 'finance_ready': False}
    if args.get('action') == 'plan':
        result['choices'] = [dict(name=row['name'], category=row['category'], price=row['price'], qty_choices=[0, 1]) for row, evidence in _ordered(policy, now)]
    return result


def run(args, kit):
    if kit.testing:
        if args.get('action') == '_sdk_test':
            return _sdk_test()
        return {'status': 'hold', 'reason': 'synthetic_only'}
    try:
        with SIGNALS.open(encoding='utf-8') as source:
            policy = json.load(source)
        if policy is None:
            policy = False
    except FileNotFoundError:
        policy = None
    except (OSError, ValueError):
        policy = False
    return _dispatch(args, kit, policy, int(time.time()), _legacy)


def _sdk_test():
    now = 100000
    calls = []
    kit = SimpleNamespace(pay=lambda *args: calls.append('pay'))
    legacy = lambda _: lambda args, kit: calls.append(args) or args
    request = {'action': 'execute', 'approved_plan': {'version': 8}}
    policy = dict(version=9, reviewed=True, wallet=WALLET, campaign_id='test', start=now, end=now + SIX_HOURS, reviewed_at=now)
    assert _dispatch(request, kit, None, now, legacy) is request
    assert _dispatch(request, kit, policy, now - 1, legacy) is request
    assert _dispatch(request, kit, policy, now + SIX_HOURS, legacy) is request
    assert _dispatch(request, kit, policy, now, legacy)['reason'] == 'finance_unready'
    assert _dispatch(request, kit, dict(policy, end=now + SIX_HOURS + 1), now, legacy)['reason'] == 'invalid_reviewed_campaign'
    def candidate(sku, buyers):
        receipts = [dict(at=now, verified=True, public=True, settled=True, nonsealed=True, unbroken=True, seller='seller', buyer='buyer', unit_id=str(i), unit_price=price, sku=sku, grade='A') for i, price in enumerate((100, 130, 150))]
        requests = [dict(at=now, verified=True, public=True, qualified=True, open=True, customer=buyer, request_id=str(i), sku=sku) for i, buyer in enumerate(buyers)]
        return dict(sku=sku, grade='A', name=sku, category='food', price=900, held=False, pending=False, prior_unproven=False, observed_count=3, settlements=receipts + receipts, demand=requests, buy_fee=1, buy_gas=1, sell_fee=1, sell_gas=1, storage=1, new_expenses=1, expiry=1, waste_bp=500)
    first = candidate('rotated', ['a', 'A'])
    target = candidate('target', ['a', 'b'])
    assert _evidence(first, now) == (100, 1)
    assert _evidence(dict(target, settlements=target['settlements'][:1] * 4), now) is None
    assert _evidence(dict(target, observed_count=4), now) is None
    assert _evidence(dict(target, demand=[dict(target['demand'][0], public=False)]), now) is None
    assert _evidence(dict(target, settlements=[dict(r, seller=WALLET) for r in target['settlements']]), now) is None
    assert not _margin(target, _evidence(target, now), 76, 'A')
    assert _margin(target, _evidence(target, now), 75, 'A')
    assert not _margin(target, _evidence(target, now), 75, 'B')
    policy.update(candidates=[first, target, dict(candidate('held', ['a', 'b', 'c']), held=True)], rotated_skus=['rotated'])
    plan = _dispatch({'action': 'plan'}, kit, policy, now, legacy)
    assert [row['name'] for row in plan['choices']] == ['target', 'rotated']
    assert all(set(row) == {'name', 'category', 'price', 'qty_choices'} for row in plan['choices'])
    assert calls == [request, request, request]
    facts = dict(authoritative=True, ledger_current=True, cash=344, equity_before_arrears_and_gas=10000, stock_pending_exposure=8247, new_goods=100, quote_total=203, dues=100, earmarked_dues=100, mandatory=200, future_6h=20, new_carry=10, gas=11, fees=3, soft_freed=400, fresh_room=400, durable_spent=286)
    assert _finance(facts)
    assert not _finance(dict(facts, cash=343))
    assert not _finance(dict(facts, stock_pending_exposure=8306))
    assert not _finance(dict(facts, earmarked_dues=99))
    assert not _finance(dict(facts, quote_total=202))
    assert not _finance(dict(facts, durable_spent=287))
    assert not _finance(dict(facts, fresh_room=0))
    assert not _finance(dict(facts, ledger_current=False))
    return {'passed': True, 'payments': 0, 'finance_ready': False}
