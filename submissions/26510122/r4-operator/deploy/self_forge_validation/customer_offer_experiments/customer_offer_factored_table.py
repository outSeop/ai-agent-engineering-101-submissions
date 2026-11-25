"""Compact lossless public offer encoding. Only text previews may shorten."""
import json

MAX_OBSERVATION=5500
FIELDS=("sku","name_preview","category_root","state","grade","price_credits","expires_at","remaining_seconds","as_of")
INDEXED={"category_root","state","expires_at","remaining_seconds","as_of"}


def table(rows, observed, total):
    if len(rows)!=total:
        return {"error":"full_offer_table_exceeds_observation_limit","total_count":total}
    full=[]
    for row in rows:
        path=row["category_path"]
        root=path[0] if isinstance(path,list) else path.split(">",1)[0].strip()
        full.append({**row,"category_root":root})
    constants={}
    values={}
    for key in FIELDS[2:]:
        ordered=list(dict.fromkeys(row[key] for row in full))
        if len(ordered)==1:
            constants[key]=ordered[0]
        elif key in INDEXED and ordered:
            values[key]=ordered
    columns=[key for key in FIELDS if key not in constants]
    lookup={key:{value:index for index,value in enumerate(group)} for key,group in values.items()}
    for width in (28,22,18,15,12):
        encoded=[]
        for row in full:
            name=row["name"]
            name=name if len(name)<=width else name[:width]+"…"
            encoded.append([name if key=="name_preview" else lookup[key][row[key]] if key in lookup else row[key]
                            for key in columns])
        result={"status":"ready","total_count":total,"observed_at":observed,
                "name_is_preview":True,"columns":columns,"constant_columns":constants,"lookup":values,
                "index_note":"Constant columns apply to every row; lookup columns use zero-based indices.","rows":encoded}
        if len(json.dumps(result,ensure_ascii=False))<=MAX_OBSERVATION:
            return result
    return {"error":"full_offer_table_exceeds_observation_limit","total_count":total}

