"""R4 model-selected, audited wholesale procurement. OpenAI Codex GPT-6.2 Sol."""
from base64 import b64decode
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import secrets
import sqlite3
import sys
import time

import httpx
from eth_account import Account
from eth_account.messages import encode_defunct

DEPENDENCY_SHA256 = "a3e52d089719e77e2dcc3e77b523de82221c243f5278bb922ad73f0a115a5c0b"
dependency = Path.cwd() / "codex-r4" / "dispatcher.py"
if __name__ == "logic":
    if hashlib.sha256(dependency.read_bytes()).hexdigest() != DEPENDENCY_SHA256:
        raise RuntimeError("dispatcher dependency differs from the forged financial contract")
sys.path.insert(0, str(dependency.parent))
import dispatcher as sales

WALLET_MAX_CREDITS = 1000000
WINDOW_LINES = 10
PER_SKU = 20
PER_CATEGORY = 24
PREPARE_LEAD = 240
APPROVAL_TTL = 600
END_BUFFER = 22
HOUR = 3600
REFUND_STRESS = .05
FOOD_HANDLING_BUFFER = 180
FOOD_TRIAL_MIN_HOURS = 2
SCHEMA = """
CREATE TABLE IF NOT EXISTS stock_observation (
    at INTEGER PRIMARY KEY, skus TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stockout_observation (
    demand TEXT PRIMARY KEY, sku TEXT NOT NULL, at REAL NOT NULL, reason TEXT NOT NULL, resolved REAL
);
CREATE TABLE IF NOT EXISTS stock_plan (
    window TEXT PRIMARY KEY, id TEXT NOT NULL UNIQUE, scope TEXT NOT NULL, planned REAL NOT NULL,
    expires REAL NOT NULL, opens REAL NOT NULL, closes REAL NOT NULL,
    choices TEXT NOT NULL, decision TEXT, status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stock_intent (
    id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES stock_plan(id), sku TEXT NOT NULL,
    qty INTEGER NOT NULL, quote TEXT UNIQUE, total INTEGER NOT NULL, marker TEXT,
    recipient TEXT, wei TEXT, units TEXT, tx TEXT UNIQUE, chain_anchor INTEGER, ledger_anchor INTEGER,
    state TEXT NOT NULL CHECK(state IN (
        'reserved','no_purchase','sending','unknown','paid','accepted','arrived')),
    created REAL NOT NULL, retry_at REAL NOT NULL DEFAULT 0, delivered TEXT,
    UNIQUE(plan_id,sku)
);
CREATE INDEX IF NOT EXISTS stock_intent_state ON stock_intent(state,retry_at);
CREATE TABLE IF NOT EXISTS stock_audit (
    id INTEGER PRIMARY KEY, at REAL NOT NULL, event TEXT NOT NULL, reference TEXT NOT NULL,
    summary TEXT NOT NULL
);
"""
PENDING = ("reserved", "sending", "unknown", "paid", "accepted")


def entries(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def log(db, now, event, ref, **summary):
    db.execute("INSERT INTO stock_audit(at,event,reference,summary) VALUES(?,?,?,?)",
               (now, event, ref, entries(summary)))


def ledger(wallet, db_path=sales.DB):
    db = sales.open_db(db_path, wallet)
    db.executescript(SCHEMA)
    return db


class Market(sales.Market):
    def snapshot(self):
        inv = self.get("/api/inventory", auth=True)
        if inv.get("round") != 4 or sales.address(inv.get("wallet")) != self.wallet:
            raise sales.Unavailable("wrong inventory identity")
        if not isinstance(inv.get("units"), list):
            raise sales.Unavailable("missing inventory")
        return inv

    def catalog(self):
        raw = self.get("/api/catalog")
        if not isinstance(raw, list):
            raise sales.Unavailable("invalid catalog")
        return {x["sku"]: x for x in raw if isinstance(x, dict)
                and isinstance(x.get("sku"), str) and sales.SKU.fullmatch(x["sku"])}

    def supply(self, payload):
        response = httpx.post(sales.MARKET + "/api/supply",
                              headers={"authorization": "Bearer " + self.kit.token("shop")},
                              json=payload, timeout=self.timeout(), trust_env=False)
        if response.status_code not in (200, 402):
            return response.status_code, None
        value = response.json()
        if not isinstance(value, dict):
            raise sales.Unavailable("malformed wholesale response")
        return response.status_code, value


def window(inv):
    raw = inv.get("restock") or {}
    opens, closes = sales.number(raw.get("opens_at")), sales.number(raw.get("closes_at"))
    if not 15 <= closes - opens <= 600:
        raise sales.Unavailable("unexpected wholesale window")
    return f"{opens:.3f}/{closes:.3f}", opens, closes


def pending(db):
    return db.execute("SELECT * FROM stock_intent WHERE state IN ('reserved','sending','unknown','paid','accepted')").fetchall()


def quality(inv, now):
    return sales.usable_units(inv["units"], now)


def capacity(db, inv, now, chain, exclude=None):
    credit, _, network, _ = chain
    acquisition_buffer = sales.acquisition_network_buffer(network)
    cash = sales.whole(inv.get("balance"))
    bankrupt = sales.whole(inv.get("bankrupt_line"), 1)
    stock = quality(inv, now)
    stock_cost = sum(u["cost"] for u in stock)
    rows = [i for i in pending(db) if i["id"] != exclude]
    pending_cost = sum(i["total"] + acquisition_buffer for i in rows)
    active_refunds = sum(int(row[0]) for row in db.execute("SELECT wei FROM refund WHERE status!='refunded'"))
    warranty = sum(int(row[0]) + int(row[1]) for row in db.execute("""
        SELECT expected_wei,fee_wei FROM sale WHERE status='settled' AND settled>?
        AND id NOT IN (SELECT sale_id FROM refund)
    """, (now-sales.WARRANTY,)))
    # Cash reserves are explicit risk hypotheses. Keep accrued costs and a
    # further two days of carrying cost, certified refunds, and loyalty exposure.
    rate = inv.get("storage_per_day")
    if type(rate) not in (float, int) or not math.isfinite(rate) or not 0 <= rate <= 1:
        raise sales.Unavailable("unknown storage rate")
    goods_cost = sum(u["cost"] for u in stock if u.get("kind") == "goods")
    storage = sales.whole(inv.get("storage_due_with_next_lot"))
    forum = sales.whole(inv.get("next_dislike_fee"))
    holding = storage + forum + math.ceil(goods_cost * rate * 2)
    credits_exposed = sales.one(db, "SELECT coalesce(sum(amount),0) FROM lot WHERE revoked IS NULL AND expires>?", now)[0]
    refund = math.ceil((active_refunds + warranty * REFUND_STRESS) / credit)
    reserve = bankrupt + max(1, bankrupt // 5) + holding + refund + credits_exposed
    equity = cash + stock_cost
    headroom = max(0, min(cash - reserve - pending_cost, equity * 80//100 - stock_cost - pending_cost))
    return {"cash": cash, "stock_cost": stock_cost, "equity_at_cost": equity, "pending_cost": pending_cost,
            "acquisition_buffer": acquisition_buffer, "cash_reserve": reserve, "holding_and_dues": holding, "refund_buffer": refund,
            "benefits_buffer": credits_exposed, "inventory_target": equity*65//100,
            "inventory_maximum": equity*80//100, "spend_room": headroom, "credit_wei": credit}


def observe(db, stock, now):
    skus = sorted({u["sku"] for u in stock if not sales.pinned(db, u["unit"])})
    db.execute("INSERT OR IGNORE INTO stock_observation VALUES(?,?)", (int(now)//60*60, entries(skus)))


def paid_sales(db, sku, now, hours):
    return db.execute("""
        SELECT settled,price,cost,base,expected_wei FROM sale
        WHERE sku=? AND status='settled' AND broken IS NULL AND market_order IS NOT NULL AND settled BETWEEN ? AND ?
    """, (sku, now-hours*HOUR, now)).fetchall()


def forecast(db, sku, now, rate, credit, network):
    snapshots = [(row["at"], sku in json.loads(row["skus"])) for row in db.execute(
        "SELECT * FROM stock_observation WHERE at BETWEEN ? AND ? ORDER BY at", (now-12*HOUR, now))]
    signals = {}
    for hours in (1, 3, 12):
        rows = paid_sales(db, sku, now, hours)
        begin = now - hours * HOUR
        intervals = [(max(begin,a),b) for (a, in_stock), (b, _) in zip(snapshots,snapshots[1:])
                     if in_stock and b>begin and b-a<=180]
        exposure = sum(b-a for a,b in intervals)/HOUR
        paired = sum(any(a<=row["settled"]<b for a,b in intervals) for row in rows)
        raw = len(rows)/hours
        correction = max(raw, (paired+raw*.5)/(exposure+.5)) if exposure >= .25 else raw
        # Cold-start conversion is a labeled Beta(2,2) hypothesis; missed
        # requests cannot by themselves establish proven demand.
        misses = sales.one(db, "SELECT count(*) FROM stockout_observation WHERE sku=? AND resolved IS NULL AND at BETWEEN ? AND ?",
                           sku, begin, now)[0]
        signals[str(hours)] = {"paid": len(rows), "paired_paid": paired, "exposure_hours": round(exposure,4),
                               "unique_stockouts": misses, "rate": max(correction, (len(rows)+.5*misses)/hours)}
    rows = paid_sales(db, sku, now, 12)
    contributions = [int(row["expected_wei"])/credit - row["cost"]*(1+rate) - row["base"]//100
                     - row["price"]*REFUND_STRESS - sales.acquisition_network_buffer(network) for row in rows]
    positive = sum(value>0 for value in contributions)
    current = (.65*signals["1"]["rate"] + .35*signals["3"]["rate"] if signals["1"]["paid"] >= 2
               else signals["3"]["rate"] if signals["3"]["rate"] else signals["12"]["rate"])
    return {"rate": round(max(current, signals["12"]["paid"]/12), 4),
            "positive_sales_12h": positive, "net_contribution_12h": round(sum(contributions),2), "windows": signals, "stockout_conversion_hypothesis": .5}


def quantile(mean, p):
    prob = total = math.exp(-max(0., mean))
    for i in range(PER_SKU):
        if total >= p:
            return i
        prob *= mean/(i+1)
        total += prob
    return PER_SKU


def target_options(item, evidence, horizon):
    kind = item.get("kind")
    max_hours = float(item.get("shelf_hours") or 0)/4 if kind=="food" else 24
    targets = []
    for label, hours, level in (("low", horizon, .90), ("base", horizon, .95), ("high", horizon, .975),
                                ("buffer_short", 1 if kind=="food" else 2, .975),
                                ("buffer_long", 2 if kind=="food" else 6, .975)):
        hours = min(hours,max_hours)
        if hours <= 0 or label.startswith("buffer") and hours <= horizon:
            continue
        units = quantile(min(100,evidence["rate"]*hours),level)
        if units and all(opt["target"] != units for opt in targets):
            targets.append({"scenario":label,"horizon_hours":round(hours,3),"target":units})
    return targets


def candidate_cost(item, surge):
    # Guard estimate only. The total and grades are revalidated on the quote.
    return math.ceil(sales.whole(item.get("list_price"),1)*.8*surge)


def expected_contribution(item, surge, chain, inv):
    _,bpts,network,_=chain
    listed=item["list_price"]
    # Scenario only: typical starting-cost fraction, no inferred demand.
    cost=math.ceil(listed*(.57 if item["kind"]=="goods" else .52)*surge)
    carry=math.ceil(cost*inv["storage_per_day"]) if item["kind"]=="goods" else 0
    result={}
    for grade in ("A","B"):
        base=listed*sales.GRADES[grade]//100
        adjusted=base-2*(base//100)
        result[grade]=(adjusted-adjusted*bpts//10000-network//2-cost-carry-math.ceil(base*REFUND_STRESS)
                       - sales.acquisition_network_buffer(network))
    return {"by_grade":result,"cost_assumption":cost,"carrying_assumption":carry,
            "booking":"scenario only; excludes existing sunk arrears and does not infer sales"}


def diverse_novel(rows, now):
    ranked=sorted(rows, key=lambda row:(
        row["margin_scenario"]["by_grade"]["B"]<=0,
        hashlib.sha256(f"{int(now)//1200}/{row['sku']}".encode()).digest()))
    first, extra, used = [], [], set()
    for row in ranked:
        key=(row["category"].split(">",1)[0],row["list_price"].bit_length())
        target=extra if key in used else first
        target.append(row)
        used.add(key)
    return first+extra


def candidates(db, inv, catalog, chain, limits, now):
    own = quality(inv, now)
    stock = Counter(u["sku"] for u in own)
    category = Counter(u.get("category") for u in own)
    reserved = Counter()
    for order in pending(db):
        reserved[order["sku"]] += order["qty"]
        category[catalog.get(order["sku"],{}).get("category")] += order["qty"]
    surge = {row.get("sku"): row.get("factor") for row in inv.get("surge",[]) if isinstance(row,dict)}
    prior = {row[0] for row in db.execute("SELECT DISTINCT sku FROM stock_intent WHERE state!='no_purchase'")}
    prior.update(row[0] for row in db.execute("SELECT DISTINCT sku FROM sale"))
    prior.update(stock)
    examined = prior | {row[0] for row in db.execute("SELECT DISTINCT sku FROM stockout_observation WHERE at>?",(now-12*HOUR,))}
    # Rotate a bounded catalog mix. Listing prominence never creates demand.
    novel = sorted((sku for sku in catalog if sku not in prior),
                   key=lambda sku: hashlib.sha256(f"{int(now)//1200}/{sku}".encode()).digest())[:192]
    output = []
    goods_room=max(0,limits["spend_room"]-limits["acquisition_buffer"])
    _, opens, closes = window(inv)
    horizon = max(.33,(closes-max(now,opens))/HOUR+.33)
    for sku in sorted(examined | set(novel)):
        item = catalog.get(sku) or {}
        if item.get("kind") not in ("goods","food") or not isinstance(item.get("category"),str):
            continue
        factor = surge.get(sku,1)
        if type(factor) not in (int,float) or not math.isfinite(factor) or not 1<=factor<=10:
            continue
        try:
            unit_cost = candidate_cost(item,factor)
        except sales.Unavailable:
            continue
        projected = stock[sku] + reserved[sku]
        cat_room = max(0,PER_CATEGORY-category[item["category"]])
        if unit_cost > goods_room or unit_cost>WALLET_MAX_CREDITS or not cat_room:
            continue
        evidence = forecast(db,sku,now,inv["storage_per_day"],chain[0],chain[2]) if sku in examined else {
            "rate":None,"positive_sales_12h":0,"windows":{}}
        proven = evidence["positive_sales_12h"] >= 2 and evidence.get("net_contribution_12h",0)>0
        tier = "proven" if proven else "second_trial" if evidence["positive_sales_12h"]==1 else "novel" if sku not in prior else "unproven"
        if tier == "unproven" or not proven and projected:
            continue
        margin_scenario=expected_contribution(item,factor,chain,inv)
        if tier=="novel" and max(margin_scenario["by_grade"].values())<=0:
            continue
        options = target_options(item,evidence,horizon) if proven else [
            {"scenario":tier,"horizon_hours":None,"target":1}]
        qtys = []
        for opt in options:
            qty = min(max(0,opt["target"]-projected),cat_room,PER_SKU,
                      goods_room//unit_cost,WALLET_MAX_CREDITS//unit_cost)
            if qty and all(q["qty"]!=qty for q in qtys):
                qtys.append(dict(opt,qty=qty,estimated_ceiling=qty*unit_cost))
        if qtys:
            label = item.get("name")
            output.append({"sku":sku,"name":label[:80] if isinstance(label,str) else sku,
                           "kind":item["kind"],"category":item["category"],"tier":tier,
                           "list_price":item["list_price"],"stock":stock[sku],"pending":reserved[sku],
                           "unit_ceiling":unit_cost,"category_room":cat_room,"options":qtys,"demand":evidence,
                           "margin_scenario":margin_scenario})
    established=sorted((row for row in output if row["tier"]!="novel"),
                       key=lambda row:(-(row["demand"]["rate"] or 0),row["sku"]))
    exploratory=diverse_novel((row for row in output if row["tier"]=="novel"),now)
    return established[:16]+exploratory[:24-min(16,len(established))]



def alternatives(rows, headroom, novel_limit, line_cap, acquisition_buffer):
    examples = []
    seen = set()
    for name, seek_novel, qty_i in (("broad",6,0),("balanced",max(1,min(3,line_cap-1)),1),("depth",1,-1)):
        ordered = sorted(rows,key=lambda r: r["tier"] != "novel" if name=="broad" else r["tier"] == "novel")
        budget, picks, novel = headroom, [], 0
        cats = Counter()
        for row in ordered:
            if len(picks) == line_cap or row["tier"]=="novel" and novel >= min(novel_limit,max(1,seek_novel)):
                continue
            possible = [q for q in row["options"] if q["estimated_ceiling"]+acquisition_buffer<=budget
                        and cats[row["category"]]+q["qty"]<=row["category_room"]]
            if not possible:
                continue
            choice = possible[min(qty_i,len(possible)-1)]
            budget -= choice["estimated_ceiling"]+acquisition_buffer
            picks.append({"sku":row["sku"],"qty":choice["qty"]})
            novel += row["tier"]=="novel"
            cats[row["category"]] += choice["qty"]
        key = tuple(sorted((x["sku"],x["qty"]) for x in picks))
        if picks and key not in seen:
            examples.append({"id":name,"lines":picks,"estimated_goods":headroom-budget-acquisition_buffer*len(picks)})
            seen.add(key)
    return examples


def stock_context(db, market, now, line_cap=WINDOW_LINES):
    line_cap = sales.whole(line_cap,1,WINDOW_LINES)
    inv = market.snapshot()
    chain = market.chain()
    key, opens, closes = window(inv)
    stock = quality(inv, now)
    with sales.atomic(db):
        observe(db, stock, now)
    limits = capacity(db, inv, now, chain)
    if not opens-PREPARE_LEAD <= now < closes-END_BUFFER:
        return {"status":"waiting","opens_at":opens,"closes_at":closes,"finance":limits}
    existing = sales.one(db, "SELECT * FROM stock_plan WHERE window=?", key)
    if existing and existing["status"]!="draft":
        return {"status":existing["status"],"opens_at":opens,"closes_at":closes}
    # Catalog and forecast are not repeatedly fetched after model approval.
    if existing and now < existing["expires"]:
        previous = json.loads(existing["choices"])
        if "acquisition_buffer" in previous.get("finance", {}):
            return {"status":"draft","plan":existing["id"],"context":previous}
        # The new fee policy must be reflected in a fresh candidate set.
        # Only obsolete drafts are refreshed, never approvals or intents.
        with sales.atomic(db):
            db.execute("UPDATE stock_plan SET expires=? WHERE id=? AND status='draft'", (now,existing["id"]))
    catalog = market.catalog()
    rows = candidates(db, inv, catalog, chain, limits, now)
    novel_limit = line_cap
    context = {"opens_at":opens,"closes_at":closes,"finance":limits, "novel_limit":novel_limit,
               "limits":{"lines":line_cap,"per_sku":PER_SKU,"per_category":PER_CATEGORY},
               "choices":rows,"alternatives":alternatives(rows,limits["spend_room"],novel_limit,line_cap,limits["acquisition_buffer"]),
               "cold_start":"No measured demand for untested SKUs. A novel choice is a single-unit trial.",
               "exposure_note":"Measured from actual available R4 stock. Missing observations are unknown."}
    ident = secrets.token_hex(16)
    expiry = min(now+APPROVAL_TTL, closes-END_BUFFER)
    with sales.atomic(db):
        db.execute("""
            INSERT INTO stock_plan VALUES(?,?,?,?,?,?,?,?,NULL,'draft')
            ON CONFLICT(window) DO UPDATE SET id=excluded.id,scope=excluded.scope,planned=excluded.planned,
            expires=excluded.expires,choices=excluded.choices WHERE stock_plan.status='draft'
            AND stock_plan.expires<=?
        """,(key,ident,market.wallet,now,expiry,opens,closes,entries(context),now))
        row = sales.one(db,"SELECT * FROM stock_plan WHERE window=?",key)
        if row["id"] == ident:
            log(db,now,"prepared_candidates",ident,choices=len(rows),opens=opens,closes=closes)
    if row["status"] != "draft":
        return {"status":row["status"],"opens_at":opens,"closes_at":closes}
    return {"status":"draft","plan":row["id"],"context":json.loads(row["choices"])}


def stock_plan(db, market, now, ident, decision):
    with sales.atomic(db):
        row = sales.one(db,"SELECT * FROM stock_plan WHERE id=?",ident)
        if not row or row["scope"]!=market.wallet or row["status"]!="draft" or row["expires"]<=now:
            return {"status":"invalid_plan"}
        if not isinstance(decision,dict) or set(decision)-{"action","lines","reason"}:
            return {"status":"invalid_choice"}
        action = decision.get("action")
        reason = decision.get("reason")
        reason_status = "complete" if isinstance(reason,str) and 1<=len(reason.strip())<=160 else "incomplete"
        if reason_status=="incomplete":
            reason="Model selection recorded without a usable explanation"
        if action=="hold" and not decision.get("lines"):
            db.execute("UPDATE stock_plan SET status='hold',decision=? WHERE id=?",(entries(decision),ident))
            log(db,now,"model_hold",ident,reason=reason,reason_status=reason_status)
            return {"status":"hold"}
        lines = decision.get("lines")
        context = json.loads(row["choices"])
        if action!="buy" or not isinstance(lines,list) or not 1<=len(lines)<=context["limits"]["lines"]:
            return {"status":"invalid_choice"}
        if "acquisition_buffer" not in context.get("finance", {}):
            return {"status":"stale_draft_policy"}
        choices = {r["sku"]:r for r in context["choices"]}
        selected, seen, novel, ceiling = [], set(), 0, 0
        category_totals = Counter()
        for line in lines:
            if (not isinstance(line,dict) or set(line)!={"sku","qty"} or not isinstance(line["sku"],str)
                    or line["sku"] in seen or type(line["qty"]) is not int or line["sku"] not in choices):
                return {"status":"invalid_choice"}
            choice = choices[line["sku"]]
            fit = next((opt for opt in choice["options"] if opt["qty"]==line["qty"]),None)
            if not fit:
                return {"status":"quantity_not_offered"}
            seen.add(line["sku"])
            novel += choice["tier"]=="novel"
            ceiling += fit["estimated_ceiling"]
            category_totals[choice["category"]] += fit["qty"]
            if category_totals[choice["category"]] > choice["category_room"]:
                return {"status":"category_limit"}
            selected.append({"sku":line["sku"],"qty":fit["qty"],"scenario":fit["scenario"],"target":fit["target"],
                             "goods_ceiling":fit["estimated_ceiling"],"tier":choice["tier"],
                             "coverage_hours":fit.get("horizon_hours"),
                             "list_price":choice["list_price"],"kind":choice["kind"],"category":choice["category"]})
        if (ceiling+len(selected)*context["finance"]["acquisition_buffer"]>context["finance"]["spend_room"]
                or novel>context["novel_limit"]):
            return {"status":"basket_exceeds_limit"}
        db.execute("UPDATE stock_plan SET status='ready',decision=? WHERE id=?",
                   (entries({"lines":selected,"reason":reason}),ident))
        log(db,now,"model_approved",ident,choice=selected,reason=reason,reason_status=reason_status,goods_ceiling=ceiling)
    return {"status":"ready","lines":len(selected)}


def validate_quote(quote, line, market, inv, chain, now, spend_room):
    if not isinstance(quote,dict) or not re.fullmatch(r"q-[0-9a-f]{16}",str(quote.get("quote",""))):
        raise sales.Unavailable("missing wholesale quote")
    credit,bps,network,recipient = chain
    gross = sales.whole(quote.get("goods"),1)
    storage, forum = sales.whole(quote.get("storage")), sales.whole(quote.get("forum_fees"))
    total = sales.whole(quote.get("total"),1,WALLET_MAX_CREDITS)
    if (total!=gross+storage+forum or gross>line["goods_ceiling"] or total+sales.acquisition_network_buffer(network)>spend_room
            or storage>sales.whole(inv.get("storage_due_with_next_lot"))+1
            or forum>sales.whole(inv.get("next_dislike_fee"))):
        raise sales.Unavailable("wholesale quote exceeds verified costs or authority")
    expires = sales.whole(quote.get("expires_in"),1,3600)
    if expires<END_BUFFER:
        raise sales.Unavailable("wholesale quote is too close to expiry")
    marker = "0x"+hashlib.sha256(quote["quote"].encode()).hexdigest()
    pay = quote.get("pay")
    if (not isinstance(pay,dict) or sales.address(pay.get("to"))!=recipient or pay.get("data")!=marker
            or pay.get("wei")!=str(total*credit)):
        raise sales.Unavailable("wholesale payment does not match bank facts")
    units = quote.get("units")
    if not isinstance(units,list) or len(units)!=line["qty"]:
        raise sales.Unavailable("wholesale lot quantity differs")
    ids, cost_sum = set(), 0
    for unit in units:
        if (not isinstance(unit,dict) or unit.get("sku")!=line["sku"] or unit.get("kind")!=line["kind"]
                or unit.get("list_price")!=line["list_price"] or unit.get("category")!=line["category"]
                or not re.fullmatch(r"u-[0-9a-f]{12}",str(unit.get("unit","")))
                or unit["unit"] in ids or unit.get("grade") not in sales.GRADES):
            raise sales.Unavailable("wrong unit in wholesale lot")
        ids.add(unit["unit"])
        cost = sales.whole(unit.get("cost"),1)
        cost_sum += cost
        if line["kind"]=="food":
            expiry = sales.number(unit.get("expires_at"))
            if line["tier"] in ("novel", "second_trial"):
                coverage = FOOD_TRIAL_MIN_HOURS
            else:
                coverage = sales.number(line.get("coverage_hours"))
                if not 0 < coverage <= 24:
                    raise sales.Unavailable("approved food coverage is invalid")
            if expiry-now < coverage*HOUR+FOOD_HANDLING_BUFFER:
                raise sales.Unavailable("food lot has inadequate life for the approved coverage")
        elif unit.get("expires_at") is not None:
            raise sales.Unavailable("goods unexpectedly expires")
        base = unit["list_price"] * sales.GRADES[unit["grade"]] //100
        # Reserve both headline 1% benefits, the clearing fees, acquisition
        # overhead, an explicit refund buffer and one day storage under current R4 rates.
        discounted = base - 2*(base//100)
        received = discounted - discounted*bps//10000 - network//2
        holding = math.ceil(cost * inv["storage_per_day"]) if line["kind"]=="goods" else 0
        if received <= cost+holding+math.ceil((storage+forum+sales.acquisition_network_buffer(network))/len(units))+math.ceil(base*REFUND_STRESS):
            raise sales.Unavailable("wholesale grade/expiry and fees imply inadequate margin")
    if cost_sum != gross:
        raise sales.Unavailable("wholesale goods total differs from unit costs")
    return {"quote":quote["quote"],"total":total,"marker":marker,"recipient":recipient,
            "wei":str(total*credit),"units":sorted(ids)}


def ledger_tail(market):
    rows = market.get("/api/ledger",params={"after":-1})
    if not isinstance(rows,list):
        raise sales.Unavailable("invalid market ledger")
    if rows:
        last=rows[-1]
        return sales.whole(last["seq"],1)
    return 0


def no_purchase(db, intent, now, reason):
    with sales.atomic(db):
        db.execute("UPDATE stock_intent SET state='no_purchase' WHERE id=? AND state='reserved'", (intent,))
        log(db,now,"wholesale_declined_without_payment",intent,reason=reason)
    return {"status":"no_purchase","reason":reason}


def stock_execute(db, market, now, pay):
    started = time.monotonic()
    inv = market.snapshot()
    key, opens, closes = window(inv)
    if not opens <= now < closes - END_BUFFER or (inv.get("restock") or {}).get("open") is not True:
        return {"status":"window_closed"}
    chain = market.chain()
    catalog = market.catalog()
    with sales.atomic(db):
        # A timeout can hide a sent transaction. Stop advancing wallet nonce
        # until durable evidence resolves it.
        if sales.one(db,"SELECT sale_id FROM refund WHERE status IN ('sending','pending_unknown')"):
            return {"status":"unresolved_refund_payment"}
        if sales.one(db,"SELECT id FROM stock_intent WHERE state IN ('reserved','sending','unknown','paid','accepted')"):
            return {"status":"unresolved_prior_payment"}
        if sales.one(db,"SELECT id FROM stock_intent WHERE created>? LIMIT 1",now-10):
            return {"status":"supply_gap"}
        plan = sales.one(db,"SELECT * FROM stock_plan WHERE window=? AND status='ready'",key)
        if not plan or plan["expires"]<=now or plan["scope"]!=market.wallet:
            return {"status":"no_approved_open_plan"}
        approved = json.loads(plan["decision"])["lines"]
        for line in approved:
            row = sales.one(db,"SELECT id FROM stock_intent WHERE plan_id=? AND sku=?",plan["id"],line["sku"])
            if not row:
                break
        else:
            db.execute("UPDATE stock_plan SET status='attempted' WHERE id=?",(plan["id"],))
            return {"status":"attempted"}
        item=catalog.get(line["sku"],{})
        if (item.get("list_price"),item.get("kind"),item.get("category"))!=(line["list_price"],line["kind"],line["category"]):
            return {"status":"catalog_changed"}
        physical=quality(inv,now)
        outstanding=pending(db)
        projected=sum(u["sku"]==line["sku"] for u in physical)+sum(x["qty"] for x in outstanding if x["sku"]==line["sku"])
        category=sum(u.get("category")==line["category"] for u in physical)+sum(
            x["qty"] for x in outstanding if catalog.get(x["sku"],{}).get("category")==line["category"])
        if projected+line["qty"]>line["target"] or category+line["qty"]>PER_CATEGORY:
            return {"status":"fresh_quantity_limit"}
        limits=capacity(db,inv,now,chain)
        if limits["spend_room"]<line["goods_ceiling"]+limits["acquisition_buffer"]:
            return {"status":"fresh_cash_limit"}
        ident=secrets.token_hex(16)
        db.execute("""INSERT INTO stock_intent(id,plan_id,sku,qty,total,state,created) VALUES(?,?,?,?,?,'reserved',?)""",
                   (ident,plan["id"],line["sku"],line["qty"],line["goods_ceiling"],now))
        log(db,now,"wholesale_intent_reserved",ident,sku=line["sku"],qty=line["qty"])
    try:
        status, raw = market.supply({"sku":line["sku"],"qty":line["qty"]})
        if status!=402:
            return no_purchase(db,ident,now,"non_quote_response_no_payment")
        quote_received = time.monotonic()
        # Revalidate the exact quote against a new authoritative balance and window.
        after=market.snapshot()
        _, _, fresh_closes = window(after)
        if window(after)[0]!=key or (after.get("restock") or {}).get("open") is not True:
            return no_purchase(db,ident,now,"window_changed_before_payment")
        fresh_time = now + time.monotonic() - started
        if market.chain()!=chain:
            return no_purchase(db,ident,now,"bank_terms_changed_before_payment")
        fresh_limits=capacity(db,after,fresh_time,chain,exclude=ident)
        quote=validate_quote(raw,line,market,after,chain,fresh_time,fresh_limits["spend_room"])
        current_units = quality(after,fresh_time)
        current_pending = [row for row in pending(db) if row["id"]!=ident]
        if (sum(u["sku"]==line["sku"] for u in current_units)
                + sum(x["qty"] for x in current_pending if x["sku"]==line["sku"])
                + line["qty"] > line["target"]):
            return no_purchase(db,ident,now,"stock_changed_before_payment")
        if (sum(u.get("category")==line["category"] for u in current_units)
                + sum(x["qty"] for x in current_pending if catalog.get(x["sku"],{}).get("category")==line["category"])
                + line["qty"] > PER_CATEGORY):
            return no_purchase(db,ident,now,"category_changed_before_payment")
        chain_before=sales.hex_int(market.rpc("eth_blockNumber"))
        ledger_before=ledger_tail(market)
        if (now+time.monotonic()-started >= fresh_closes-END_BUFFER
                or time.monotonic()-quote_received >= raw["expires_in"]-END_BUFFER):
            return no_purchase(db,ident,now,"insufficient_time_before_payment")
    except (httpx.HTTPError,sales.Unavailable,OSError,ValueError,TypeError,KeyError,AttributeError):
        return no_purchase(db,ident,now,"invalid_or_unavailable_quote_no_payment")
    with sales.atomic(db):
        # This commit must be durable before calling the wallet. A second
        # process cannot consume the same quote, even after a crash.
        armed_now = now+time.monotonic()-started
        if (armed_now >= min(fresh_closes-END_BUFFER,plan["expires"])
                or time.monotonic()-quote_received >= raw["expires_in"]-END_BUFFER
                or sales.one(db,"SELECT id FROM stock_intent WHERE id!=? AND state IN ('reserved','sending','unknown','paid','accepted')",ident)
                or sales.one(db,"SELECT sale_id FROM refund WHERE status IN ('sending','pending_unknown')")):
            db.execute("UPDATE stock_intent SET state='no_purchase' WHERE id=? AND state='reserved'",(ident,))
            return {"status":"prepayment_recheck_failed"}
        if sales.one(db,"SELECT id FROM stock_intent WHERE quote=?",quote["quote"]):
            db.execute("UPDATE stock_intent SET state='no_purchase' WHERE id=?",(ident,))
            return {"status":"duplicate_quote"}
        changed=db.execute("""UPDATE stock_intent SET state='sending',quote=?,total=?,marker=?,recipient=?,wei=?,units=?,
                          chain_anchor=?,ledger_anchor=? WHERE id=? AND state='reserved'""",
                   (quote["quote"],quote["total"],quote["marker"],quote["recipient"],quote["wei"],
                    entries(quote["units"]),chain_before,ledger_before,ident))
        if changed.rowcount != 1:
            return {"status":"prepayment_reservation_no_longer_current"}
        log(db,now,"wallet_send_started",ident,total=quote["total"])
    try:
        tx = sales.tx_hash(pay(quote["recipient"],int(quote["wei"]),quote["marker"]))
    except Exception:
        tx=None
    with sales.atomic(db):
        db.execute("UPDATE stock_intent SET tx=?,state=?,retry_at=? WHERE id=? AND state='sending'",
                   (tx,"paid" if tx else "unknown",now,ident))
        log(db,now,"wallet_result",ident,verified_hash=bool(tx))
    return {"status":"paid_pending_confirmation" if tx else "payment_unknown"}



def paid_ledger(market, item):
    after=item["ledger_anchor"]
    wanted=set(json.loads(item["units"]))
    prev=None
    for _ in range(2):
        rows=market.get("/api/ledger",params={"after":after})
        if not isinstance(rows,list):
            raise sales.Unavailable("invalid supply ledger")
        for event in rows:
            seq=sales.whole(event["seq"],1)
            if seq!=after+1 or prev is not None and event.get("prev")!=prev:
                raise sales.Unavailable("noncontiguous supply ledger")
            prev=sales.ledger_hash(event)
            after=seq
            data=event["data"]
            if event.get("kind")!="supply" or event.get("round")!=4 or sales.tx_hash(data.get("tx_hash"))!=item["tx"]:
                continue
            if (data.get("shop")!=sales.SHOP or data.get("sku")!=item["sku"] or data.get("qty")!=item["qty"]
                    or set(data.get("units",[]))!=wanted
                    or sum(sales.whole(data.get(k,0)) for k in ("total","storage","fees"))!=item["total"]):
                raise sales.Unavailable("conflicting wholesale ledger evidence")
            return seq
        if len(rows)<500:
            break
    return None


def find_unknown(market, item):
    upper=sales.hex_int(market.rpc("eth_blockNumber"))
    first=item["chain_anchor"]
    if first is None:
        return None
    # This bounded search is automatic. Older unresolved cases can be
    # investigated by an operator without authorizing a second wallet send.
    for block in range(first,min(upper-2,first+35)+1):
        data=market.rpc("eth_getBlockByNumber",hex(block),True)
        if not isinstance(data,dict):
            return None
        for tx in data.get("transactions",[]):
            if (sales.address(tx.get("from"))==market.wallet and sales.address(tx.get("to"))==item["recipient"]
                    and tx.get("input")==item["marker"] and sales.hex_int(tx.get("value"))==int(item["wei"])):
                return sales.tx_hash(tx.get("hash"))
    return None


def receipt_valid(market, item, tx):
    return market.transaction(tx,market.wallet,item["recipient"],int(item["wei"]),item["marker"]) == market.wallet


def verified_unit(unit, sku, market_wallet):
    if not isinstance(unit,dict) or unit.get("sku")!=sku or not isinstance(unit.get("cert"),dict):
        return False
    signed=unit["cert"]
    claims=signed.get("cert")
    if (not isinstance(claims,dict) or claims.get("shop")!=sales.SHOP or claims.get("sku")!=sku
            or claims.get("unit")!=unit.get("unit")):
        return False
    try:
        signer=Account.recover_message(encode_defunct(primitive=sales.canonical(claims)),
                                       signature=b64decode(signed["sig"],validate=True))
    except Exception:
        return False
    return sales.address(signer)==market_wallet


def mark_arrived(db,item,now,source,seq=None):
    with sales.atomic(db):
        db.execute("UPDATE stock_intent SET state='arrived' WHERE id=? AND state IN ('paid','accepted')",(item["id"],))
        log(db,now,"wholesale_units_reconciled",item["id"],source=source,seq=seq,qty=item["qty"])
    return {"status":"arrived","source":source,"qty":item["qty"]}


def stock_reconcile(db, market, now):
    with sales.atomic(db):
        # When a process died before arming the wallet, no transfer was
        # possible. The atomic sending transition is the only boundary.
        stale = db.execute("SELECT id FROM stock_intent WHERE state='reserved' AND created<?",(now-150,)).fetchall()
        for row in stale:
            db.execute("UPDATE stock_intent SET state='no_purchase' WHERE id=?",(row["id"],))
            log(db,now,"prepayment_reservation_recovered",row["id"])
        item=sales.one(db,"""SELECT * FROM stock_intent WHERE retry_at<=? AND
                              (state IN ('unknown','paid','accepted') OR state='sending' AND created<?)
                              ORDER BY created LIMIT 1""",now,now-150)
        if not item:
            return {"status":"no_reconciliation_due"}
        db.execute("UPDATE stock_intent SET retry_at=? WHERE id=?",(now+15,item["id"]))
    if item["state"] in ("unknown","sending"):
        tx=find_unknown(market,item)
        if not tx:
            return {"status":"payment_unknown"}
        if not receipt_valid(market,item,tx):
            return {"status":"payment_receipt_pending"}
        with sales.atomic(db):
            db.execute("UPDATE stock_intent SET tx=?,state='paid' WHERE id=? AND state IN ('unknown','sending')",
                       (tx,item["id"]))
            log(db,now,"wholesale_transfer_recovered",item["id"])
            item=sales.one(db,"SELECT * FROM stock_intent WHERE id=?",item["id"])
    if not receipt_valid(market,item,item["tx"]):
        return {"status":"payment_receipt_pending"}
    seq=paid_ledger(market,item)
    if seq:
        return mark_arrived(db,item,now,"own_market_ledger",seq)
    if item["state"]=="accepted":
        observed={u.get("unit") for u in market.snapshot()["units"]
                  if verified_unit(u,item["sku"],item["recipient"])}
        if set(json.loads(item["units"]))<=observed:
            return mark_arrived(db,item,now,"exact_physical_units")
        return {"status":"accepted_awaiting_units"}
    if now-item["created"]>6*HOUR:
        return {"status":"requires_operator_reconciliation"}
    status,body=market.supply({"quote":item["quote"],"tx_hash":item["tx"]})
    if status!=200:
        return {"status":"same_quote_tx_confirm_pending","market_status":status}
    units=body.get("units") if isinstance(body,dict) else None
    if (not isinstance(units,list) or len(units)!=item["qty"] or
            any(not verified_unit(u,item["sku"],item["recipient"]) for u in units)
            or {u.get("unit") for u in units}!=set(json.loads(item["units"]))):
        raise sales.Unavailable("confirmation conflicts with quoted unit IDs")
    with sales.atomic(db):
        db.execute("UPDATE stock_intent SET state='accepted',delivered=? WHERE id=? AND state='paid'",
                   (entries(sorted(u["unit"] for u in units)),item["id"]))
        log(db,now,"market_accepted_awaiting_arrival",item["id"])
    return {"status":"market_accepted_waiting_for_units"}


def run(args, kit):
    db=None
    try:
        market=Market(kit)
        db=ledger(market.wallet)
        now=time.time()
        action=args.get("action")
        if action=="context":
            return stock_context(db,market,now,args.get("line_cap",WINDOW_LINES))
        if action=="plan":
            return stock_plan(db,market,now,args["plan"],args["decision"])
        if action=="execute":
            from eth_utils import to_checksum_address
            return stock_execute(db,market,now,lambda to,wei,marker: kit.pay(to_checksum_address(to),wei,marker,role="shop"))
        if action=="reconcile":
            return stock_reconcile(db,market,now)
        return {"status":"invalid_action"}
    except (sales.Unavailable,sqlite3.Error,httpx.HTTPError,OSError,ValueError,TypeError,KeyError,AttributeError):
        return {"status":"authoritative_check_unavailable"}
    finally:
        if db is not None:
            db.close()

