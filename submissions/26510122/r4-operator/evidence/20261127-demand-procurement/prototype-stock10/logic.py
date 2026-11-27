import hashlib
import hmac
import json
import math
import sqlite3
import time
from collections import Counter, defaultdict
from pathlib import Path

LEGACY = Path('host_inputs/legacy-stock8.py')
DIGEST = '675bdaa2942f7bdf3d119d10c6e1176f790ae0bacbb22a32cf77ae82de0628c6'
SIGNALS = Path('host_inputs/stock-demand-signals.json')
POLICY = Path('host_inputs/stock-campaign-policy.json')
REQUESTS = Path('state/r4-demand/requests.sqlite3')
AGE = 21600
VERSION = 10
PENDING = ('reserved', 'sending', 'unknown', 'paid', 'accepted')
SETTLED = {'settle', 'settled', 'sale_settled'}
ADVERSE = ('refund', 'break', 'broken', 'dispute', 'reversal', 'reversed', 'cancel', 'void', 'chargeback', 'warranty_claim', 'failed', 'reject')
CHARGES = '''CREATE TABLE IF NOT EXISTS stock_campaign_charge (
    intent TEXT PRIMARY KEY REFERENCES stock_intent(id), wallet TEXT NOT NULL,
    campaign TEXT NOT NULL, quote TEXT NOT NULL UNIQUE, at REAL NOT NULL,
    old_storage INTEGER NOT NULL, old_forum INTEGER NOT NULL, goods INTEGER NOT NULL,
    total INTEGER NOT NULL, gas INTEGER NOT NULL, new_carry INTEGER NOT NULL,
    risk INTEGER NOT NULL, cash_outflow INTEGER NOT NULL)'''


def load_original():
    source = LEGACY.read_bytes()
    if not hmac.compare_digest(hashlib.sha256(source).hexdigest(), DIGEST):
        raise RuntimeError('legacy stock digest mismatch')
    namespace = {'__name__': 'logic', '__file__': str(LEGACY)}
    exec(compile(source, str(LEGACY), 'exec'), namespace)
    return namespace


def read_json(path, limit):
    try:
        with path.open('rb') as stream:
            raw = stream.read(limit + 1)
        if len(raw) <= limit:
            return json.loads(raw)
    except (OSError, ValueError, RecursionError):
        pass
    return None


def number(value):
    return type(value) in (int, float) and -1e16 <= value <= 1e16


def natural(value):
    return type(value) is int and 0 <= value <= 10**12


def text(value):
    return isinstance(value, str) and 0 < len(value) <= 160 and bool(value.strip())


def active(policy, now):
    if not isinstance(policy, dict) or set(policy) != {'campaign_id', 'starts_at', 'ends_at'}:
        return None
    ident, start, end = (policy[k] for k in ('campaign_id', 'starts_at', 'ends_at'))
    if text(ident) and number(start) and number(end) and 0 < end-start <= AGE and start <= now < end:
        return ident, start, end
    return None


def comparables(source, now, own):
    if not isinstance(source, dict) or source.get('round') != 4:
        return {}
    observed, until, coverage, events = (source.get(k) for k in ('observed_at', 'valid_until', 'coverage', 'events'))
    if not (number(observed) and number(until) and 0 < until-observed <= 150 and observed <= now < until
            and isinstance(coverage, dict) and coverage.get('complete') is True and number(coverage.get('since'))
            and coverage['since'] <= observed-AGE and isinstance(events, list)):
        return {}
    sequence, orders, adverse = {}, {}, set()
    for event in events:
        if not isinstance(event, dict) or event.get('round') != 4:
            continue
        seq, stamp, ref, kind = (event.get(k) for k in ('seq', 'ts', 'order_ref', 'kind'))
        if not natural(seq) or not number(stamp) or not text(kind) or stamp > observed:
            return {}
        previous = sequence.get(seq)
        if previous is not None:
            if previous != event:
                return {}
            continue
        sequence[seq] = event
        kind = kind.lower()
        if event.get('broken') is True or event.get('sealed') is True or any(word in kind for word in ADVERSE):
            if text(ref):
                adverse.add(ref)
        if kind not in SETTLED or stamp < now-AGE or not text(ref):
            continue
        sku, grade, amount, shop = (event.get(k) for k in ('sku', 'grade', 'amount', 'shop'))
        if not (text(sku) and text(grade) and text(shop) and natural(amount) and amount and shop.lower() not in own
                and event.get('broken') is False and event.get('sealed') is False):
            adverse.add(ref)
            continue
        fees = [event.get(key, 0) for key in ('buyer_fee', 'shop_fee', 'market_fee')]
        if not all(natural(fee) for fee in fees):
            adverse.add(ref)
            continue
        term = event.get('warranty_hours', 0)
        expiry = event.get('expires_at')
        if not number(term) or not 0 <= term <= 168 or (expiry is not None and not number(expiry)):
            adverse.add(ref)
            continue
        row = (sku, grade, amount, shop.lower(), sum(fees), term, expiry)
        if ref in orders and orders[ref] != row:
            adverse.add(ref)
        orders[ref] = row
    grouped = defaultdict(list)
    for ref, row in orders.items():
        if ref not in adverse:
            grouped[row[:2]].append(row[2:])
    return {key: rows for key, rows in grouped.items() if len(rows) >= 5}


def request_priority(now):
    if not REQUESTS.is_file():
        return {}
    try:
        uri = REQUESTS.resolve().as_uri() + '?mode=ro'
        with sqlite3.connect(uri, uri=True, timeout=.2) as db:
            rows = db.execute('SELECT event_hash,sku,term,observed_at,confidence FROM request WHERE observed_at BETWEEN ? AND ? ORDER BY observed_at DESC LIMIT 10000', (now-3600, now)).fetchall()
    except (OSError, sqlite3.Error, ValueError):
        return {}
    output, seen = {}, set()
    for event, sku, term, stamp, confidence in rows:
        if text(event) and text(sku) and event not in seen and number(stamp) and number(confidence) and 0 < confidence <= 1:
            seen.add(event)
            output[sku] = max(output.get(sku, 0), confidence)
    return output


def percent_up(value, percent):
    return (value*percent + 99)//100


def safe_ceiling(rows, listed, kind, rate, hours, chain, gas, now, life=None):
    if kind == 'food' and life is not None:
        rows = [row for row in rows if life >= max(2, row[3])*3600 + 180]
    if len(rows) < 5:
        return 0
    prices = sorted(row[0] for row in rows)
    lower = prices[(len(prices)-1)//10]
    by_bank = (lower*chain[1]+9999)//10000 + chain[2]
    sale_fees = max(by_bank, max(row[2] for row in rows))
    available = (lower-sale_fees-gas-percent_up(lower, 7)-percent_up(lower, 5)
                 -(percent_up(lower, 5) if kind == 'food' else 0))
    upper = max(0, min(listed*80//100, available-1))
    if kind == 'goods':
        low, high = 0, upper
        while low < high:
            cost = (low+high+1)//2
            if cost+math.ceil(cost*rate*hours/24) < available:
                low = cost
            else:
                high = cost-1
        return low
    return upper


def accrual(inv, whole):
    return whole(inv.get('storage_due_with_next_lot')), whole(inv.get('next_dislike_fee'))


def campaign_facts(base, inv, owned, whole, spent):
    storage, forum = accrual(inv, whole)
    rate = inv['storage_per_day']
    owned_goods = sum(unit['cost'] for unit in owned if unit.get('kind') == 'goods')
    released = math.ceil(owned_goods*rate*2)-math.ceil(owned_goods*rate/4)
    reserve = base['cash_reserve']-released
    fresh = max(0, base['cash']-reserve-base['pending_cost'])
    cap = max(0, min(100000, base['equity_at_cost']//20, released, fresh))
    return dict(base, invoice=(storage, forum), reserve6=reserve, released=released, cap=cap,
                spent=spent, spend_room=max(0, min(fresh, cap-spent)))


def approve_campaign(facts, first_invoice, invoice, gross, total, gas, carry):
    if invoice != first_invoice or invoice != facts['invoice'] or total != gross+sum(invoice):
        return None
    if not 0 < gross <= total <= 1000000:
        return None
    risk, outflow = gross+gas+carry, total+gas
    if facts['spent']+risk > facts['cap']:
        return None
    if facts['cash']-outflow < facts['reserve6']-sum(invoice)+carry+facts['pending_cost']:
        return None
    equity_after = facts['equity_at_cost']-sum(invoice)-gas
    exposure = facts['stock_cost']+facts['pending_cost']+gross
    if equity_after <= 0 or exposure*100 > equity_after*85:
        return None
    return risk, outflow


def public_context(result):
    if result.get('status') != 'draft':
        return {key: result[key] for key in ('status', 'opens_at', 'closes_at') if key in result}
    context = result['context']
    fields = ('sku', 'name', 'kind', 'category', 'tier', 'list_price')
    choices = [{**{key: row[key] for key in fields}, 'options': [dict(scenario='trial', target=1, qty=1)]}
               for row in context['choices']]
    return {'status': 'draft', 'plan': result['plan'], 'context': {
        'opens_at': context['opens_at'], 'closes_at': context['closes_at'],
        'limits': {'lines': context['limits']['lines'], 'per_sku': 1}, 'choices': choices}}


def is_new(row):
    if row is None:
        return False
    try:
        return json.loads(row['choices']).get('stock_overlay') == VERSION
    except (ValueError, AttributeError, TypeError):
        return False


def run(args, kit):
    db = None
    try:
        legacy = load_original()
        action = args.get('action')
        if action not in ('context', 'plan', 'execute'):
            return legacy['run'](args, kit)
        sales = legacy['sales']
        market = legacy['Market'](kit)
        db = legacy['ledger'](market.wallet)
        now = time.time()
        own = {str(value).lower() for value in (market.wallet, kit.name, getattr(sales, 'SHOP', '')) if value}
        campaign = active(read_json(POLICY, 4096), now)
        original_capacity = legacy['capacity']
        original_validate = legacy['validate_quote']
        original_log = legacy['log']
        original_snapshot = market.snapshot
        guarded = {}
        snapshots = []

        def snapshot():
            inv = original_snapshot()
            if len(snapshots) < 3:
                snapshots.append(inv)
            return inv

        market.snapshot = snapshot

        def spent(conn):
            return conn.execute('SELECT coalesce(sum(risk),0) FROM stock_campaign_charge WHERE wallet=? AND campaign=?',
                                (market.wallet, campaign[0])).fetchone()[0]

        def capacity(conn, inv, stamp, chain, exclude=None):
            base = original_capacity(conn, inv, stamp, chain, exclude)
            if not campaign:
                return base
            return campaign_facts(base, inv, legacy['quality'](inv, stamp), sales.whole, spent(conn))

        def candidate_rows(conn, inv, catalog, chain, limits, stamp):
            evidence = comparables(read_json(SIGNALS, 4000000), stamp, own)
            requests = request_priority(stamp)
            held = {unit.get('sku') for unit in inv['units'] if isinstance(unit, dict)}
            prior = {row[0] for row in conn.execute("SELECT DISTINCT sku FROM stock_intent WHERE state!='no_purchase' UNION SELECT DISTINCT sku FROM sale")}
            blocked = held | prior
            physical = Counter(unit.get('category') for unit in legacy['quality'](inv, stamp))
            for intent in legacy['pending'](conn):
                physical[catalog.get(intent['sku'], {}).get('category')] += intent['qty']
            ceilings = defaultdict(int)
            for (sku, grade), rows in evidence.items():
                item = catalog.get(sku, {})
                kind, category, listed = (item.get(k) for k in ('kind', 'category', 'list_price'))
                if sku in blocked or grade not in sales.GRADES or kind not in ('goods', 'food') or not text(category) or not natural(listed) or not listed:
                    continue
                if physical[category] >= legacy['PER_CATEGORY']:
                    continue
                ceiling = safe_ceiling(rows, listed, kind, inv['storage_per_day'], 6 if campaign else 48,
                                       chain, limits['acquisition_buffer'], stamp)
                ceilings[sku] = max(ceilings[sku], ceiling)
            output = []
            for sku in sorted(ceilings, key=lambda key: (-requests.get(key, 0), key)):
                ceiling = min(ceilings[sku], limits['spend_room']-limits['acquisition_buffer'], 1000000)
                if ceiling < 1:
                    continue
                item = catalog[sku]
                category = item['category']
                output.append({'sku': sku, 'name': str(item.get('name') or sku)[:80], 'kind': item['kind'],
                               'category': category, 'tier': 'novel', 'list_price': item['list_price'],
                               'category_room': legacy['PER_CATEGORY']-physical[category],
                               'options': [{'scenario': 'trial', 'target': 1, 'qty': 1, 'estimated_ceiling': ceiling}]})
            return output[:5]

        def audit(conn, stamp, event, ref, **summary):
            if event == 'prepared_candidates':
                row = sales.one(conn, 'SELECT choices FROM stock_plan WHERE id=?', ref)
                data = json.loads(row['choices'])
                data['stock_overlay'] = VERSION
                data['campaign'] = list(campaign) if campaign else None
                conn.execute('UPDATE stock_plan SET choices=? WHERE id=?', (legacy['entries'](data), ref))
            if event == 'wallet_send_started':
                intent = sales.one(conn, 'SELECT quote,total,state FROM stock_intent WHERE id=?', ref)
                if not guarded or intent['state'] != 'sending' or (intent['quote'], intent['total']) != guarded['key']:
                    raise sales.Unavailable('quote authorization mismatch')
                facts = guarded['facts']
                if campaign:
                    stamp_now = time.time()
                    if active(read_json(POLICY, 4096), stamp_now) != campaign or spent(conn) != facts['spent']:
                        raise sales.Unavailable('campaign authorization changed')
                    conn.execute('INSERT INTO stock_campaign_charge VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                                 (ref, market.wallet, campaign[0], intent['quote'], stamp_now, *guarded['invoice'],
                                  guarded['goods'], intent['total'], guarded['gas'], guarded['carry'],
                                  guarded['risk'], guarded['outflow']))
                original_log(conn, stamp, 'wholesale_cash_authorized', ref, old_storage=guarded['invoice'][0],
                             old_forum=guarded['invoice'][1], new_goods=guarded['goods'],
                             full_quote_total=intent['total'], cash_outflow_with_gas_reserve=guarded['outflow'])
            original_log(conn, stamp, event, ref, **summary)

        def validate(raw, line, caller, inv, chain, stamp, spend_room):
            quote = original_validate(raw, line, caller, inv, chain, stamp, 10**12 if campaign else spend_room)
            evidence = comparables(read_json(SIGNALS, 4000000), stamp, own)
            gas = sales.acquisition_network_buffer(chain[2])
            rate, hours = inv['storage_per_day'], 6 if campaign else 48
            unit, = raw['units']
            life = unit['expires_at']-stamp if line['kind'] == 'food' else None
            ceiling = safe_ceiling(evidence.get((line['sku'], unit['grade']), ()), line['list_price'],
                                   line['kind'], rate, hours, chain, gas, stamp, life)
            gross = raw['goods']
            if not ceiling or gross > ceiling:
                raise sales.Unavailable('no positive comparable-backed contribution')
            invoice = (raw['storage'], raw['forum_fees'])
            facts = None
            carry = math.ceil(gross*rate*hours/24) if line['kind'] == 'goods' else 0
            risk, outflow = gross+gas+carry, quote['total']+gas
            if campaign:
                fresh_intent = sales.one(db, 'SELECT id FROM stock_intent WHERE state=\'reserved\'')
                if fresh_intent is None or len(snapshots) < 3:
                    raise sales.Unavailable('missing original reservation or inventory')
                facts = capacity(db, inv, stamp, chain, exclude=fresh_intent['id'])
                result = approve_campaign(facts, accrual(snapshots[-2], sales.whole), invoice, gross, quote['total'], gas, carry)
                if result is None:
                    raise sales.Unavailable('campaign quote exceeds available risk or exact invoice')
                risk, outflow = result
            guarded.update(key=(quote['quote'], quote['total']), facts=facts, invoice=invoice,
                           goods=gross, gas=gas, carry=carry, risk=risk, outflow=outflow)
            return quote

        if action == 'plan':
            row = sales.one(db, 'SELECT * FROM stock_plan WHERE id=?', args.get('plan'))
            if not is_new(row):
                return {'status': 'invalid_plan'}
            return legacy['stock_plan'](db, market, now, args['plan'], args.get('decision'))

        inv = snapshot()
        window, _, _ = legacy['window'](inv)
        row = sales.one(db, 'SELECT * FROM stock_plan WHERE window=?', window)
        if action == 'execute' and not is_new(row):
            db.close()
            db = None
            return legacy['run'](args, kit)
        if action == 'context' and row and row['status'] == 'draft' and not is_new(row):
            with sales.atomic(db):
                db.execute("UPDATE stock_plan SET expires=? WHERE id=? AND status='draft'", (now, row['id']))
        if campaign:
            db.execute(CHARGES)
        legacy.update(capacity=capacity, candidates=candidate_rows, log=audit, validate_quote=validate)
        if action == 'context':
            return public_context(legacy['stock_context'](db, market, now, min(5, sales.whole(args.get('line_cap', 5), 1, 10))))
        from eth_utils import to_checksum_address
        return legacy['stock_execute'](db, market, now, lambda to, wei, marker: kit.pay(to_checksum_address(to), wei, marker, role='shop'))
    except (OSError, ValueError, TypeError, KeyError, AttributeError, ArithmeticError, RuntimeError, sqlite3.Error, ImportError):
        return {'status': 'authoritative_check_unavailable'}
    except Exception as exc:
        if 'legacy' in locals() and (isinstance(exc, legacy['sales'].Unavailable) or isinstance(exc, legacy['httpx'].HTTPError)):
            return {'status': 'authoritative_check_unavailable'}
        raise
    finally:
        if db is not None:
            db.close()
