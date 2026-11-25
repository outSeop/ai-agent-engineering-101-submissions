"""Lossless indexes for exact offer facts, with explicit public text previews."""
import json

import customer_offer_auto_pages as base


def indexed_table(rows, observed, total):
    categories=list(dict.fromkeys(
        row["category_path"][0] if isinstance(row["category_path"],list)
        else row["category_path"].split(">",1)[0].strip() for row in rows
    ))
    states=list(dict.fromkeys(row["state"] for row in rows))
    times=list(dict.fromkeys(row["as_of"] for row in rows))
    expiry=list(dict.fromkeys(row["expires_at"] for row in rows))
    remaining=list(dict.fromkeys(row["remaining_seconds"] for row in rows))
    indices=[{value:index for index,value in enumerate(group)} for group in (categories,states,times,expiry,remaining)]
    cat_idx,state_idx,time_idx,expiry_idx,remaining_idx=indices
    for width in (28,22,18,15,12):
        response={"status":"ready","total_count":total,"observed_at":observed,
                  "name_is_preview":True,
                  "lookup":{"c":categories,"s":states,"t":times,"e":expiry,"r":remaining},
                  "columns":["sku","name_preview","c","s","grade","price_credits","e","r","t"],
                  "index_note":"c=category root; s=state; e=expiry; r=remaining seconds; t=as_of. All zero-based into lookup.",
                  "rows":[]}
        for row in rows:
            path=row["category_path"]
            category=path[0] if isinstance(path,list) else path.split(">",1)[0].strip()
            name=row["name"]
            name=name if len(name)<=width else name[:width]+"…"
            response["rows"].append([row["sku"],name,cat_idx[category],state_idx[row["state"]],
                 row["grade"],row["price_credits"],expiry_idx[row["expires_at"]],
                 remaining_idx[row["remaining_seconds"]],time_idx[row["as_of"]]])
        if len(json.dumps(response,ensure_ascii=False))<=base.MAX_OBSERVATION:
            return response
    return {"error":"full_offer_table_exceeds_observation_limit","total_count":total}


class IndexedAutoOfferGate(base.AutoOfferGate):
    def format_table(self, rows, observed, total):
        return indexed_table(rows,observed,total)


