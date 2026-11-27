import ast
import hashlib
import hmac
import json
import math
import re
import sqlite3
import time
import unicodedata
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from urllib.parse import urlsplit

DIGEST = '675bdaa2942f7bdf3d119d10c6e1176f790ae0bacbb22a32cf77ae82de0628c6'
TAG = '_stock12_policy'
HOUR = 3600
SKU = re.compile(r'[FG][0-9A-Fa-f]{8}')
REF = re.compile(r'[0-9a-f]{64}')
SETTLED = {'settle', 'settled', 'sale_settled'}
ADVERSE = re.compile(r'refund|break|broken|disput|revers|cancel|void|chargeback|warranty_claim|fail|reject|sealed')
SCHEMA = '''
CREATE TABLE IF NOT EXISTS stock12_campaign (
    wallet TEXT NOT NULL, campaign_id TEXT NOT NULL, policy TEXT NOT NULL,
    starts REAL NOT NULL, ends REAL NOT NULL, PRIMARY KEY(wallet,campaign_id)
);
CREATE TABLE IF NOT EXISTS stock12_risk (
    intent TEXT PRIMARY KEY REFERENCES stock_intent(id), wallet TEXT NOT NULL,
    campaign_id TEXT NOT NULL, amount INTEGER NOT NULL CHECK(amount>0)
);
CREATE INDEX IF NOT EXISTS stock12_risk_scope ON stock12_risk(wallet,campaign_id);
'''


def read_input(name, limit):
    try:
        with (Path.cwd() / 'host_inputs' / name).open('rb') as stream:
            raw = stream.read(limit+1)
        if len(raw) <= limit:
            return json.loads(raw)
    except FileNotFoundError:
        raise
    except (OSError, ValueError, RecursionError):
        pass
    return None


def optional_input(name, limit):
    try:
        return read_input(name, limit)
    except FileNotFoundError:
        return None


def timestamp(value):
    return type(value) in (int,float) and 0 <= value <= 10**12


def positive(value):
    return type(value) is int and 0 < value <= 10**12


def matches(pattern, value):
    return isinstance(value,str) and pattern.fullmatch(value) is not None


def policy_at(now):
    try:
        raw = read_input('stock-campaign-policy.json',8192)
    except FileNotFoundError:
        return {'mode':'normal'}
    if not isinstance(raw,dict) or set(raw) != {'campaign_id','starts_at','ends_at'}:
        return None
    ident, start, end = (raw[k] for k in ('campaign_id','starts_at','ends_at'))
    if (not isinstance(ident,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',ident)
            or not timestamp(start) or not timestamp(end) or not 0 < end-start <= 21600):
        return None
    if start <= now < end:
        return dict(raw,mode='campaign')
    return {'mode':'normal'}


def fresh(raw, now):
    if not isinstance(raw,dict) or type(raw.get('round')) is not int or raw['round'] != 4:
        return False
    start, end = raw.get('observed_at'), raw.get('valid_until')
    return timestamp(start) and timestamp(end) and 0 < end-start <= 150 and start <= now < end


def endpoint(value):
    if not isinstance(value,str) or len(value)>512:
        return None
    try:
        part = urlsplit(value.strip())
        scheme = part.scheme.lower()
        if scheme not in ('https','http') or not part.hostname or part.username is not None or part.password is not None:
            return None
        port = part.port or (443 if scheme=='https' else 80)
        return scheme, part.hostname.lower().rstrip('.'),port,part.path.rstrip('/')
    except ValueError:
        return None


def price_feed(now, own_url, grades):
    raw = optional_input('stock-demand-signals.json',12*1024*1024)
    if not fresh(raw,now):
        return {}
    observed = raw['observed_at']
    coverage, events = raw.get('coverage'), raw.get('events')
    if (not isinstance(coverage,dict) or coverage.get('complete') is not True
            or not timestamp(coverage.get('since')) or coverage['since'] > observed-HOUR
            or not isinstance(events,list) or len(events)>50000):
        return {}
    own = endpoint(own_url)
    seen, orders = {}, {}
    bad_refs, bad_seqs = set(), set()
    for event in events:
        if not isinstance(event,dict):
            return {}
        if type(event.get('round')) is not int or event['round']!=4:
            continue
        seq, stamp, ref, kind = (event.get(k) for k in ('seq','ts','order_ref','kind'))
        if not positive(seq) or not timestamp(stamp) or stamp>observed or not isinstance(kind,str):
            return {}
        if seq in seen:
            if seen[seq]!=event:
                return {}
            continue
        seen[seq]=event
        kind=kind.lower()
        flags=(event.get('broken'),event.get('sealed'))
        if any(flag is not None and type(flag) is not bool for flag in flags):
            continue
        if True in flags or ADVERSE.search(kind):
            if matches(REF,ref):
                bad_refs.add(ref)
            bad_seqs.add(seq)
            for key in ('settle_seq','sale_seq','order_seq','ref_seq','related_seq','target_seq'):
                if positive(event.get(key)):
                    bad_seqs.add(event[key])
            continue
        if kind not in SETTLED or stamp<observed-HOUR or not matches(REF,ref):
            continue
        sku, grade, amount = (event.get(k) for k in ('sku','grade','amount'))
        shop=endpoint(event.get('shop'))
        if not (matches(SKU,sku) and isinstance(grade,str) and grade in grades and positive(amount) and shop):
            continue
        value=(sku,grade,amount,shop,stamp)
        if ref in orders:
            first, seqs=orders[ref]
            if first!=value:
                bad_refs.add(ref)
            seqs.add(seq)
        else:
            orders[ref]=(value,{seq})
    groups=defaultdict(list)
    for ref, ((sku,grade,amount,shop,_),seqs) in orders.items():
        if ref not in bad_refs and not seqs.intersection(bad_seqs) and shop!=own:
            groups[sku,grade].append(amount)
    return {key:sorted(amounts)[(len(amounts)-1)//10] for key,amounts in groups.items() if len(amounts)>=5}


def normalize_term(value):
    if not isinstance(value,str) or not 1<=len(value)<=160:
        return ''
    return ' '.join(unicodedata.normalize('NFKC',value).casefold().split())


def request_path():
    return Path.cwd() / 'state/r4-demand/requests.sqlite3'


def request_boost(catalog, now):
    raw=optional_input('stock-demand-exclusions.json',2*1024*1024)
    if not fresh(raw,now) or not isinstance(raw.get('event_refs'),list) or not all(matches(REF,r) for r in raw['event_refs']):
        return {}
    excluded=set(raw['event_refs'])
    terms=defaultdict(set)
    for sku,item in catalog.items():
        term=normalize_term(item.get('name'))
        if matches(SKU,sku) and term:
            terms[term].add(sku)
    resolved=defaultdict(set)
    db=None
    try:
        db=sqlite3.connect(request_path().resolve().as_uri()+'?mode=ro',uri=True,timeout=1)
        db.execute('PRAGMA query_only=ON')
        rows=db.execute('SELECT event_hash,sku,term,observed_at,confidence FROM request WHERE observed_at BETWEEN ? AND ? LIMIT 10001',(now-HOUR,now)).fetchall()
    except (sqlite3.Error,OSError,ValueError):
        return {}
    finally:
        if db is not None:
            db.close()
    if len(rows)>10000:
        return {}
    for ref,sku,term,stamp,confidence in rows:
        if not matches(REF,ref) or ref in excluded or not timestamp(stamp):
            continue
        if confidence in ('exact_name','exact_sku') and matches(SKU,sku) and sku in catalog:
            resolved[ref].add(sku)
        elif confidence=='public_term' and sku is None:
            hits=terms.get(normalize_term(term),set())
            if len(hits)==1:
                resolved[ref].update(hits)
    return dict(Counter(next(iter(hits)) for hits in resolved.values() if len(hits)==1))


def ceil_ratio(numerator, denominator):
    return (numerator+denominator-1)//denominator


def carry_charge(cost, rate, fraction):
    return int((Decimal(cost)*Decimal(str(rate))*fraction).to_integral_value(rounding=ROUND_CEILING))


def net_price(amount, chain):
    _,bps,network,_=chain
    return amount-ceil_ratio(amount*7,100)-ceil_ratio(amount*5,100)-ceil_ratio(amount*bps,10000)-ceil_ratio(network,2)


def campaign_spent(db, market, policy):
    return db.execute('SELECT coalesce(sum(amount),0) FROM stock12_risk WHERE wallet=? AND campaign_id=?',(market.wallet,policy['campaign_id'])).fetchone()[0]


def scope_current(db, market, tag, now, *, bind=False):
    current=policy_at(now)
    if not isinstance(tag,dict) or current is None or tag!=current:
        return False
    if tag['mode']=='normal':
        return True
    encoded=json.dumps(tag,sort_keys=True,separators=(',',':'))
    rows=db.execute('SELECT campaign_id,policy FROM stock12_campaign WHERE wallet=? AND (campaign_id=? OR (starts<? AND ends>?))',
                    (market.wallet,tag['campaign_id'],tag['ends_at'],tag['starts_at'])).fetchall()
    if rows:
        return len(rows)==1 and rows[0][0]==tag['campaign_id'] and rows[0][1]==encoded
    if not bind:
        return False
    db.execute('INSERT INTO stock12_campaign VALUES(?,?,?,?,?)',
               (market.wallet,tag['campaign_id'],encoded,tag['starts_at'],tag['ends_at']))
    return True


def plan_tag(row):
    return json.loads(row['choices']).get(TAG)


def scope_before_approval(db, market, row, now):
    tag=plan_tag(row)
    return tag is None or scope_current(db,market,tag,now,bind=True)


def scope_before_execution(db, market, row, now):
    tag=plan_tag(row)
    return tag is None or scope_current(db,market,tag,now)


def context_capacity(ns, db, market, inv, now, chain, policy, exclude=None):
    limits=ns['capacity'](db,inv,now,chain,exclude)
    if policy is None or policy['mode']=='normal':
        return limits
    rate=inv['storage_per_day']
    goods=sum(unit['cost'] for unit in ns['quality'](inv,now) if unit.get('kind')=='goods')
    released=math.ceil(goods*rate*2)-carry_charge(goods,rate,Decimal('.25'))
    reserve=limits['cash_reserve']-released
    freshroom=max(0,limits['cash']-reserve-limits['pending_cost'])
    cap=min(100000,limits['equity_at_cost']//20,released,freshroom)
    spent=campaign_spent(db,market,policy)
    limits.update(cash_reserve=reserve,released=released,freshroom=freshroom,campaign_cap=cap,
                  campaign_spent=spent,spend_room=max(0,cap-spent),campaign_rate=rate)
    return limits


def shortlist(ns, db, market, inv, catalog, chain, limits, now, line_cap, policy):
    sales=ns['sales']
    prices=price_feed(now,market.own_url,sales.GRADES)
    boost=request_boost(catalog,now)
    observed={unit['sku'] for unit in inv['units'] if isinstance(unit,dict) and isinstance(unit.get('sku'),str)}
    stock=Counter(unit.get('category') for unit in ns['quality'](inv,now))
    pending=ns['pending'](db)
    reserved={row['sku'] for row in pending}
    for row in pending:
        stock[catalog.get(row['sku'],{}).get('category')]+=row['qty']
    prior={row[0] for row in db.execute("SELECT DISTINCT sku FROM stock_intent WHERE state!='no_purchase' UNION SELECT DISTINCT sku FROM sale")}
    surge={item.get('sku'):item.get('factor') for item in inv.get('surge',[]) if isinstance(item,dict)}
    campaign=policy['mode']=='campaign'
    rate=inv['storage_per_day']
    fraction=Decimal('.25') if campaign else Decimal(1)
    gas=limits['acquisition_buffer']
    rows=[]
    for sku,item in catalog.items():
        name,category,kind,listed=(item.get(key) for key in ('name','category','kind','list_price'))
        if (not matches(SKU,sku) or sku in observed or sku in reserved or not normalize_term(name)
                or not isinstance(category,str) or not category.strip() or kind not in ('food','goods') or not positive(listed)):
            continue
        category_room=ns['PER_CATEGORY']-stock[category]
        if category_room<=0:
            continue
        tier='novel'
        if sku in prior:
            evidence=ns['forecast'](db,sku,now,rate,chain[0],chain[2])
            if evidence['positive_sales_12h']<2 or evidence['net_contribution_12h']<=0:
                continue
            tier='proven'
        grade_prices=[prices[sku,grade] for grade in sales.GRADES if (sku,grade) in prices]
        if not grade_prices:
            continue
        factor=surge.get(sku,1)
        if type(factor) not in (int,float) or not 1<=factor<=10:
            continue
        revenue=min(net_price(amount,chain) for amount in grade_prices)
        room=limits['spend_room']-gas
        upper=min(listed*80//100,ns['candidate_cost'](item,factor),room,revenue-gas-1)
        lower=0
        while lower<upper:
            cost=(lower+upper+1)//2
            carry=carry_charge(cost,rate,fraction) if kind=='goods' else 0
            if cost+carry<=room and cost+carry+gas<revenue:
                lower=cost
            else:
                upper=cost-1
        if lower<=0:
            continue
        rows.append((boost.get(sku,0),revenue,{'sku':sku,'name':name,'kind':kind,'category':category,'tier':tier,
                    'list_price':listed,'category_room':category_room,'options':[{'qty':1,'scenario':tier,
                    'target':1,'horizon_hours':ns['FOOD_TRIAL_MIN_HOURS'] if kind=='food' else None,'estimated_ceiling':lower}]}))
    rows.sort(key=lambda row:(-row[0],row[2]['tier']!='proven',-row[1],row[2]['sku']))
    return [row[2] for row in rows[:line_cap]]


def additional_plan_budget(context, selected):
    tag=context.get(TAG)
    if tag is None or tag['mode']!='campaign':
        return True
    finance=context['finance']
    rate=finance['campaign_rate']
    risk=sum(line['goods_ceiling']+finance['acquisition_buffer']+
             (carry_charge(line['goods_ceiling'],rate,Decimal('.25')) if line['kind']=='goods' else 0) for line in selected)
    return risk<=finance['spend_room']


def campaign_charge(ns, db, market, inv, chain, now, intent, tag, raw, quote, line):
    sales=ns['sales']
    storage=sales.whole(inv.get('storage_due_with_next_lot'))
    forum=sales.whole(inv.get('next_dislike_fee'))
    if raw['storage']!=storage or raw['forum_fees']!=forum:
        raise sales.Unavailable('charged dues differ from authoritative accruals')
    dues=storage+forum
    goods=raw['goods']
    new_fees=quote['total']-dues-goods
    gas=sales.acquisition_network_buffer(chain[2])
    carry=carry_charge(goods,inv['storage_per_day'],Decimal('.25')) if line['kind']=='goods' else 0
    limits=context_capacity(ns,db,market,inv,now,chain,tag,exclude=intent)
    risk=goods+new_fees+gas+carry
    pending=limits['pending_cost']
    equity_after=limits['equity_at_cost']-dues-new_fees-gas
    if (new_fees<0 or risk>limits['spend_room']
            or limits['cash']-quote['total']-gas < limits['cash_reserve']-dues+pending+carry
            or (limits['stock_cost']+pending+goods)*100 > equity_after*85):
        raise sales.Unavailable('campaign quote exceeds cash, risk or inventory authority')
    return risk


def make_callbacks(ns):
    sales=ns['sales']
    original_validate=ns['validate_quote']

    def draft_capacity(db,market,inv,now,chain):
        return context_capacity(ns,db,market,inv,now,chain,market.draft_policy)

    def choose(db,market,inv,catalog,chain,limits,now,line_cap):
        return shortlist(ns,db,market,inv,catalog,chain,limits,now,line_cap,market.draft_policy)

    def execution_capacity(db,market,inv,now,chain,plan):
        return context_capacity(ns,db,market,inv,now,chain,plan_tag(plan))

    def verify_quote(db,market,inv,chain,now,plan,intent,raw,line,legacy_room):
        tag=plan_tag(plan)
        if tag is None or tag['mode']=='normal':
            return original_validate(raw,line,market,inv,chain,now,legacy_room)
        if not scope_current(db,market,tag,now):
            raise sales.Unavailable('campaign scope changed before quote validation')
        prices=price_feed(now,market.own_url,sales.GRADES)
        quote=ns['campaign_validate'](raw,line,market,inv,chain,now,prices)
        quote['campaign_risk']=campaign_charge(ns,db,market,inv,chain,now,intent,tag,raw,quote,line)
        return quote

    def marginal(unit,line,inv,chain,prices):
        amount=prices.get((unit['sku'],unit['grade']))
        if amount is None:
            return False
        cost=unit['cost']
        carry=carry_charge(cost,inv['storage_per_day'],Decimal('.25')) if line['kind']=='goods' else 0
        return net_price(amount,chain)>cost+carry+sales.acquisition_network_buffer(chain[2])

    def final_scope(db,market,inv,chain,now,plan,intent,raw,quote,line):
        if not scope_before_execution(db,market,plan,now):
            return False
        if 'campaign_risk' not in quote:
            return True
        try:
            return campaign_charge(ns,db,market,inv,chain,now,intent,plan_tag(plan),raw,quote,line)==quote['campaign_risk']
        except sales.Unavailable:
            return False

    def record_risk(db,market,plan,intent,quote):
        if 'campaign_risk' in quote:
            db.execute('INSERT INTO stock12_risk VALUES(?,?,?,?)',
                       (intent,market.wallet,plan_tag(plan)['campaign_id'],quote['campaign_risk']))

    ns.update(TAG=TAG,draft_capacity=draft_capacity,choose=choose,execution_capacity=execution_capacity,
              scope_before_approval=scope_before_approval,scope_before_execution=scope_before_execution,
              additional_plan_budget=additional_plan_budget,verify_quote=verify_quote,marginal=marginal,
              final_scope=final_scope,record_risk=record_risk)


def replace_once(source, old, new):
    if source.count(old)!=1:
        raise RuntimeError('pinned parent hook does not match')
    return source.replace(old,new,1)


def install_hooks(source, path, ns):
    tree=ast.parse(source)
    definitions={node.name:ast.get_source_segment(source,node) for node in tree.body if isinstance(node,ast.FunctionDef)}
    patches={
        'stock_context':[
            ('limits = capacity(db, inv, now, chain)','limits = draft_capacity(db, market, inv, now, chain)'),
            ('if "acquisition_buffer" in previous.get("finance", {}):','if "acquisition_buffer" in previous.get("finance", {}) and previous.get(TAG)==market.draft_policy:'),
            ('rows = candidates(db, inv, catalog, chain, limits, now)','rows = choose(db, market, inv, catalog, chain, limits, now, line_cap)'),
            ('    ident = secrets.token_hex(16)','    context[TAG] = market.draft_policy\n    ident = secrets.token_hex(16)')],
        'stock_plan':[
            ('        if not isinstance(decision,dict)','        if not scope_before_approval(db,market,row,now):\n            return {"status":"invalid_policy_scope"}\n        if not isinstance(decision,dict)'),
            ('                or novel>context["novel_limit"]):','                or novel>context["novel_limit"] or not additional_plan_budget(context,selected)):')],
        'stock_execute':[
            ('        approved = json.loads(plan["decision"])["lines"]','        if not scope_before_execution(db,market,plan,now):\n            return {"status":"invalid_policy_scope"}\n        approved = json.loads(plan["decision"])["lines"]'),
            ('limits=capacity(db,inv,now,chain)','limits=execution_capacity(db,market,inv,now,chain,plan)'),
            ('quote=validate_quote(raw,line,market,after,chain,fresh_time,fresh_limits["spend_room"])','quote=verify_quote(db,market,after,chain,fresh_time,plan,ident,raw,line,fresh_limits["spend_room"])'),
            ('        if sales.one(db,"SELECT id FROM stock_intent WHERE quote=?",quote["quote"]):','        if not final_scope(db,market,after,chain,armed_now,plan,ident,raw,quote,line):\n            db.execute("UPDATE stock_intent SET state=\'no_purchase\' WHERE id=? AND state=\'reserved\'",(ident,))\n            return {"status":"prepayment_policy_recheck_failed"}\n        if sales.one(db,"SELECT id FROM stock_intent WHERE quote=?",quote["quote"]):'),
            ('        log(db,now,"wallet_send_started",ident,total=quote["total"])','        record_risk(db,market,plan,ident,quote)\n        log(db,now,"wallet_send_started",ident,total=quote["total"])')],
    }
    for name, edits in patches.items():
        code=definitions[name]
        for old,new in edits:
            code=replace_once(code,old,new)
        exec(compile(code,str(path),'exec'),ns)
    code=definitions['validate_quote']
    code=replace_once(code,'def validate_quote(quote, line, market, inv, chain, now, spend_room):',
                      'def campaign_validate(quote, line, market, inv, chain, now, prices):')
    code=replace_once(code,' or total+sales.acquisition_network_buffer(network)>spend_room','')
    code=replace_once(code,'storage>sales.whole(inv.get("storage_due_with_next_lot"))+1','storage!=sales.whole(inv.get("storage_due_with_next_lot"))')
    code=replace_once(code,'forum>sales.whole(inv.get("next_dislike_fee"))','forum!=sales.whole(inv.get("next_dislike_fee"))')
    start=code.index('        base = unit["list_price"]')
    end=code.index('    if cost_sum != gross:',start)
    code=code[:start]+('        if not marginal(unit,line,inv,chain,prices):\n'
                       '            raise sales.Unavailable("actual-grade settled comparables do not cover new costs")\n')+code[end:]
    exec(compile(code,str(path),'exec'),ns)


def load_original():
    path=Path.cwd() / 'host_inputs' / 'legacy-stock8.py'
    source=path.read_bytes()
    if not hmac.compare_digest(hashlib.sha256(source).hexdigest(),DIGEST):
        raise RuntimeError('legacy stock digest mismatch')
    ns={'__name__':'logic','__file__':str(path)}
    exec(compile(source,str(path),'exec'),ns)
    return source.decode('utf-8'),path,ns


_TEST_SETUP=None


def public_result(result):
    if result['status']!='draft':
        return {key:result[key] for key in ('status','opens_at','closes_at') if key in result}
    context=result['context']
    choices=[]
    for row in context['choices']:
        choices.append({key:row[key] for key in ('sku','name','category','kind','list_price')} |
                       {'options':[{key:option[key] for key in ('qty','scenario')} for option in row['options']]})
    return {'status':'draft','plan':result['plan'],'context':{'opens_at':context['opens_at'],'closes_at':context['closes_at'],
            'limits':{'lines':context['limits']['lines']},'choices':choices}}


def run(args,kit):
    if not isinstance(args,dict):
        return {'status':'invalid_action'}
    action=args.get('action')
    allowed={'context':{'action','line_cap'},'plan':{'action','plan','decision'},'execute':{'action'},'reconcile':{'action'}}
    if not isinstance(action,str) or action not in allowed or set(args)-allowed[action]:
        return {'status':'invalid_action'}
    try:
        source,path,ns=load_original()
        original_ledger=ns['ledger']
        original_market=ns['Market']
        test_db=None
        if getattr(kit,'testing',False):
            if _TEST_SETUP is None:
                return {'status':'synthetic_world_required'}
            original_market,test_db=_TEST_SETUP(ns,kit)

        def open_ledger(wallet):
            db=original_ledger(wallet) if test_db is None else original_ledger(wallet,db_path=test_db)
            try:
                db.executescript(SCHEMA)
                return db
            except Exception:
                db.close()
                raise

        def market_factory(current_kit):
            market=original_market(current_kit)
            market.own_url=getattr(current_kit,'shop_url',None)
            return market

        make_callbacks(ns)
        install_hooks(source,path,ns)
        ns['ledger']=open_ledger
        ns['Market']=market_factory
        if action=='context':
            cap=args.get('line_cap',5)
            if type(cap) is not int or not 1<=cap<=ns['WINDOW_LINES']:
                return {'status':'invalid_line_cap'}
            parent_context=ns['stock_context']

            def context_with_policy(db,market,now,line_cap):
                market.draft_policy=policy_at(now)
                if market.draft_policy is None:
                    return {'status':'invalid_policy_scope'}
                return parent_context(db,market,now,line_cap)

            ns['stock_context']=context_with_policy
            return public_result(ns['run']({'action':'context','line_cap':min(cap,5)},kit))
        return ns['run'](args,kit)
    except (OSError,RuntimeError,ValueError,TypeError,KeyError,sqlite3.Error):
        return {'status':'authoritative_check_unavailable'}
