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


def page_facts(pages, selections):
    """Decode selected facts from a bounded collection of verified pages."""
    if not pages or len(pages)>6:
        return []
    snapshot = pages[0]["snapshot"]
    selected = {(item["sku"],item["grade"]) for item in selections}
    found = {}
    for page in pages:
        if page["snapshot"]!=snapshot or len(page["rows"])>8:
            return []
        seen = set()
        for values in page["rows"]:
            row = dict(page["common"])
            for name,value in zip(page["columns"],values):
                lookup=page["lookup"].get(name)
                row[name]=lookup[value] if lookup is not None else value
            key=(row.get("sku"),row.get("grade"))
            if key not in selected:
                continue
            price=row.get("preferred_price")
            if key in seen or type(price) is not int or price<=0:
                return []
            if key in found and found[key]["preferred_price"]!=price:
                return []
            seen.add(key)
            found[key]={name:row[name] for name in ("sku","grade","preferred_price")}
    if found.keys()!=selected:
        return []
    return [found[item["sku"],item["grade"]] for item in selections]
