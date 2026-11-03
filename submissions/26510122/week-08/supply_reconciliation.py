"""Reconcile acquisition intents from physical-unit evidence, never from price guesses."""
from inventory_observation import timestamp


def pending_quantity(intent):
    if intent.get('status') != 'issued_unknown':
        return 0
    return max(0, intent.get('qty', 1)-len(set(intent.get('observed_units', []))))


def reconcile(intents, inventory, history, now):
    changes = []
    evidence = []
    for unit in inventory.get('units', []):
        if unit.get('unit') and unit.get('sku'):
            evidence.append({'unit': unit['unit'], 'sku': unit['sku'], 'at': now, 'source': 'inventory'})
    for event in history:
        at = timestamp(event.get('at'))
        kind = event.get('event')
        if (kind not in ('receipt_signed', 'settled') or at is None or at > now
                or not event.get('unit') or not event.get('sku')):
            continue
        if kind == 'settled' and event.get('ledger') is None:
            continue
        evidence.append({'unit': event['unit'], 'sku': event['sku'], 'at': at,
                         'source': kind, 'ledger': event.get('ledger')})
    # Evidence for an already identified unit belongs to that original intent.
    owners = {unit: i for i, intent in enumerate(intents) for unit in intent.get('observed_units', [])}
    for proof in evidence:
        candidates = [i for i, intent in enumerate(intents)
                      if intent['sku'] == proof['sku'] and intent['at'] <= proof['at']
                      and proof['unit'] not in intent.get('prior_units', [])
                      and (pending_quantity(intent) or proof['unit'] in intent.get('observed_units', []))]
        if proof['unit'] in owners:
            candidates = [owners[proof['unit']]] if owners[proof['unit']] in candidates else []
        if len(candidates) != 1:
            continue  # ambiguous repeated same-SKU acquisitions need stronger evidence
        index = candidates[0]
        intent = intents[index]
        old = intent['status']
        units = set(intent.get('observed_units', [])) | {proof['unit']}
        intent['observed_units'] = sorted(units)
        owners[proof['unit']] = index
        if proof['source'] == 'settled':
            intent['settled_units'] = sorted(set(intent.get('settled_units', [])) | {proof['unit']})
            intent['settled_ledgers'] = sorted(set(intent.get('settled_ledgers', [])) | {proof['ledger']})
        if len(intent.get('settled_units', [])) >= intent.get('qty', 1):
            intent['status'] = 'settled'
        elif len(units) >= intent.get('qty', 1) and old != 'settled':
            intent['status'] = 'observed_inventory'
        if old != intent['status']:
            changes.append({'sku': intent['sku'], 'unit': proof['unit'], 'old_status': old,
                            'status': intent['status'], 'source': proof['source'], 'ledger': proof.get('ledger')})
    return changes
