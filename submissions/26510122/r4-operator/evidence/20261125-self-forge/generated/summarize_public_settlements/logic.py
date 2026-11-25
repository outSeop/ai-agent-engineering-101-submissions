import math
import time
from collections import Counter

import httpx

MARKET = 'https://market.ourolabs.ai'


def _get(client, path, params=None):
    response = client.get(MARKET + path, params=params)
    response.raise_for_status()
    return response.json()


def _ledger(client, after):
    payload = _get(client, '/api/ledger', {'after': after})
    if not isinstance(payload, list):
        raise ValueError('ledger must be an array')
    rows = []
    previous = -1
    for entry in payload:
        seq, ts = entry['seq'], entry['ts']
        if type(seq) is not int or seq <= previous:
            raise ValueError('invalid ledger sequence')
        if type(ts) not in (int, float) or not math.isfinite(ts):
            raise ValueError('invalid ledger timestamp')
        data = entry.get('data')
        data = data if isinstance(data, dict) else {}
        sealed = 'sealed' in data
        sku = data.get('sku') if not sealed else None
        sku = sku if isinstance(sku, str) else None
        is_settlement = entry.get('kind') == 'settle' and entry.get('round') == 4
        rows.append((seq, ts, is_settlement, sealed, sku if is_settlement else None))
        previous = seq
    return rows


def _catalog(client):
    payload = _get(client, '/api/catalog')
    if isinstance(payload, dict):
        for key in ('catalog', 'items'):
            if key in payload:
                payload = payload[key]
                break
    if isinstance(payload, list):
        entries = [(None, item) for item in payload]
    elif isinstance(payload, dict):
        entries = payload.items()
    else:
        raise ValueError('invalid catalog format')
    products = {}
    for key, item in entries:
        if not isinstance(item, dict):
            continue
        sku = item.get('sku', key)
        name, category = item.get('name'), item.get('category')
        if all(isinstance(value, str) and value.strip() for value in (sku, name, category)):
            if sku in products and products[sku] != (name, category):
                raise ValueError('conflicting catalog entries')
            products[sku] = (name, category)
    if payload and not products:
        raise ValueError('catalog has no recognized products')
    return products


def _sample(client):
    head = _ledger(client, -1)
    if len(head) > 1:
        raise ValueError('unexpected ledger tail response')
    if not head:
        return [], None
    last_seq = head[0][0]
    rows = [row for row in _ledger(client, -2000) if row[0] <= last_seq]
    for _ in range(3):
        if not rows or rows[-1][0] == last_seq:
            break
        cursor = rows[-1][0]
        page = [row for row in _ledger(client, cursor) if cursor < row[0] <= last_seq]
        if not page:
            break
        rows.extend(page)
    return rows, last_seq


def run(args, kit):
    window = args.get('window_seconds', 3600)
    if type(window) is not int or not 60 <= window <= 86400:
        return {'error': 'invalid_window_seconds'}
    end = int(time.time())
    start = end - window
    try:
        with httpx.Client(timeout=10.0, follow_redirects=False, trust_env=False) as client:
            rows, last_seq = _sample(client)
            sales = [row for row in rows if row[2] and start <= row[1] <= end]
            counts = Counter(row[4] for row in sales if not row[3])
            products = _catalog(client) if any(sku is not None for sku in counts) else {}
    except httpx.HTTPStatusError as error:
        return {'error': 'public_http_error', 'status': error.response.status_code}
    except httpx.RequestError:
        return {'error': 'public_request_failed'}
    except (ValueError, TypeError, KeyError, OverflowError):
        return {'error': 'invalid_public_data'}

    timestamps = [row[1] for row in rows]
    # The window includes start, so earlier pages could contain rows at start.
    boundaries_observed = bool(rows) and rows[0][1] < start and rows[-1][0] == last_seq
    boundaries_observed = boundaries_observed and all(
        b[0] == a[0] + 1 and b[1] >= a[1] for a, b in zip(rows, rows[1:])
    )
    by_sku = []
    categories = Counter()
    for sku, count in counts.items():
        if sku not in products:
            continue
        name, category = products[sku]
        by_sku.append({'sku': sku, 'name': name, 'category': category, 'count': count})
        categories[category] += count
    return {
        'mode': 'synthetic_test' if kit.testing else 'public_market_sample',
        'requested_time': {'start': start, 'end': end},
        'sample_time': {'start': min(timestamps), 'end': max(timestamps)} if rows else None,
        'coverage': 'boundaries_observed' if boundaries_observed else 'partial',
        'by_sku': sorted(by_sku, key=lambda item: (-item['count'], item['sku'])),
        'by_category': dict(sorted(categories.items(), key=lambda item: (-item[1], item[0]))),
        'sealed_count': sum(row[3] for row in sales),
        'unclassified_count': sum(count for sku, count in counts.items() if sku not in products),
    }
