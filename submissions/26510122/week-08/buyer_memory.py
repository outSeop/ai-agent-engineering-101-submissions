"""First-hand buyer outcomes, separated from unsigned receipts and public reviews."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any
import decision_audit
from context_compaction import (BUYER_MEMORY_BYTES, BUYER_BRIEF_BYTES, MAX_TURNS,
                                bounded, price_ranges, select_cases, text)


EVENTS = Path("logs/buyer-events.jsonl")
PAYMENTS = Path(".market/payments.jsonl")
BROKEN = Path(".market/broken.jsonl")


def read_events(path: Path = EVENTS) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    result = []
    with path.open(encoding="utf-8", errors="replace") as source:
        for line in source:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and isinstance(event.get("event"), str):
                result.append(event)
    return result


def record(event: str, *, path: Path = EVENTS, **fields: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "event": event, **decision_audit.enrich(fields)}
    data = (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        if os.write(fd, data) != len(data):
            raise OSError("short buyer event write")
    finally:
        os.close(fd)


def register_shops(shops: list[dict], *, path: Path = EVENTS) -> None:
    """Use registry names as identity; URLs are transport aliases, not identity."""
    seen = {(r.get('shop_name'), r.get('shop')) for r in read_events(path) if r['event']=='shop_identity'}
    for shop in shops:
        if not isinstance(shop,dict):
            continue
        name, url = shop.get('name'), shop.get('url')
        if isinstance(name,str) and name and isinstance(url,str) and url and (name,url) not in seen:
            record('shop_identity',path=path,shop_name=name,shop=url)
            seen.add((name,url))


def resolve_shop_name(shop_url: str, *, order: str | None = None,
                      history: list[dict] | None = None) -> str | None:
    rows = read_events() if history is None else history
    if order:
        names = {e['shop_name'] for e in rows if e.get('order')==order and e.get('shop')==shop_url and e.get('shop_name')}
        if len(names)==1:
            return next(iter(names))
    names = {e['shop_name'] for e in rows if e.get('shop')==shop_url and e.get('shop_name')}
    return next(iter(names)) if len(names)==1 else None


def import_payments(payment_path: Path = PAYMENTS, *, event_path: Path = EVENTS) -> int:
    """Import kit payment evidence once; a negotiated receipt is not a purchase."""
    if not payment_path.exists():
        return 0
    history = read_events(event_path)
    def key(e):
        return tuple(e.get(k) for k in ('order','shop','sku','price','paid','ledger','reason'))
    seen = {key(e) for e in history if e['event']=='payment'}
    count = 0
    with payment_path.open(encoding="utf-8", errors="replace") as source:
        for line in source:
            try:
                payment = json.loads(line)
            except ValueError:
                continue
            if not isinstance(payment, dict) or not payment.get("order"):
                continue
            normalized = {**payment,'sku':payment.get('item'),'paid':payment.get('paid') is True}
            if key(normalized) in seen:
                continue
            linked = decision_audit.buyer_outcome_links(history, order=payment['order'],
                        shop=payment.get('shop'), sku=payment.get('item'), price=payment.get('price'))
            record("payment", path=event_path, order=payment["order"],
                   shop_name=resolve_shop_name(payment.get('shop'),order=payment['order'],history=history),
                   shop=payment.get("shop"), sku=payment.get("item"),
                   price=payment.get("price"), paid=payment.get("paid") is True,
                   ledger=payment.get("ledger"), reason=payment.get("reason"),
                   **{k:v for k,v in linked.items() if k not in ('order','shop','shop_name','sku')},
                   outcome_source='kit_payment')
            seen.add(key(normalized))
            count += 1
    return count


def import_broken(broken_path: Path = BROKEN, *, event_path: Path = EVENTS) -> int:
    """Keep post-sale breakage evidence without guessing which seller caused it."""
    if not broken_path.exists():
        return 0
    seen = {(e.get("name"), e.get("broke_at")) for e in read_events(event_path)
            if e["event"] == "broken"}
    count = 0
    with broken_path.open(encoding="utf-8", errors="replace") as source:
        for line in source:
            try:
                news = json.loads(line)
            except ValueError:
                continue
            if not isinstance(news, dict) or not news.get("name") or not news.get("broke_at"):
                continue
            key = (news["name"], news["broke_at"])
            if key in seen:
                continue
            record("broken", path=event_path, name=news["name"], broke_at=news["broke_at"],
                   outcome_link_status='unmatched',outcome_source='kit_breakage_notice')
            seen.add(key)
            count += 1
    return count


def context(shop_url: str, sku: str, *, shop_name: str | None = None,
            product_name: str | None = None, path: Path = EVENTS,
            history: list[dict] | None = None) -> dict[str, Any]:
    rows = read_events(path) if history is None else history
    alias_names, order_names = {}, {}
    for e in rows:
        if e.get('shop_name') and e.get('shop'):
            alias_names.setdefault(e['shop'],set()).add(e['shop_name'])
            if e.get('order'):
                order_names.setdefault((e['order'],e['shop']),set()).add(e['shop_name'])
    def resolved(url, order=None):
        names = order_names.get((order,url)) or alias_names.get(url,set())
        return next(iter(names)) if len(names)==1 else None
    name = shop_name or resolved(shop_url)
    def belongs(e):
        if e.get('shop_name'):
            return e['shop_name']==name if name else e.get('shop')==shop_url
        identity = resolved(e.get('shop'),e.get('order'))
        return identity==name if name else e.get('shop')==shop_url
    first_hand = [e for e in rows if e['event'] in ('payment','settled','negotiation') and belongs(e)]
    ledger_orders={e['ledger']:e['order'] for e in first_hand if e.get('ledger') is not None and e.get('order')}
    episodes = {}
    for i,e in enumerate(first_hand):
        key = (e.get('order') or ledger_orders.get(e.get('ledger')) or e.get('ledger') or f'legacy-{i}',e.get('sku'))
        episode = episodes.setdefault(key,{'order':e.get('order'),'sku':e.get('sku'),'outcome':'unknown'})
        episode['at'] = e.get('at');episode['_sequence'] = i
        if e['event']=='negotiation':
            offers=e.get('offers') if isinstance(e.get('offers'),list) else []
            episode.update({'offers':offers[-MAX_TURNS:],
                            'offer_count':len(offers), 'reason':text(e.get('reason'))})
            if episode['outcome'] not in ('paid','refused'):
                episode['outcome'] = e.get('result','unknown')
        elif e['event']=='payment':
            episode['payment_seen'] = True
            if e.get('paid') or episode['outcome']!='paid':
                episode.update({'outcome':'paid' if e.get('paid') else 'refused','price':e.get('price'),
                                'ledger':e.get('ledger'),'reason':text(e.get('reason'))})
        elif e['event']=='settled' and e.get('ledger') is not None:
            episode.update({k:e.get(k) for k in ('price','ledger','grade','value','warranty_hours',
                                                'expires_at','hours_left_at_recording')})
            episode['outcome'] = 'paid'
    same = [{k:v for k,v in e.items() if k!='_sequence'} for e in sorted(episodes.values(),key=lambda e:e['_sequence']) if e['sku']==sku]
    outcomes = Counter(e['outcome'] for e in same if e['outcome'] in ('paid','refused'))
    view = {'shop_name':text(name,80),'shop_payment_count':sum(e['outcome'] in ('paid','refused') for e in episodes.values()),
            'same_sku_payment_outcomes':dict(outcomes),
            'settled_prices_by_grade':price_ranges([e for e in same if e['outcome']=='paid']),
            'cases':select_cases(same),
            'observed_receipt_problems':sum(e.get('result')=='invalid_receipt' for e in first_hand if e['event']=='negotiation' and e.get('sku')==sku),
            'same_product_broken_reports':sum(e['event']=='broken' and e.get('name')==product_name for e in rows) if product_name else 0,
            'note':'Only confirmed payment/settlement is paid. Cases are observations, not rules. '
                   'Breakage reports identify a product, not its seller. Unknown grade stays unknown.'}
    return bounded(view,('cases',),BUYER_MEMORY_BYTES)


def brief(memory: dict) -> dict:
    """Give the selector evidence behind a tool score, not just a score."""
    result = {k:memory.get(k) for k in ('shop_name','shop_payment_count','same_sku_payment_outcomes',
                                      'settled_prices_by_grade','observed_receipt_problems','same_product_broken_reports')}
    result['cases'] = memory.get('cases',[])[:2]
    result['note'] = 'First-hand observations; public reviews are separate claims. More history may be omitted.'
    return bounded(result,('cases',),BUYER_BRIEF_BYTES)
