"""HOST response wiring for verified terminal public tool metadata.

All business interpretation remains in the classroom-forged tool and pinned
broker. This adapter transports non-issuance and public hint metadata to the
customer, task state and the exact customer_received trace together.
"""
from copy import deepcopy
from public_catalogue_protocol import load_base_host
_base=load_base_host('_verified_catalogue_base_broker','broker_public_catalogue_host_candidate.py')
SEMANTIC_INSTRUCTION=_base.SEMANTIC_INSTRUCTION

def __getattr__(name):return getattr(_base,name)

class CatalogueView:
    def __init__(self,original):self.original=original;self.terminal=None
    def __getattr__(self,name):return getattr(self.original,name)
    def semantic(self,*args,**kwargs):
        result=self.original.semantic(*args,**kwargs)
        if isinstance(result,dict) and result.get('status')=='rendered':self.terminal=deepcopy(result)
        return result

class Delivery:
    def __init__(self,view,remember):self.view=view;self.remember=remember;self.memory_saved=False;self.memory_attempted=False
    def apply(self,answer):
        terminal=self.view.terminal if self.view else None
        # Do not attach a successful tool's metadata to an unrelated error reply.
        if not terminal or not isinstance(answer,dict) or answer.get('reply')!=terminal.get('reply'):return answer
        out=deepcopy(answer)
        if 'payment_request' in terminal:
            data=out.get('data') if isinstance(out.get('data'),dict) else {}
            out['data']={**data,'payment_request':deepcopy(terminal['payment_request'])}
            out['state']='input_required'
        facts=terminal.get('public_facts')
        if facts and self.remember is not None and not self.memory_attempted:
            self.memory_attempted=True
            self.memory_saved=bool(self.remember(facts))
        if self.memory_saved:out['state']='input_required'
        return out

class TraceView:
    def __init__(self,original,delivery):self.original=original;self.delivery=delivery
    def add(self,ref,role,payload,review=None):
        if role=='customer_received':payload=self.delivery.apply(payload)
        return self.original.add(ref,role,payload,review)

class Broker(_base.Broker):
    def __init__(self,*args,**kwargs):
        _base.SEMANTIC_INSTRUCTION=SEMANTIC_INSTRUCTION
        super().__init__(*args,**kwargs)
    def handle(self,text,*,transport_id=None,claimed_from=None,remembered=None,remember=None):
        original_catalogue=self.catalogue;original_trace=self.trace
        view=CatalogueView(original_catalogue) if original_catalogue is not None else None
        delivery=Delivery(view,remember)
        self.catalogue=view
        if original_trace is not None:self.trace=TraceView(original_trace,delivery)
        try:
            answer=super().handle(text,transport_id=transport_id,claimed_from=claimed_from,
                                  remembered=remembered,remember=remember)
            return delivery.apply(answer)
        finally:
            self.catalogue=original_catalogue;self.trace=original_trace
