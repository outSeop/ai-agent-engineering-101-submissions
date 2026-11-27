"""Validate the read-only tool boundary without implementing catalogue decisions."""
import json
import re

from public_catalogue_snapshot_host import CatalogueError

SKU=re.compile(r"[FG][0-9a-fA-F]{8}\Z")
SEARCH_KEYS={"q","skus","exclude_skus","category","grade","max_price","min_remaining_seconds",
             "sort","offset","limit","snapshot","as_of","query_id"}
PAGE_KEYS={"status","coverage","observed_at","as_of","valid_until","columns","common","lookup",
           "rows","text_limit","snapshot","query_id","catalogue"}
REPLY_KEYS={"status","reply","observed_at","valid_until"}
TOKEN=re.compile(r"[0-9a-fA-F]{64}\Z")
PUBLIC_COLUMNS={"sku","grade","name","preferred_price","category_path","remaining_seconds",
                "category","stock_status","available","wait_eligible","state"}
CATALOGUE_KEYS={"source_count","eligible_count","matched_count","offset","returned_count","next_args",
                "category_counts","category_counts_partial","criteria","excluded_counts","missing_skus",
                "display_counts","name_preview_limit","coverage","search","hints"}
PAGE_REASONS={"dependency_unavailable","unsupported_request","unsafe_query","snapshot_changed","query_changed","cursor_mismatch","pagination_restart_required",
              "fallback_not_applicable","no_match","invalid_query","stale_snapshot","output_limit",
              "invalid_snapshot","invalid_args","selection_not_available","query_restart_required",
              "selection_ambiguous","selection_unavailable","source_unavailable","unsafe_query_cursor",
              "output_budget","name_unavailable","selection_limit"}


def sku(value):
    return isinstance(value,str) and SKU.fullmatch(value) is not None


class CatalogueProtocol:
    def __init__(self,mask):
        self.mask=mask

    def _public_text(self,value,max_chars):
        return isinstance(value,str) and 0<len(value)<=max_chars and self.mask(value)==value

    def context(self,text,focus_skus=()):
        if not self._public_text(text,1500) or any(not sku(value) for value in focus_skus):
            raise CatalogueError("action_rejected")
        return {"text":text,**({"focus_skus":list(focus_skus)} if focus_skus else {})}

    def search(self,args,prior):
        if not isinstance(args,dict) or set(args)-(SEARCH_KEYS|{"op"}) or args.get("op","search")!="search":
            raise CatalogueError("action_rejected")
        args={key:value for key,value in args.items() if key!="op"}
        cursor_keys={"snapshot","as_of","query_id"}
        bound=bool(cursor_keys & args.keys())
        if bound and not cursor_keys<=args.keys():
            raise CatalogueError("pagination_restart_required")
        for key,value in args.items():
            if key in {"skus","exclude_skus"}:
                ok=isinstance(value,list) and len(value)<=20 and all(map(sku,value))
            elif key=="q":
                ok=value=="" or self._public_text(value,64)
            elif key=="category":
                ok=(bound and value=="") or self._public_text(value,128)
            elif key=="sort":
                ok=value in ("source","price_asc","expiry_asc")
            elif key=="grade":
                ok=isinstance(value,str) and (value in {"A","B","C"} or bound and value=="")
            elif key in {"snapshot","query_id"}:
                ok=isinstance(value,str) and TOKEN.fullmatch(value)
            else:
                maximum={"limit":8,"offset":5000,"as_of":2**53,"max_price":10**12}.get(key,2**53)
                ok=type(value) is int and (1 if key in {"limit","max_price"} else 0)<=value<=maximum
            if not ok:
                raise CatalogueError("action_rejected")
        if bound or args.get("offset",0)>0:
            next_args=self.next_args(prior)
            if next_args is None or args!={key:value for key,value in next_args.items() if key!="op"}:
                raise CatalogueError("pagination_restart_required")
        return dict(args)

    @staticmethod
    def next_args(page):
        if page is None:
            return None
        return page["catalogue"].get("next_args")

    def render(self,args):
        if not isinstance(args,dict) or set(args)!={"items"}:
            raise CatalogueError("action_rejected")
        items=args["items"]
        if not isinstance(items,list) or not 1<=len(items)<=3 or any(
            not isinstance(row,dict) or set(row)!={"sku","grade"} or not sku(row["sku"])
            or row["grade"] not in ("A","B","C") for row in items
        ):
            raise CatalogueError("action_rejected")
        if len({(row["sku"],row["grade"]) for row in items})!=len(items):
            raise CatalogueError("action_rejected")
        return {"items":items}

    def semantic(self,text,args):
        if (not self._public_text(text,1500) or not isinstance(args,dict) or set(args)!={"product_phrase","queries"}):
            raise CatalogueError("action_rejected")
        phrase=args["product_phrase"]
        if not self._public_text(phrase,48) or phrase!=phrase.strip() or text.count(phrase)!=1:
            raise CatalogueError("action_rejected")
        queries=args["queries"]
        if (not isinstance(queries,list) or not 1<=len(queries)<=2
                or any(not self._public_text(q,48) or q!=q.strip() for q in queries)
                or len({q.casefold() for q in queries})!=len(queries)):
            raise CatalogueError("action_rejected")
        return {"text":text,"product_phrase":phrase,"queries":list(queries)}

    def fallback(self,text):
        if not self._public_text(text,1500):
            raise CatalogueError("fallback_denied")
        return {"text":text}

    def page_skus(self,page):
        names=page["columns"]
        if "sku" in page["common"]:
            value=page["common"]["sku"]
            if not sku(value):
                raise CatalogueError("context_failed")
            return {value} if page["rows"] else set()
        if "sku" not in names:
            raise CatalogueError("context_failed")
        index=names.index("sku")
        lookup=page["lookup"].get("sku")
        selected=set()
        for row in page["rows"]:
            value=row[index]
            if lookup is not None:
                if type(value) is not int or not 0<=value<len(lookup):
                    raise CatalogueError("context_failed")
                value=lookup[value]
            if not sku(value):
                raise CatalogueError("context_failed")
            selected.add(value)
        return selected

    def result(self,op,result,observed,valid):
        error=op+"_failed"
        if not isinstance(result,dict):
            raise CatalogueError(error)
        if set(result)=={"status","reason"} and result["status"]=="unavailable":
            why=result["reason"]
            raise CatalogueError(why if isinstance(why,str) and why in PAGE_REASONS else error)
        expected=PAGE_KEYS if op in {"context","search","prepare"} else REPLY_KEYS
        if (set(result)!=expected or type(result["observed_at"]) is not int or type(result["valid_until"]) is not int
                or result["observed_at"]!=observed or result["valid_until"]!=valid):
            raise CatalogueError(error)
        if expected==REPLY_KEYS:
            if result["status"]!="rendered" or not self._public_text(result["reply"],450):
                raise CatalogueError(error)
            return result
        self._check_page(result,op,observed,valid)
        if op=="prepare":
            self._check_preparation(result)
        return result

    @staticmethod
    def _check_preparation(page):
        def read(row,name):
            if name in page["common"]:
                return page["common"][name]
            value=row[page["columns"].index(name)]
            values=page["lookup"].get(name)
            if values is None:
                return value
            if type(value) is not int or not 0<=value<len(values):
                raise ValueError("invalid prepared lookup index")
            return values[value]
        try:
            hints=page["catalogue"]["hints"]["preparation"]
            if set(hints)!={"fits","requested_sku_missing","constraints_unverified"}:
                raise ValueError("invalid preparation fields")
            if any(type(hints[k]) is not bool for k in ("requested_sku_missing","constraints_unverified")):
                raise ValueError("invalid preparation flags")
            fits=hints["fits"]
            pairs=[(read(row,"sku"),read(row,"grade")) for row in page["rows"]]
            if not isinstance(fits,list) or len(fits)!=len(pairs):
                raise ValueError("preparation and page counts differ")
            observed=[]
            for item in fits:
                if (set(item)!={"sku","grade","kind"} or not sku(item["sku"])
                    or item["grade"] not in {"A","B","C"}
                    or item["kind"] not in {"exact_sku","named_pack","category_alternative","related_literal"}):
                    raise ValueError("invalid preparation evidence")
                observed.append((item["sku"],item["grade"]))
            if len(set(observed))!=len(fits) or set(observed)!=set(pairs):
                raise ValueError("preparation keys do not match page")
        except (KeyError,TypeError,AttributeError,ValueError) as exc:
            raise CatalogueError("prepare_failed") from exc

    def _check_page(self,page,op,observed,valid):
        error=op+"_failed"
        cols,common,lookup,rows,meta=(page[k] for k in ("columns","common","lookup","rows","catalogue"))
        if (page["status"]!="ready" or type(page["as_of"]) is not int or not observed<=page["as_of"]<valid
            or not all(isinstance(page[key],str) and TOKEN.fullmatch(page[key]) for key in ("snapshot","query_id"))
            or not isinstance(cols,list) or not all(isinstance(name,str) for name in cols) or len(cols)!=len(set(cols))
            or not isinstance(common,dict) or set(common)&set(cols) or not (set(common)|set(cols))<=PUBLIC_COLUMNS
            or not isinstance(lookup,dict) or not set(lookup)<=set(cols)
            or not all(isinstance(values,list) for values in lookup.values())
            or not isinstance(rows,list) or len(rows)>8 or
            any(not isinstance(row,list) or len(row)!=len(cols) for row in rows)
            or not isinstance(meta,dict) or set(meta)-CATALOGUE_KEYS or any(type(meta.get(key)) is not int for key in
                                                ("source_count","matched_count","offset","returned_count"))
            or not 0<=meta["matched_count"]<=meta["source_count"]<=5000
            or meta["returned_count"]!=len(rows) or not 0<=meta["offset"]<=5000
            or meta["offset"]+len(rows)>meta["matched_count"]):
            raise CatalogueError(error)
        cursor=meta.get("next_args")
        if cursor is not None:
            if (not isinstance(cursor,dict) or set(cursor)-(SEARCH_KEYS|{"op"}) or cursor.get("op","search")!="search" or
                cursor.get("snapshot")!=page["snapshot"] or cursor.get("as_of")!=page["as_of"] or
                cursor.get("query_id")!=page["query_id"] or cursor.get("offset")!=meta["offset"]+len(rows)
                or not rows):
                raise CatalogueError("pagination_restart_required")
        self.page_skus(page)
        packed=json.dumps(page,ensure_ascii=False,separators=(",",":"),allow_nan=False)
        if len(packed)>5500:
            raise CatalogueError("output_limit")

