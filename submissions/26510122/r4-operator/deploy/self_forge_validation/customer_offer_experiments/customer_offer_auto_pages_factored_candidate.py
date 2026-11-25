"""Host transport experiment: collect exact native pages without selecting offers."""
import json
import time

from customer_offer_mind_canary import TOOL
from customer_offer_factored_table import table


PUBLIC = ("sku","name","category_path","state","grade","price_credits","expires_at","remaining_seconds")
MAX_OBSERVATION = 5500
MAX_CALLS = 256


class AutoOfferGate:
    tools={TOOL:{}}

    def __init__(self,invoke,clock=time.time):
        self.invoke=invoke
        self.clock=clock
        self.actions=[]
        self.observed=[]
        self.expiry=None

    def listing(self):
        return ("- read_customer_offers: {op:'context', skus?: [SKU], min_remaining_seconds?: int}; "
                "host automatically follows native pages. Table text is abbreviated. "
                "Use {op:'details', skus:[up to 4 SKUs from the same table]} for exact observed text.")

    def forge(self,args):
        return {"error":"disabled"}

    def read(self,name):
        return {"error":"disabled"}

    def call(self,name,args):
        if name!=TOOL or not isinstance(args,dict):
            return {"error":"invalid_arguments"}
        operation=args.get("op")
        if operation=="details" and set(args)=={"op","skus"}:
            return self.details(args["skus"])
        if operation!="context" or not set(args)<={"op","skus","min_remaining_seconds"}:
            return {"error":"invalid_arguments"}
        self.observed=[]
        self.expiry=None
        self.actions.append({"tool":TOOL,"op":"context"})
        try:
            return self.collect(args)
        except (TypeError,KeyError,ValueError,OverflowError):
            return {"error":"offer_pages_unavailable"}

    def details(self, skus):
        if (not isinstance(skus,list) or not 1<=len(skus)<=4 or any(not isinstance(s,str) for s in skus)
            or len(set(skus))!=len(skus) or not self.expiry or self.clock()>=self.expiry
            or not set(skus)<={r["sku"] for r in self.observed}):
            return {"error":"offer_details_unavailable"}
        rows=[row for row in self.observed if row["sku"] in skus]
        if any(row["expires_at"] is not None and row["expires_at"]<=self.clock() for row in rows):
            return {"error":"offer_details_unavailable"}
        result={"items":rows,"facts_are_observed_not_reservations":True}
        if len(json.dumps(result,ensure_ascii=False))>MAX_OBSERVATION:
            return {"error":"full_details_exceed_observation_limit"}
        self.actions.append({"tool":TOOL,"op":"details"})
        return result

    def collect(self, original):
        current=original
        identity=None
        rows=[]
        seen={}
        fragment=None
        for call_index in range(MAX_CALLS):
            self.actions[-1]["native_page_count"]=call_index+1
            envelope=self.invoke(current)
            if not isinstance(envelope,dict) or set(envelope)!={"ok","result"} or envelope["ok"] is not True:
                raise ValueError("invalid native page")
            page=envelope["result"]
            if not isinstance(page,dict) or "error" in page:
                raise ValueError("native rejection")
            key=tuple(page[k] for k in ("snapshot","observed_at","valid_until","total_count"))
            if identity is None:
                identity=key
            elif identity!=key:
                raise ValueError("changed observation")
            if self.clock()>=page["valid_until"] or page["returned_count"]!=len(page["units"]):
                raise ValueError("stale or incomplete page")
            collected=page["units"]
            part=page.get("row_fragment")
            if part is not None:
                if collected:
                    raise ValueError("mixed fragment and rows")
                index, offset, stamp=part["unit_index"],part["offset"],part["as_of"]
                if fragment is None:
                    fragment=(index,stamp,"")
                last_index,last_stamp,previous=fragment
                if (last_index,last_stamp,len(previous))!=(index,stamp,offset):
                    raise ValueError("fragment discontinuity")
                fragment=(index,stamp,previous+part["text"])
                if part["complete"] is True:
                    collected=[json.loads(fragment[2])]
                    fragment=None
            elif fragment is not None:
                raise ValueError("incomplete row fragment")
            for row in collected:
                ref=row["unit_ref"]
                if ref in seen:
                    raise ValueError("duplicate native row")
                seen[ref]=True
                rows.append({**{field:row[field] for field in PUBLIC},"as_of":page["as_of"]})
            next_args=page["next_args"]
            if next_args is None:
                if fragment is not None or len(rows)!=page["total_count"] or len(rows)>200:
                    raise ValueError("native result incomplete")
                result=table(rows,page["observed_at"],page["total_count"])
                if result.get("status")=="ready":
                    self.observed=rows
                    self.expiry=page["valid_until"]
                return result
            if not isinstance(next_args,dict) or next_args.get("snapshot")!=page["snapshot"] or next_args==current:
                raise ValueError("invalid native continuation")
            for key in ("skus","min_remaining_seconds"):
                if (key in original)!=(key in next_args) or original.get(key)!=next_args.get(key):
                    raise ValueError("filters changed")
            current=next_args
        raise ValueError("too many native pages")

