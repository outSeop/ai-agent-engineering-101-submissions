"""Select explicitly requested public inventory rows for the model's copy only."""
from copy import deepcopy
import re

EXPLICIT_SKU = re.compile(r"(?<![A-Za-z0-9])[FG][A-Fa-f0-9]{8}(?![A-Za-z0-9])")


def project_catalogue_for_model(*, customer_text, context):
    requested = set(EXPLICIT_SKU.findall(customer_text))
    if not requested:
        return context
    projected = deepcopy(context)
    legacy = projected.get("inventory")
    if isinstance(legacy, list) and all(isinstance(row, dict) and isinstance(row.get("sku"), str) for row in legacy):
        projected["inventory"] = [row for row in legacy if row["sku"] in requested]
        projected["inventory_scope"] = {
            "mode": "explicit_skus_only",
            "requested_skus": sorted(requested),
            "legacy_source_row_count": len(legacy),
            "legacy_visible_row_count": len(projected["inventory"]),
        }

    native = projected.get("native_customer_context")
    if not isinstance(native, dict) or native.get("status") != "ready":
        return projected
    columns, common, lookup, rows = (native.get(key) for key in ("columns", "common", "lookup", "rows"))
    if not isinstance(columns, list) or not isinstance(common, dict) or not isinstance(lookup, dict) or not isinstance(rows, list):
        return projected
    if "sku" in common and "sku" not in columns and isinstance(common["sku"], str):
        selected = rows if common["sku"] in requested else []
    elif columns.count("sku") == 1 and "sku" not in common:
        sku_index = columns.index("sku")
        sku_lookup = lookup.get("sku")
        if "sku" in lookup and (not isinstance(sku_lookup, list) or any(not isinstance(sku, str) for sku in sku_lookup)):
            return projected
        selected = []
        for row in rows:
            if not isinstance(row, list) or len(row) != len(columns):
                return projected
            sku = row[sku_index]
            if sku_lookup is not None:
                if type(sku) is not int or not 0 <= sku < len(sku_lookup):
                    return projected
                sku = sku_lookup[sku]
            elif not isinstance(sku, str):
                return projected
            if sku in requested:
                selected.append(row)
    else:
        return projected
    projected["native_customer_context"] = dict(native, rows=selected)
    projected["inventory_scope"] = {
        **projected.get("inventory_scope", {}),
        "mode": "explicit_skus_only",
        "requested_skus": sorted(requested),
        "native_source_row_count": len(rows),
        "native_source_coverage": native.get("coverage"),
        "native_visible_row_count": len(selected),
    }
    return projected

