"""Compact buyer-authored constraints and conservative numeric offer parsing.

Only explicit numeric terms become hard constraints. Original wording and the
last few nonnumeric messages also accompany every model turn. Ambiguous text
does not silently become a price or erase an earlier requirement.
"""
from __future__ import annotations

import math
import re


def initial(message):
    return update({'original_request': message[:1000], 'condition_messages': [],
                   'min_hours_left': 0., 'grades': None, 'warranty_hours': 0., 'cert_required': False}, message)


def update(previous, message):
    view = {**previous, 'condition_messages': list(previous.get('condition_messages', []))}
    if re.fullmatch(r'\s*\d[\d,]*\s*', message):
        return view
    view['condition_messages'] = (view['condition_messages'] + [message[:500]])[-3:]
    lower = message.lower()
    # Bind numbers to their meaning, instead of interpreting any number in a
    # mixed price/expiry message as a purchase offer.
    hour_patterns = [
        r'(?:must last|needs? to last|lasts?(?: at least)?|at least|minimum|min_hours_left|needs?|use within)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h\b)',
        r'(\d+(?:\.\d+)?)\s*시간\s*이상',
        r'(?:유통기한|남은\s*기한)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*시간',
    ]
    hours = []
    for pattern in hour_patterns:
        for match in re.finditer(pattern, lower):
            # A six-hour warranty is not a six-hour food lifetime.
            nearby = lower[max(0, match.start()-12):match.end()+12]
            if 'warranty' not in nearby and '보증' not in nearby:
                hours.append((match.start(), float(match.group(1))))
    if hours:
        view['min_hours_left'] = max(hours)[1]
    if re.search(r'no (?:minimum )?(?:shelf.life|expiry) (?:requirement|limit)|유통기한\s*제한\s*없', lower):
        view['min_hours_left'] = 0.
    warranty = list(re.finditer(r'(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h\b|시간)\s*(?:of\s*)?(?:warranty|보증)', lower))
    warranty += list(re.finditer(r'(?:warranty(?:_hours)?|보증)\s*(?:of|for|[:=])?\s*(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h\b|시간)?', lower))
    if warranty:
        view['warranty_hours'] = float(max(warranty, key=lambda m: m.start()).group(1))
    if re.search(r'no warranty (?:needed|required)|보증\s*(?:필요\s*없|불필요)', lower):
        view['warranty_hours'] = 0.
    grade = re.search(r'\bgrades?\s*[:=]?\s*([abc](?:\s*(?:or|and|/|,)\s*[abc])*)\b', lower)
    if not grade:
        grade = re.search(r'([ABC](?:\s*[/,]\s*[ABC])*)\s*등급', message)
    if grade:
        view['grades'] = sorted(set(re.findall(r'[ABC]', grade.group(1).upper())))
        if re.search(r'(?:not|no)\s+grades?\s*[:=]?\s*[abc]', lower):
            view['grades'] = sorted(set('ABC') - set(view['grades']))
    if re.search(r'any grade|등급\s*무관', lower):
        view['grades'] = None
    if re.search(r'(?:require|need|must have)\s+(?:a\s+)?cert|cert\s*[:=]\s*true|인증서\s*(?:필수|필요)', lower):
        view['cert_required'] = True
    return view


def offer(message):
    for token in re.findall(r'\d[\d,]*', message):
        if re.search(r',\d', token) and not re.fullmatch(r'\d{1,3}(?:,\d{3})+', token.rstrip(',')):
            return None
    numeric = re.fullmatch(r'\s*(\d{1,3}(?:,\d{3})+|\d+)\s*', message)
    if numeric:
        return int(numeric.group(1).replace(',', ''))
    patterns = [r'^\s*(\d{1,3}(?:,\d{3})+|\d+)(?=\s|[,;]|원|$)',
                r'\b(?:offer|pay|price)\s*(?:is|of|[:=])?\s*[$₩]?\s*(\d[\d,]*)',
                r'(?:가격|제안가)\s*[:=]?\s*(\d[\d,]*)', r'(\d[\d,]*)\s*원']
    found = []
    for pattern in patterns:
        for match in re.finditer(pattern, message, re.IGNORECASE):
            suffix = message[match.end():].lstrip().lower()
            if re.match(r'(?:hours?|hrs?|h\b|시간)', suffix):
                continue
            token = match.group(1).rstrip(',')
            if re.fullmatch(r'\d+|\d{1,3}(?:,\d{3})+', token):
                found.append(int(token.replace(',', '')))
    return found[0] if found and len(set(found)) == 1 else None


def violations(unit, requirements, now, *, warranty_hours=0):
    errors = []
    expires = unit.get('expires_at')
    if unit.get('kind') == 'food':
        remaining = (expires-now)/3600 if type(expires) in (int, float) and math.isfinite(expires) else None
        if remaining is None or remaining <= 0:
            errors.append('food expiry is unknown or passed')
        elif remaining < requirements.get('min_hours_left', 0):
            errors.append(f"needs {requirements['min_hours_left']:g}h; unit has {remaining:.2f}h left")
    if requirements.get('grades') and unit.get('grade') not in requirements['grades']:
        errors.append('unit does not meet the requested grade')
    if requirements.get('cert_required') and unit.get('cert') is False:
        errors.append('required certificate is unavailable')
    if requirements.get('warranty_hours', 0) > warranty_hours:
        errors.append('requested warranty is not offered')
    return errors
