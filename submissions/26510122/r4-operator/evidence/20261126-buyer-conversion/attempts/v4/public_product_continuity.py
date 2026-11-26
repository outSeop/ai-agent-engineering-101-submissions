"""Bounded public facts for SDK task continuation. No financial authority."""
from collections import OrderedDict
from hashlib import sha256
import re
from threading import Lock
from time import monotonic

from public_catalogue_protocol import sku

TASK = re.compile(r"[A-Za-z0-9_-]{16,128}\Z")


class PublicContinuity:
    def __init__(self, *, ttl=300, limit=300, clock=monotonic):
        self.ttl, self.limit, self.clock = ttl, limit, clock
        self.entries = OrderedDict()
        self.lock = Lock()

    @staticmethod
    def key(task, context):
        if not all(isinstance(value, str) and TASK.fullmatch(value) for value in (task, context)):
            return None
        return sha256((task+":"+context).encode()).digest()

    def current(self, task, context):
        key = self.key(task, context)
        if key is None:
            return None
        with self.lock:
            entry = self.entries.get(key)
            if not entry:
                return None
            until, facts = entry
            if until <= self.clock():
                self.entries.pop(key)
                return None
            return tuple(dict(fact) for fact in facts)

    def remember(self, task, context, facts):
        key = self.key(task, context)
        if key is None or len(facts)>3 or any(not sku(row.get("sku")) or row.get("grade") not in {"A","B","C"}
                or type(row.get("preferred_price")) is not int or row["preferred_price"]<=0 for row in facts):
            return False
        with self.lock:
            self.entries[key]=(self.clock()+self.ttl,tuple({k:row[k] for k in ("sku","grade","preferred_price")} for row in facts))
            self.entries.move_to_end(key)
            while len(self.entries)>self.limit:
                self.entries.popitem(last=False)
        return True


def page_facts(page, selections):
    """Decode only selected public row fields from a protocol-verified page."""
    if not isinstance(page,dict):
        return []
    found = {}
    for values in page["rows"]:
        row = dict(page["common"])
        for name,value in zip(page["columns"],values):
            lookup=page["lookup"].get(name)
            row[name]=lookup[value] if lookup is not None else value
        key=(row.get("sku"),row.get("grade"))
        if key in found:
            return []
        found[key]=row
    rows=[]
    for item in selections:
        row=found.get((item["sku"],item["grade"]))
        if row is None or type(row.get("preferred_price")) is not int:
            return []
        rows.append({k:row[k] for k in ("sku","grade","preferred_price")})
    return rows
