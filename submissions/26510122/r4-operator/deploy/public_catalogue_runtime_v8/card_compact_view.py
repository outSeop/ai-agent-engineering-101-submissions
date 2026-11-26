"""Bounded observation formatting. Preserves every candidate and its input order."""
import json


def compact_card_candidates(rows, limit=5500):
    for width in (64,52,40,32,24,16,12,8,4,1):
        def compact(text):
            return text if len(text)<=width else text[:width-1]+"…"
        result = {
            "status":"ready",
            "columns":["sku","name_preview","category_preview","grade","price_credits"],
            "name_and_category_may_be_abbreviated":True,
            "candidates":[[row["sku"],compact(row["name"]),compact(">".join(row["category_path"])),
                           row["grade"],row["price_credits"]] for row in rows],
        }
        # Official Mind serializes with default separators before clipping.
        if len(json.dumps(result,ensure_ascii=False))<=limit:
            return result
    return {"status":"full_comparison_exceeds_observation_limit"}

