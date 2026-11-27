import hashlib
import json
import math
import re
import sqlite3
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

import httpx

PARENT = Path('host_inputs/legacy-stock8.py')
PIN = '675bdaa2942f7bdf3d119d10c6e1176f790ae0bacbb22a32cf77ae82de0628c6'
POLICY = Path('state/r4-benefits/stock-campaign-policy.json')
SIGNALS = Path('host_inputs/stock-demand-signals.json')
EXCLUSIONS = Path('host_inputs/stock-demand-exclusions.json')
REQUESTS = Path('state/r4-demand/requests.sqlite3')
SKU = re.compile(r'[FG][0-9a-fA-F]{8}')
HASH = re.compile(r'[0-9a-fA-F]{64}')
TOKEN = re.compile(r'[^\W_]+', re.UNICODE)
LIFE = 7380
BOOST_CAP = 3
SCHEMA = '''
CREATE TABLE IF NOT EXISTS stock_scope_v13 (
    plan_id TEXT PRIMARY KEY, policy TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stock_risk_v13 (
    intent_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, campaign_id TEXT,
    recorded REAL NOT NULL, detail TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS stock_risk_v13_campaign ON stock_risk_v13(campaign_id);
'''


def finite(value):
    return type(value) in (int, float) and -1e12 <= value <= 1e12


def packed(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def load_parent():
    source = PARENT.read_bytes()
    if hashlib.sha256(source).hexdigest() != PIN:
        raise ValueError('public parent pin mismatch')
    namespace = {'__name__': 'logic', '__file__': str(PARENT)}
    exec(compile(source, str(PARENT), 'exec'), namespace)
    return namespace


def optional_json(reader, path):
    try:
        return reader(path)
    except (OSError, ValueError, TypeError):
        return None


def scope(reader, now):
    try:
        policy = reader(POLICY)
    except FileNotFoundError:
        return {'mode': 'normal'}
    if not isinstance(policy, dict) or set(policy) != {'campaign_id', 'starts_at', 'ends_at'}:
        raise ValueError('invalid campaign scope')
    ident, start, end = (policy[key] for key in ('campaign_id', 'starts_at', 'ends_at'))
    if (not isinstance(ident, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', ident)
            or not finite(start) or not finite(end) or not 0 < end - start <= 21600):
        raise ValueError('invalid campaign scope')
    return dict(policy, mode='campaign') if start <= now < end else {'mode': 'normal'}


def fresh(doc, now):
    if not isinstance(doc, dict) or doc.get('round') != 4:
        return False
    observed, until = doc.get('observed_at'), doc.get('valid_until')
    return finite(observed) and finite(until) and 0 <= now - observed and now < until <= observed + 150


def shop_identity(value):
    if not isinstance(value, str):
        return ''
    value = value.strip()
    if '://' not in value:
        return value.casefold().rstrip('/')
    url = urlsplit(value)
    path = url.path.rstrip('/').removesuffix('/.well-known/agent-card.json').rstrip('/')
    return url.netloc.casefold() + path if url.netloc else ''


def evidence(reader, now, own):
    doc = optional_json(reader, SIGNALS)
    if not fresh(doc, now):
        return {}
    coverage = doc.get('coverage')
    if (not isinstance(coverage, dict) or coverage.get('complete') is not True
            or not finite(coverage.get('since')) or coverage['since'] > doc['observed_at'] - 3600
            or not isinstance(doc.get('events'), list)):
        return {}
    records = []
    statuses = {'broken', 'refunded', 'refund', 'chargeback', 'cancelled', 'canceled', 'reversed'}
    for event in doc['events']:
        if not isinstance(event, dict) or event.get('round') != 4:
            continue
        seq, stamp, ref = (event.get(key) for key in ('seq', 'ts', 'order_ref'))
        if (type(seq) is not int or seq < 1 or not finite(stamp)
                or not doc['observed_at'] - 3600 <= stamp <= doc['observed_at']
                or not isinstance(ref, str) or not HASH.fullmatch(ref)):
            continue
        records.append((seq, ref.lower(), event))
    excluded_refs = set()
    for _, ref, event in records:
        kind = event.get('kind')
        if (isinstance(kind, str) and kind in statuses
                or event.get('broken') not in (None, False)
                or event.get('sealed') not in (None, False)
                or event.get('refunded') not in (None, False)
                or event.get('refund') not in (None, False)
                or str(event.get('status', '')).casefold() in statuses):
            excluded_refs.add(ref)
    by_seq, by_ref = {}, {}
    for seq, ref, event in records:
        by_seq.setdefault(seq, set()).add(packed(event))
        by_ref.setdefault(ref, set()).add(seq)
    groups, seen = {}, set()
    for seq, ref, event in records:
        if ref in excluded_refs or ref in seen or len(by_seq[seq]) != 1 or len(by_ref[ref]) != 1:
            continue
        if event.get('kind') not in ('sale', 'settled', 'sale_settled', 'order_settled'):
            continue
        sku, grade, amount = (event.get(key) for key in ('sku', 'grade', 'amount'))
        seller = shop_identity(event.get('shop'))
        if (not seller or seller == own or not isinstance(sku, str) or not SKU.fullmatch(sku)
                or not isinstance(grade, str) or type(amount) is not int or not 0 < amount <= 10**9):
            continue
        seen.add(ref)
        groups.setdefault(sku, {}).setdefault(grade, []).append(amount)
    return {sku: {grade: sorted(prices)[(len(prices) - 1) // 10]
                  for grade, prices in grades.items() if len(prices) >= 5}
            for sku, grades in groups.items()}


def recorder_rows(now):
    uri = REQUESTS.resolve().as_uri() + '?mode=ro'
    db = sqlite3.connect(uri, uri=True, timeout=1)
    try:
        return db.execute('SELECT event_hash,sku,term,observed_at,confidence FROM request '
                          'WHERE observed_at BETWEEN ? AND ? ORDER BY observed_at DESC LIMIT 1000',
                          (now - 3600, now)).fetchall()
    finally:
        db.close()


def tokens(value):
    return tuple(TOKEN.findall(unicodedata.normalize('NFKC', value).casefold())) if isinstance(value, str) else ()


def contains(haystack, needle):
    return any(haystack[i:i + len(needle)] == needle for i in range(len(haystack) - len(needle) + 1))


def priorities(reader, rows, choices, now):
    doc = optional_json(reader, EXCLUSIONS)
    if not fresh(doc, now):
        return {}
    refs = doc.get('event_refs')
    if not isinstance(refs, list) or any(not isinstance(ref, str) or not HASH.fullmatch(ref) for ref in refs):
        return {}
    excluded = {ref.lower() for ref in refs}
    indexed = {sku: (tokens(item['name']), tokens(item['category'])) for sku, item in choices.items()}
    matched = {}
    try:
        for ref, sku, term, stamp, confidence in rows(now):
            if (not isinstance(ref, str) or not HASH.fullmatch(ref) or ref.lower() in excluded
                    or not finite(stamp) or not now - 3600 <= stamp <= now):
                continue
            if confidence in ('exact_name', 'exact_sku') and term is None and sku in indexed:
                hits = (sku,)
            elif confidence == 'public_term' and sku is None:
                needle = tokens(term)
                if not needle or len(needle) > 8 or sum(map(len, needle)) < 2:
                    continue
                hits = (key for key, fields in indexed.items() if any(contains(field, needle) for field in fields))
            else:
                continue
            for key in hits:
                refs_for_sku = matched.setdefault(key, set())
                if len(refs_for_sku) < BOOST_CAP:
                    refs_for_sku.add(ref.lower())
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return {}
    return {sku: len(refs_for_sku) for sku, refs_for_sku in matched.items()}


def public_view(result):
    if result.get('status') != 'draft':
        return {key: result[key] for key in ('status', 'opens_at', 'closes_at') if key in result}
    context = result['context']
    choices = []
    for row in context['choices']:
        item = {key: row[key] for key in ('sku', 'name', 'category', 'kind', 'list_price')}
        item['options'] = [{key: option[key] for key in ('qty', 'scenario')} for option in row['options']]
        choices.append(item)
    return {'status': 'draft', 'plan': result['plan'], 'context': {
        'opens_at': context['opens_at'], 'closes_at': context['closes_at'],
        'limits': dict(context['limits']), 'choices': choices,
        'alternatives': [{key: example[key] for key in ('id', 'lines')} for example in context['alternatives']]}}


class Procurement:
    def __init__(self, parent, db, market, reader, rows, own, clock, gas=None):
        self.parent, self.db, self.market = parent, db, market
        self.sales = parent['sales']
        self.reader, self.rows, self.own, self.clock = reader, rows, own, clock
        self.gas = gas or self.sales.acquisition_network_buffer
        self.original_capacity = parent['capacity']
        self.original_quote = parent['validate_quote']
        self.whole = self.sales.whole
        self.fail = self.sales.Unavailable
        self.policy = None
        self.draft_policy = None
        self.armed = None
        self.plan_id = None
        db.executescript(SCHEMA)
        db.create_function('v13_draft_policy', 0, lambda: self.draft_policy)
        db.create_function('v13_charge', 5, self.charge)
        db.executescript('''
        CREATE TEMP TRIGGER v13_tag_insert AFTER INSERT ON main.stock_plan
        WHEN NEW.status='draft' AND v13_draft_policy() IS NOT NULL
        BEGIN
            INSERT INTO stock_scope_v13 VALUES(NEW.id,v13_draft_policy());
        END;
        CREATE TEMP TRIGGER v13_tag_replace AFTER UPDATE OF id ON main.stock_plan
        WHEN OLD.id!=NEW.id AND NEW.status='draft' AND v13_draft_policy() IS NOT NULL
        BEGIN
            DELETE FROM stock_scope_v13 WHERE plan_id=OLD.id;
            INSERT INTO stock_scope_v13 VALUES(NEW.id,v13_draft_policy());
        END;
        CREATE TEMP TRIGGER v13_audit_send AFTER UPDATE OF state ON main.stock_intent
        WHEN OLD.state='reserved' AND NEW.state='sending'
          AND EXISTS(SELECT 1 FROM stock_scope_v13 WHERE plan_id=NEW.plan_id)
        BEGIN
            INSERT INTO stock_risk_v13(intent_id,plan_id,campaign_id,recorded,detail)
            SELECT NEW.id,NEW.plan_id,json_extract(detail,'$.policy.campaign_id'),
                   json_extract(detail,'$.recorded'),detail
            FROM (SELECT v13_charge(NEW.id,NEW.plan_id,NEW.quote,NEW.marker,NEW.total) AS detail LIMIT 1);
        END;
        ''')
        parent['capacity'] = self.capacity
        parent['candidates'] = self.candidates
        parent['validate_quote'] = self.quote

    def tag(self, plan):
        row = self.db.execute('SELECT policy FROM stock_scope_v13 WHERE plan_id=?', (plan,)).fetchone()
        return json.loads(row[0]) if row else None

    def check_scope(self):
        if self.policy != scope(self.reader, self.clock()):
            raise self.fail('procurement scope changed')

    def campaign(self):
        return self.policy is not None and self.policy['mode'] == 'campaign'

    def outstanding_risk(self):
        row = self.db.execute('SELECT coalesce(sum(json_extract(detail,\'$.new_risk\')),0) '
                              'FROM stock_risk_v13 WHERE campaign_id=?', (self.policy['campaign_id'],)).fetchone()
        return int(row[0])

    def unaccounted_campaign_history(self):
        return self.db.execute('''SELECT 1 FROM stock_intent AS i
            WHERE i.created>=? AND i.created<? AND i.state IN ('sending','unknown','paid','accepted','arrived')
              AND NOT EXISTS(SELECT 1 FROM stock_risk_v13 AS a WHERE a.intent_id=i.id) LIMIT 1''',
            (self.policy['starts_at'], self.policy['ends_at'])).fetchone() is not None

    def capacity(self, db, inv, now, chain, exclude=None):
        limits = self.original_capacity(db, inv, now, chain, exclude)
        limits['acquisition_buffer'] = self.gas(chain[2]) if self.policy is not None else limits['acquisition_buffer']
        if not self.campaign():
            return limits
        goods_cost = sum(unit['cost'] for unit in self.parent['quality'](inv, now) if unit['kind'] == 'goods')
        rate = inv['storage_per_day']
        released = math.ceil(goods_cost * rate * 2) - math.ceil(goods_cost * rate * .25)
        reserve = limits['cash_reserve'] - released
        fresh_room = max(0, limits['cash'] - reserve - limits['pending_cost'])
        cap = min(100000, limits['equity_at_cost'] // 20, released, fresh_room)
        spent = self.outstanding_risk()
        room = 0 if self.unaccounted_campaign_history() else max(0, cap - spent)
        return dict(limits, released=released, cash_reserve=reserve, fresh_room=fresh_room,
                    campaign_cap=cap, campaign_spent=spent, spend_room=room)

    def carry(self, kind, cost, rate):
        return math.ceil(cost * rate * (.25 if self.campaign() else 2)) if kind == 'goods' else 0

    def profitable(self, kind, price, cost, new_fees, rate, chain):
        _, bps, network, _ = chain
        benefits = (price * 7 + 99) // 100
        refund = (price * 5 + 99) // 100
        spoilage = refund if kind == 'food' else 0
        clearing = (price * bps + 9999) // 10000
        return price - benefits - refund - spoilage - clearing - (network + 1) // 2 > (
            cost + new_fees + self.gas(network) + self.carry(kind, cost, rate))

    def candidates(self, db, inv, catalog, chain, limits, now):
        if self.policy is None:
            return []
        prices = evidence(self.reader, now, self.own)
        stock = self.parent['quality'](inv, now)
        pending = self.parent['pending'](db)
        occupied = {row['sku'] for row in stock} | {row['sku'] for row in pending}
        prior = {row[0] for row in db.execute("SELECT sku FROM stock_intent WHERE state!='no_purchase' UNION SELECT sku FROM sale")}
        surge = {item.get('sku'): item.get('factor') for item in inv.get('surge', []) if isinstance(item, dict)}
        choices = {}
        gas = limits['acquisition_buffer']
        for sku, grades in prices.items():
            item = catalog.get(sku, {})
            kind, name, category, listed = (item.get(key) for key in ('kind','name','category','list_price'))
            if (sku in occupied or kind not in ('goods','food') or not isinstance(name,str) or not name.strip()
                    or not isinstance(category,str) or not category.strip() or type(listed) is not int or listed < 1):
                continue
            shelf = item.get('shelf_hours')
            if kind == 'food' and (not finite(shelf) or shelf * 3600 < LIFE):
                continue
            tier = 'novel'
            if sku in prior:
                forecast = self.parent['forecast'](db,sku,now,inv['storage_per_day'],chain[0],chain[2])
                if forecast['positive_sales_12h'] < 2 or forecast['net_contribution_12h'] <= 0:
                    continue
                tier = 'proven'
            factor = surge.get(sku,1)
            if not finite(factor) or not 1 <= factor <= 10:
                continue
            used = sum(row.get('category') == category for row in stock) + sum(
                row['qty'] for row in pending if catalog.get(row['sku'], {}).get('category') == category)
            if used >= self.parent['PER_CATEGORY']:
                continue
            high = min(listed * 80 // 100, limits['spend_room'] - gas, 1000000)
            low = 0
            while low < high:
                cost = (low + high + 1) // 2
                carry = self.carry(kind, cost, inv['storage_per_day'])
                budget_ok = not self.campaign() or cost + gas + carry <= limits['spend_room']
                if budget_ok and any(grade in self.sales.GRADES and self.profitable(
                        kind, price, cost, 0, inv['storage_per_day'], chain) for grade,price in grades.items()):
                    low = cost
                else:
                    high = cost - 1
            if low < 1:
                continue
            choices[sku] = {'sku':sku,'name':name,'category':category,'kind':kind,'list_price':listed,
                            'tier':tier,'category_room':self.parent['PER_CATEGORY'] - used,
                            'options':[{'scenario':tier,'qty':1,'target':1,'estimated_ceiling':low,
                                        'horizon_hours':2 if kind == 'food' else None}]}
        boost = priorities(self.reader,self.rows,choices,now)
        ranked = sorted(choices.values(), key=lambda item: (-boost.get(item['sku'],0), item['tier'] != 'proven', item['sku']))
        return ranked[:self.line_cap]

    def quote(self, raw, line, market, inv, chain, now, spend_room):
        if self.policy is None:
            return self.original_quote(raw,line,market,inv,chain,now,spend_room)
        self.check_scope()
        if not isinstance(raw,dict) or not re.fullmatch(r'q-[0-9a-f]{16}',str(raw.get('quote',''))):
            raise self.fail('bad wholesale quote identifier')
        credit, _, network, recipient = chain
        goods = self.whole(raw.get('goods'),1)
        storage, forum = self.whole(raw.get('storage')), self.whole(raw.get('forum_fees'))
        old_storage = self.whole(inv.get('storage_due_with_next_lot'))
        old_forum = self.whole(inv.get('next_dislike_fee'))
        total = self.whole(raw.get('total'),1,1000000)
        if total != goods + storage + forum or goods > line['goods_ceiling']:
            raise self.fail('bad wholesale total')
        gas = self.gas(network)
        if self.campaign():
            if storage != old_storage or forum != old_forum:
                raise self.fail('old dues differ from authoritative inventory')
        elif storage > old_storage + 1 or forum > old_forum or total + gas > spend_room:
            raise self.fail('normal wholesale cash or fee limit')
        storage_paid, forum_paid = min(old_storage,storage), min(old_forum,forum)
        dues = storage_paid + forum_paid
        new_fees = total - goods - dues
        if self.whole(raw.get('expires_in'),1,3600) < self.parent['END_BUFFER']:
            raise self.fail('insufficient quote time')
        marker = '0x' + hashlib.sha256(raw['quote'].encode()).hexdigest()
        pay = raw.get('pay')
        if (not isinstance(pay,dict) or self.sales.address(pay.get('to')) != recipient
                or pay.get('data') != marker or pay.get('wei') != str(total * credit)):
            raise self.fail('bank facts do not match quote')
        units = raw.get('units')
        if line['qty'] != 1 or not isinstance(units,list) or len(units) != 1 or not isinstance(units[0],dict):
            raise self.fail('unexpected wholesale quantity')
        unit = units[0]
        if (any(unit.get(key) != line[key] for key in ('sku','kind','list_price','category'))
                or not re.fullmatch(r'u-[0-9a-f]{12}',str(unit.get('unit','')))
                or unit.get('grade') not in self.sales.GRADES or self.whole(unit.get('cost'),1) != goods):
            raise self.fail('quote unit does not match approved stock')
        if line['kind'] == 'food':
            if self.sales.number(unit.get('expires_at')) - now < LIFE:
                raise self.fail('food handling or life limit')
        elif unit.get('expires_at') is not None:
            raise self.fail('goods has unexpected expiry')
        price = evidence(self.reader,now,self.own).get(line['sku'],{}).get(unit['grade'])
        rate = inv['storage_per_day']
        if price is None or not self.profitable(line['kind'],price,goods,new_fees,rate,chain):
            raise self.fail('actual grade lacks positive conservative margin')
        carry = self.carry(line['kind'],goods,rate)
        risk = goods + new_fees + gas + carry
        cap = None
        if self.campaign():
            held = self.db.execute("SELECT id FROM stock_intent WHERE state='reserved' AND plan_id=?",(self.plan_id,)).fetchone()
            if held is None:
                raise self.fail('missing reserved quote intent')
            limits = self.capacity(self.db,inv,now,chain,held[0])
            cap = limits['campaign_cap']
            cash, pending = limits['cash'], limits['pending_cost']
            if (risk > min(spend_room,limits['spend_room']) or cash - total - gas < limits['cash_reserve'] - dues + pending + carry
                    or 100 * (limits['stock_cost'] + pending + goods) > 85 * (limits['equity_at_cost'] - dues - new_fees - gas)):
                raise self.fail('campaign cash, cumulative risk, or exposure limit')
        self.armed = {'policy':self.policy,'quote':raw['quote'],'marker':marker,'old_storage_paid':storage_paid,
                      'old_forum_paid':forum_paid,'old_dues_paid':dues,'new_goods':goods,'new_fees':new_fees,
                      'acquisition_gas_reserve':gas,'new_carry':carry,'full_quote':total,
                      'full_cash_outflow':total + gas,'new_risk':risk,'campaign_cap':cap}
        return {'quote':raw['quote'],'total':total,'marker':marker,'recipient':recipient,
                'wei':str(total * credit),'units':[unit['unit']]}

    def charge(self, intent, plan, quote, marker, total):
        self.check_scope()
        a = self.armed
        if (a is None or plan != self.plan_id or self.tag(plan) != self.policy
                or (quote,marker,total) != (a['quote'],a['marker'],a['full_quote'])):
            raise self.fail('sending transition has no matching risk record')
        if self.campaign() and a['new_risk'] + self.outstanding_risk() > a['campaign_cap']:
            raise self.fail('campaign risk changed before send')
        return packed(dict(a,intent_id=intent,plan_id=plan,recorded=self.clock()))

    def context(self, now, cap):
        self.line_cap = self.whole(cap,1,5)
        self.policy = scope(self.reader,now)
        self.draft_policy = packed(self.policy)
        return public_view(self.parent['stock_context'](self.db,self.market,now,self.line_cap))

    def plan(self, now, ident, decision):
        self.policy = self.tag(ident)
        if self.policy is not None:
            self.check_scope()
        return self.parent['stock_plan'](self.db,self.market,now,ident,decision)

    def execute(self, now, pay):
        inv = self.market.snapshot()
        window, _, _ = self.parent['window'](inv)
        plan = self.db.execute("SELECT id FROM stock_plan WHERE window=? AND status='ready'",(window,)).fetchone()
        if plan:
            self.plan_id = plan[0]
            self.policy = self.tag(self.plan_id)
            if self.policy is not None:
                self.check_scope()
                if not self.campaign() and self.unexpected_history_tag(self.plan_id):
                    raise self.fail('invalid plan scope')
        return self.parent['stock_execute'](self.db,self.market,now,pay)

    def unexpected_history_tag(self, ident):
        return self.tag(ident) != {'mode':'normal'}


def run(args, kit):
    db = None
    try:
        parent = load_parent()
        world = globals().get('_TEST_WORLD') if kit.testing else None
        if world is None:
            market = parent['Market'](kit)
            db = parent['ledger'](market.wallet)
            def reader(path):
                return json.loads(path.read_text(encoding='utf-8'))
            def pay(to, wei, marker):
                from eth_utils import to_checksum_address
                return kit.pay(to_checksum_address(to),wei,marker,role='shop')
            clock, rows, gas = time.time, recorder_rows, None
        else:
            market, reader, clock, rows, pay, gas = world, world.read, world.clock, world.rows, world.pay, world.gas
            db = parent['ledger'](market.wallet,world.db_path)
            parent['quality'] = lambda inv, now: inv['units']
        own = shop_identity(kit.shop_url)
        service = Procurement(parent,db,market,reader,rows,own,clock,gas)
        now = clock()
        action = args.get('action')
        if action == 'context':
            return service.context(now,args.get('line_cap',5))
        if action == 'plan':
            return service.plan(now,args['plan'],args['decision'])
        if action == 'execute':
            return service.execute(now,pay)
        if action == 'reconcile':
            return parent['stock_reconcile'](db,market,now)
        return {'status':'invalid_action'}
    except (OSError,ValueError,TypeError,KeyError,AttributeError,sqlite3.Error,httpx.HTTPError):
        return {'status':'authoritative_check_unavailable'}
    except Exception as exc:
        if 'parent' in locals() and isinstance(exc,parent['sales'].Unavailable):
            return {'status':'authoritative_check_unavailable'}
        raise
    finally:
        if db is not None:
            db.close()
