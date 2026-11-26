"""Bind byte-original public observations and operation results to one request."""
from copy import deepcopy
from hashlib import sha256
import json
from time import time

from public_catalogue_snapshot_host import CatalogueError


class ScopedPublicCatalogue:
    def __init__(self, supplier, invoke, protocol, instruction, *, clock=time, stock_state_supplier=None):
        self.supplier=supplier
        self.invoke=invoke
        self.protocol=protocol
        self.instruction=instruction
        self.clock=clock
        self.stock_state_supplier=stock_state_supplier
        self.stock_state=None
        self.prepared=stock_state_supplier is not None
        self._source=None
        self.page=None

    def open(self, text, focus_skus, remaining_seconds):
        if self._source is not None:
            raise CatalogueError("action_rejected")
        raw, document=self.supplier()
        self._source=(raw,document["observed_at"],document["valid_until"])
        op="prepare" if self.prepared else "context"
        self.page=self._run(op,self.protocol.context(text,focus_skus),remaining_seconds)
        if self.prepared:
            try:
                self.stock_state=self.stock_state_supplier(raw,document)
            except CatalogueError:
                self.stock_state=None
        return deepcopy(self.page)

    def search(self, args, remaining_seconds):
        original=self.page
        # Trust only the cursor/filters carried on a host-verified page.
        outgoing=self.protocol.search(args,deepcopy(original))
        candidate=self._run("search",outgoing,remaining_seconds)
        if outgoing.get("offset",0)>0 and (
            any(candidate[key]!=original[key] for key in ("snapshot","as_of","query_id"))
            or candidate["catalogue"]["offset"]!=outgoing["offset"]
        ):
            raise CatalogueError("pagination_restart_required")
        self.page=candidate
        return deepcopy(candidate)

    def render(self, args, remaining_seconds):
        return self._run("render",self.protocol.render(args),remaining_seconds)

    def semantic(self, text, args, remaining_seconds):
        if not self.prepared:
            raise CatalogueError("action_rejected")
        return self._run("semantic_candidates",self.protocol.semantic(text,args),remaining_seconds)

    def fallback(self, text, remaining_seconds):
        return self._run("prepared_fallback" if self.prepared else "fallback",self.protocol.fallback(text),remaining_seconds)

    def _run(self, op, outgoing, remaining_seconds):
        if self._source is None:
            raise CatalogueError("cache_missing")
        raw,observed,valid=self._source
        if not observed<=self.clock()<valid:
            raise CatalogueError("cache_stale")
        deadline=min(5,remaining_seconds,valid-self.clock())
        if deadline<=0:
            raise CatalogueError("flow_deadline")
        code=op+"_failed"
        try:
            result=self.invoke(args={**outgoing,"op":op},snapshot=raw,timeout=deadline)
            if not observed<=self.clock()<valid:
                raise CatalogueError("cache_stale")
            checked=self.protocol.result(op,result,observed,valid)
            if op in {"context","search","prepare"} and checked.get("snapshot")!=sha256(raw).hexdigest():
                raise CatalogueError("snapshot_changed")
        except CatalogueError:
            raise
        except Exception as exc:
            raise CatalogueError(code) from exc
        return checked


def context_for_model(legacy, page, public_skus, protected_skus=()):
    """Only the copy passed to the model loses off-page inventory rows."""
    view=deepcopy(legacy)
    rows=view.get("inventory")
    if isinstance(rows,list):
        selected={sku.upper() for sku in {*public_skus,*protected_skus}}
        view["inventory"]=[row for row in rows if isinstance(row,dict)
                           and (isinstance(row.get("sku"),str) and row["sku"].upper() in selected
                                or row.get("stock_status") in ("reserved_pending","reconciling"))]
    view["public_catalogue"]=deepcopy(page)
    if len(json.dumps(view["public_catalogue"],ensure_ascii=False,separators=(",",":"),allow_nan=False))>6000:
        raise CatalogueError("context_failed")
    return view

