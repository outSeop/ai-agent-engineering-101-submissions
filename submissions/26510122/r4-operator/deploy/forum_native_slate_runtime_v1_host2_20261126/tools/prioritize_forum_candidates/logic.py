import json
import math
import re
import time
import unicodedata
from collections import deque
from pathlib import Path

SOURCE = Path('host_inputs/forum_candidates.json')
SCHEMA = 'outseop-r4.forum-candidates.v1'
ROOT_KEYS = {'schema', 'observed_at', 'valid_until', 'spotlight_allowed', 'items', 'reply_options'}
ITEM_KEYS = {'sku', 'grade', 'name', 'price', 'category', 'expiry', 'certificate', 'spotlight_eligible'}
REPLY_KEYS = {'thread', 'request', 'eligible'}
PAIR_KEYS = {'sku', 'grade'}
GRADES = ('A', 'B', 'C')
SKU = re.compile(r'[FG][0-9a-fA-F]{8}')
PACK = re.compile(r'(?<![0-9A-Za-z])([1-9][0-9]{0,8})\s*(?:개\s*입|개\s*(?:구성|세트)|팩\s*구성)(?![가-힣0-9A-Za-z])')
PACK_JOIN = re.compile(r'[0-9]\s*(?:[.,~∼〜/／+×xX*–—-]|또는|내지|에서)\s*[0-9]')
PACK_EXTRA = re.compile(r'(?<![0-9A-Za-z])[0-9]+\s*(?:개\s*입|개\s*(?:구성|세트)|팩\s*구성|개|팩|입)(?![가-힣0-9A-Za-z])')
GRADE_MENTION = re.compile(r'(?<![A-Za-z0-9])([ABC])\s*(?:등급|급)|(?<![A-Za-z0-9])([ABC])(?![A-Za-z0-9가-힣])', re.IGNORECASE)
PARTICLE = r'^\s*(?:(?:으로는|으로|은|는|을|를|이|가)\s*)?'
BOUNDARY = r'(?=$|[\s,.!?;:，。])'
NEGATIVE = re.compile(PARTICLE + r'(?:말고|제외(?:하고|해\s*주세요|해주세요|해|합니다|할게요|할래요)?|빼고|빼\s*주세요|빼주세요|아닌|아니고|싫어요|안\s*(?:돼요|됩니다|원해요))' + BOUNDARY)
POSITIVE = re.compile(PARTICLE + r'(?:만(?:\s*(?:주세요|원해요|가능해요|가능합니다|찾아요|구해요))?|주세요|원해요|부탁(?:해요|합니다|드려요)?|선호(?:해요|합니다)?|찾아요|구해요|가능(?:해요|합니다)?)' + BOUNDARY)
CHOICE_JOIN = re.compile(r'\s*(?:이나|나|또는|혹은|및|과|와|,|/)\s*')
END_MARKS = re.compile(r'[\s.!?,。！？]*')
UNRESOLVED = re.compile(r'제외|말고|빼(?:고|면|야|는|주|\s*주)|아니|아닌|싫|(?:^|\s)안(?=\s|해|하|돼|됩|사|원)|못\s*(?:해|하)|(?:상관|제한)\s*없|이상|이하|미만|초과|아무\s*등급|다른\s*등급|않|하지만|그런데|다만|라면|으면|러면|경우|대신|(?:도|은|는)\s*가능|(?:은|는)\s*괜찮|혹시')


def unavailable(reason):
    return {'status': 'unavailable', 'reason': reason}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate key')
        result[key] = value
    return result


def exact_keys(value, keys):
    return type(value) is dict and value.keys() == keys


def public_text(value, limit=None, multiline=False):
    if type(value) is not str or not value.strip():
        return False
    if limit is not None and len(value) > limit:
        return False
    whitespace = '\t\r\n' if multiline else ''
    return all(ch in whitespace or unicodedata.category(ch) not in {'Cc', 'Cs'} for ch in value)


def valid_pair(value):
    return (type(value['sku']) is str and SKU.fullmatch(value['sku']) is not None
            and value['grade'] in GRADES)


def pair_key(value):
    return value['sku'], value['grade']


def valid_item(value):
    if not exact_keys(value, ITEM_KEYS) or not valid_pair(value):
        return False
    expiry = value['expiry']
    expiry_ok = (expiry is None or type(expiry) is int
                 or (type(expiry) is float and math.isfinite(expiry)))
    return (public_text(value['name']) and public_text(value['category'])
            and type(value['price']) is int and value['price'] > 0
            and expiry_ok and type(value['certificate']) is bool
            and type(value['spotlight_eligible']) is bool)


def pack_fields(name):
    label = unicodedata.normalize('NFKC', name)
    matches = list(PACK.finditer(label))
    if len(matches) != 1 or PACK_JOIN.search(label):
        return 'unknown', None
    match = matches[0]
    before = label[:match.start()].rstrip()
    after = label[match.end():].lstrip()
    if (PACK_EXTRA.search(before) or PACK_EXTRA.search(after)
            or re.search(r'(?:이상|이하|미만|초과|내외|부터|까지|또는|혹은|선택|랜덤|별도|옵션)', before + ' ' + after)
            or re.search(r'[~/∼〜+×*–—-]\s*$', before)
            or re.match(r'^[~/∼〜+×*–—-](?:\s*[0-9]|\s*$)', after)
            or re.match(r'^(?:씩|당|용|분량|해당|기준|별|가능)', after)):
        return 'unknown', None
    count = int(match.group(1))
    return ('explicit_small' if count <= 3 else 'explicit_multi'), count


def grade_filter(request):
    text = unicodedata.normalize('NFKC', request)
    mentions = list(GRADE_MENTION.finditer(text))
    if not mentions:
        return set(GRADES)
    allowed = set()
    denied = set()
    pending = []
    remainder = []
    cursor = 0
    for index, mention in enumerate(mentions):
        remainder.append(text[cursor:mention.start()])
        grade = (mention.group(1) or mention.group(2)).upper()
        next_start = mentions[index + 1].start() if index + 1 < len(mentions) else len(text)
        tail = text[mention.end():next_start]
        negative = NEGATIVE.match(tail)
        positive = POSITIVE.match(tail)
        cursor = mention.end()
        if negative:
            if pending:
                return None
            denied.add(grade)
            cursor += negative.end()
        elif positive:
            allowed.update(pending + [grade])
            pending.clear()
            cursor += positive.end()
        elif index + 1 < len(mentions) and CHOICE_JOIN.fullmatch(tail):
            pending.append(grade)
            cursor = next_start
        elif (index + 1 == len(mentions) and END_MARKS.fullmatch(tail)
              and (pending or denied or (not text[:mention.start()].strip() and mention.group(1)))):
            allowed.update(pending + [grade])
            pending.clear()
        else:
            return None
    remainder.append(text[cursor:])
    if pending or allowed.intersection(denied) or UNRESOLVED.search(' '.join(remainder)):
        return None
    return (allowed or set(GRADES)) - denied


def validate(snapshot, now):
    if not exact_keys(snapshot, ROOT_KEYS) or snapshot['schema'] != SCHEMA:
        return 'invalid_snapshot'
    items = snapshot['items']
    replies = snapshot['reply_options']
    observed = snapshot['observed_at']
    until = snapshot['valid_until']
    if (type(observed) is not int or type(until) is not int
            or type(snapshot['spotlight_allowed']) is not bool
            or type(items) is not list or len(items) > 2000
            or type(replies) is not list or len(replies) > 8):
        return 'invalid_snapshot'
    if not observed <= now < until <= observed + 150:
        return 'stale_snapshot'
    keys = set()
    for item in items:
        if not valid_item(item) or pair_key(item) in keys:
            return 'invalid_snapshot'
        keys.add(pair_key(item))
    for reply in replies:
        if (not exact_keys(reply, REPLY_KEYS) or type(reply['thread']) is not int
                or reply['thread'] <= 0 or not public_text(reply['request'], 350, multiline=True)
                or type(reply['eligible']) is not list or len(reply['eligible']) > len(keys)):
            return 'invalid_snapshot'
        seen = set()
        for pair in reply['eligible']:
            if not exact_keys(pair, PAIR_KEYS) or not valid_pair(pair):
                return 'invalid_snapshot'
            key = pair_key(pair)
            if key not in keys or key in seen:
                return 'invalid_snapshot'
            seen.add(key)
    return None


def candidate_order(items, now):
    def priority(item):
        expiry = item['expiry']
        upcoming = item['grade'] == 'C' and expiry is not None and expiry > now
        return (not upcoming, expiry if upcoming else 0, item['pack_label'] != 'explicit_small')

    categories = {grade: {} for grade in GRADES}
    for item in items:
        categories[item['grade']].setdefault(item['category'], []).append(item)
    queues = {}
    for grade, grouped in categories.items():
        groups = [deque(sorted(group, key=priority)) for group in grouped.values()]
        groups.sort(key=len, reverse=True)
        if grade == 'C' and groups:
            first = min(range(len(groups)), key=lambda index: priority(groups[index][0]))
            groups.insert(0, groups.pop(first))
        queues[grade] = deque(groups)
    ordered = []
    while any(queues.values()):
        for grade in GRADES:
            groups = queues[grade]
            if groups:
                group = groups.popleft()
                ordered.append(group.popleft())
                if group:
                    groups.append(group)
    return ordered


def json_length(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False))


def select(snapshot, now):
    items = []
    for item in snapshot['items']:
        label, count = pack_fields(item['name'])
        items.append(dict(item, pack_label=label, pack_count=count))
    ordered = candidate_order(items, now)
    by_key = {pair_key(item): item for item in ordered}
    output = {'status': 'options', 'spotlight_allowed': snapshot['spotlight_allowed'], 'items': [], 'reply_options': []}
    visible = set()
    remaining = 5500 - json_length(output)

    def add_item(item):
        nonlocal remaining
        key = pair_key(item)
        if key in visible:
            return True
        cost = json_length(item) + bool(output['items'])
        if len(visible) >= 16 or cost > remaining:
            return False
        output['items'].append(item)
        visible.add(key)
        remaining -= cost
        return True

    represented = set()
    for item in ordered:
        grade = item['grade']
        if grade not in represented and add_item(item):
            represented.add(grade)
        if len(represented) == len(GRADES):
            break

    projected_replies = []
    for reply in snapshot['reply_options']:
        accepted = grade_filter(reply['request'])
        if not accepted:
            continue
        eligible = [pair for pair in reply['eligible'] if pair['grade'] in accepted]
        for pair in sorted(eligible, key=lambda pair: pair_key(pair) not in visible):
            projected = {'thread': reply['thread'], 'request': reply['request'], 'eligible': [pair]}
            cost = json_length(projected) + bool(output['reply_options'])
            if cost > remaining:
                continue
            remaining -= cost
            if add_item(by_key[pair_key(pair)]):
                output['reply_options'].append(projected)
                projected_replies.append((projected, eligible))
                break
            remaining += cost

    for item in ordered:
        if len(visible) == 16:
            break
        add_item(item)

    for projected, eligible in projected_replies:
        included = {pair_key(projected['eligible'][0])}
        for pair in eligible:
            key = pair_key(pair)
            if key in visible and key not in included:
                cost = json_length(pair) + 1
                if cost <= remaining:
                    included.add(key)
                    remaining -= cost
        projected['eligible'] = [pair for pair in eligible if pair_key(pair) in included]
    return output


def run(args, kit):
    if type(args) is not dict or args != {'mode': 'context'}:
        return unavailable('invalid_args')
    try:
        raw = SOURCE.read_text(encoding='utf-8')
    except OSError:
        return unavailable('input_missing')
    except UnicodeError:
        return unavailable('invalid_snapshot')
    try:
        snapshot = json.loads(raw, object_pairs_hook=unique_object)
    except (ValueError, RecursionError):
        return unavailable('invalid_snapshot')
    now = time.time()
    problem = validate(snapshot, now)
    if problem:
        return unavailable(problem)
    return select(snapshot, now)
