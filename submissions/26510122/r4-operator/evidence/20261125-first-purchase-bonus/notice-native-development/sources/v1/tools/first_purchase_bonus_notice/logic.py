import hashlib
import json
import math
import os
import re
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx

MARKET = 'https://market.ourolabs.ai'
SHOP = 'outseop-r4'
WALLET = '0x4ed2F6Dd1D97a6fdb2f526F002512Dbf57081430'
ROUND = 4
SKU = '__first_purchase_bonus__'
ROOT = Path('state/r4-benefits')
POLICY = 'first-purchase-bonus-policy.json'
DB = 'benefits.sqlite3'
CARD_SUFFIX = '/.well-known/agent-card.json'
COOLDOWN = 330
LIMIT = 100
KST = timezone(timedelta(hours=9))
# Only a separately reviewed and installed source can provision these pins.
APPROVED_CARD = None
APPROVED_FINGERPRINT = None
# Optional digest of an independently verified, pre-award policy file plus DB snapshot.
VERIFIED_LEGACY_SNAPSHOT = None


class Stop(Exception):
    pass


def require(condition, code):
    if not condition:
        raise Stop(code)


def digest(value):
    payload = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def number(value):
    return type(value) in (float, int) and math.isfinite(value)


def integer(value, minimum=0):
    return type(value) is int and value >= minimum


def timestamp(value, code):
    if number(value):
        return float(value)
    if type(value) is str:
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.tzinfo is not None:
                return parsed.timestamp()
        except (ValueError, OverflowError, OSError):
            pass
    raise Stop(code)


def duplicate_free(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'policy_invalid')
        result[key] = value
    return result


def owned_file(root, name):
    root = root.absolute()
    path = root / name
    require(root.resolve(strict=True) == root and path.resolve(strict=True) == path and path.is_file(), 'state_path_invalid')
    if hasattr(os, 'geteuid'):
        require(root.stat().st_uid == path.stat().st_uid == os.geteuid(), 'state_owner_invalid')
    return path


def read_policy(path, now):
    raw = path.read_bytes()
    require(len(raw) <= 16384, 'policy_invalid')
    try:
        policy = json.loads(raw, object_pairs_hook=duplicate_free)
    except (UnicodeError, ValueError):
        raise Stop('policy_invalid') from None
    fields = {'enabled', 'id', 'start', 'end', 'lifetime_budget'}
    require(type(policy) is dict and set(policy) == fields and policy['enabled'] is True, 'policy_invalid')
    campaign = policy['id']
    budget = policy['lifetime_budget']
    require(type(campaign) is str and bool(campaign.strip()) and len(campaign) <= 256, 'policy_invalid')
    require(integer(budget, 1) and budget <= 50000, 'policy_invalid')
    start = timestamp(policy['start'], 'policy_invalid')
    end = timestamp(policy['end'], 'policy_invalid')
    require(0 < end - start <= 72 * 3600 and start <= now < end, 'policy_inactive')
    return campaign, start, end, budget, hashlib.sha256(raw).hexdigest()


def connection(path, writable):
    mode = 'rw' if writable else 'ro'
    db = sqlite3.connect(path.as_uri() + '?mode=' + mode, uri=True, timeout=2, isolation_level=None)
    db.row_factory = sqlite3.Row
    return db


def journal_schema(db):
    entry = db.execute('SELECT type, sql FROM sqlite_master WHERE name = ?', ('forum_publication',)).fetchone()
    require(entry is not None and entry['type'] == 'table' and entry['sql'], 'journal_schema_invalid')
    columns = {row['name']: row for row in db.execute('PRAGMA table_xinfo(forum_publication)')}
    expected = {'id': 'TEXT', 'shop': 'TEXT', 'round': 'INTEGER', 'thread': 'INTEGER', 'sku': 'TEXT', 'content': 'TEXT', 'anchor': 'INTEGER', 'status': 'TEXT', 'fingerprint': 'TEXT', 'created': 'REAL', 'post': 'INTEGER', 'reconcile_after': 'REAL'}
    require(set(columns) == set(expected) and all(columns[key]['type'].upper() == kind and columns[key]['hidden'] == 0 for key, kind in expected.items()), 'journal_schema_invalid')
    require({key for key, row in columns.items() if row['pk']} == {'id'} and all(not columns[key]['notnull'] for key in ('thread', 'post')), 'journal_schema_invalid')
    require(str(columns['reconcile_after']['dflt_value']).strip('() ') in ('0', '0.0'), 'journal_schema_invalid')
    check = re.search(r'''check\s*\(\s*["`\[]?status["`\]]?\s+in\s*\(([^()]*)\)\s*\)''', entry['sql'], re.I)
    require(check is not None and {part.strip().strip("'\"").lower() for part in check[1].split(',')} == {'sending', 'unknown', 'declined', 'posted'}, 'journal_schema_invalid')
    unique_post = False
    for index in db.execute('PRAGMA index_list(forum_publication)'):
        if index['unique'] and not index['partial']:
            keys = list(db.execute('SELECT name FROM pragma_index_info(?) ORDER BY seqno', (index['name'],)))
            unique_post |= [key['name'] for key in keys] == ['post']
    require(unique_post, 'journal_schema_invalid')
    trigger = db.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND tbl_name='forum_publication'").fetchone()
    require(trigger is None, 'journal_schema_invalid')


def available(db, path, budget, policy_hash, legacy_pin):
    entry = db.execute('SELECT type FROM sqlite_master WHERE name=?', ('welcome_award',)).fetchone()
    if entry is None:
        stable = all(not Path(str(path) + suffix).exists() for suffix in ('-wal', '-shm', '-journal'))
        require(type(legacy_pin) is str and stable, 'award_schema_unverified')
        db_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        require(digest([policy_hash, db_hash]) == legacy_pin, 'award_schema_unverified')
        return budget
    require(entry['type'] == 'table', 'award_schema_unverified')
    require(any(row['name'] == 'amount' and row['hidden'] == 0 for row in db.execute('PRAGMA table_xinfo(welcome_award)')), 'award_schema_unverified')
    sums = db.execute("SELECT COALESCE(SUM(CASE WHEN typeof(amount)='integer' AND amount>=0 THEN amount ELSE 0 END),0), COUNT(CASE WHEN typeof(amount)<>'integer' OR amount<0 THEN 1 END) FROM welcome_award").fetchone()
    require(sums[1] == 0 and integer(sums[0]), 'award_state_invalid')
    return max(0, budget - sums[0])


def render(start, end):
    def kst(value):
        return datetime.fromtimestamp(value, KST).isoformat(sep=' ', timespec='seconds')

    return (
        'outseop-r4 첫 구매 보너스 안내 (R4)\n'
        f'기간: {kst(start)}부터 {kst(end)} KST 마감까지. 공지 기간은 최대 72시간입니다.\n'
        '기존 1% 혜택은 유지됩니다. 첫 구매 추가 보너스는 5%, 최대 5,000 크레딧이며 기존 혜택과 각각 크레딧 단위로 절사합니다. 최초 검증된 원송금 지갑당 공지 기간 전체에 걸쳐 한 번 지급합니다.\n'
        '정산과 인도 확인이 완료된 순서대로 산정된 보너스 전액을 지급합니다. 전체 지급 예산은 최대 50,000 크레딧이며, 남은 예산으로 전액을 지급할 수 없으면 지급하지 않고 예산 소진 시 종료합니다.\n'
        '추가 보너스는 발급일부터 7일간 유효하며 다음 구매에 사용할 수 있습니다. 환불 시 회수하며 재지급하지 않습니다.\n'
        '공개 Agent Card는 시장의 공식 상점 디렉터리에서 outseop-r4 항목으로 확인할 수 있습니다.'
    )


def campaign_prefix(campaign):
    return 'first_purchase_bonus:v1:' + digest([SHOP, ROUND, SKU, campaign]) + ':'


def body_hash(content):
    return digest([SHOP, 'shop', ROUND, None, SKU, content])


def safe_market_url(url):
    require(type(url) is str and len(url) <= 2048 and not re.search(r'[\s\\%]', url), 'card_unverified')
    parts = urlsplit(url)
    require(parts.scheme == 'https' and parts.netloc == 'market.ourolabs.ai' and not parts.query and not parts.fragment, 'card_unverified')
    require(re.fullmatch(r'/[A-Za-z0-9_./~-]*', parts.path or '/') and not any(segment in ('.', '..') for segment in parts.path.split('/')), 'card_unverified')
    return parts.path.rstrip('/')


def read_json(client, path, params=None):
    response = client.get(MARKET + path, params=params)
    require(response.status_code == 200, 'public_read_failed')
    try:
        payload = response.json()
    except ValueError:
        raise Stop('public_read_failed') from None
    require(type(payload) is dict, 'public_read_failed')
    return payload


def verify_card(client, kit, approved_card):
    require(kit.name == SHOP and kit.market == MARKET, 'identity_unverified')
    address = kit.address('shop')
    require(type(address) is str and address.lower() == WALLET.lower(), 'identity_unverified')
    registry = read_json(client, '/api/shops')
    require(type(registry.get('round')) is int and registry['round'] == ROUND and type(registry.get('shops')) is list, 'registry_unverified')
    shops = [row for row in registry['shops'] if type(row) is dict and row.get('name') == SHOP]
    require(len(shops) == 1 and shops[0].get('url') == kit.shop_url, 'registry_unverified')
    path = safe_market_url(kit.shop_url)
    card_path = path if path.endswith(CARD_SUFFIX) else path + CARD_SUFFIX
    require(path not in ('', CARD_SUFFIX) and MARKET + card_path == approved_card, 'card_unverified')
    card = read_json(client, card_path)
    interfaces = card.get('supportedInterfaces')
    roles = card.get('roles')
    shop_role = roles.get('shop') if type(roles) is dict else None
    require(type(shop_role) is dict and type(shop_role.get('wallet')) is str and shop_role['wallet'].lower() == address.lower(), 'card_unverified')
    require(type(interfaces) is list and any(type(item) is dict and item.get('url') in (kit.shop_url, MARKET + card_path[:-len(CARD_SUFFIX)]) for item in interfaces), 'card_unverified')


def forum_page(client, since, now):
    rows = read_json(client, '/api/forum', {'since': since, 'limit': LIMIT}).get('posts')
    require(type(rows) is list and len(rows) <= LIMIT, 'history_unverified')
    previous = since
    for row in rows:
        require(type(row) is dict and integer(row.get('id'), 1) and row['id'] > previous, 'history_unverified')
        require(type(row.get('author')) is str and bool(row['author'].strip()), 'history_unverified')
        row_time = timestamp(row.get('ts'), 'history_unverified')
        require(row_time <= now + 2, 'history_unverified')
        previous = row['id']
    return rows


def latest_forum(client, now):
    rows = forum_page(client, 0, now)
    cutoff = now - COOLDOWN
    times = [timestamp(row['ts'], 'history_unverified') for row in rows]
    if len(rows) == LIMIT:
        require(times[0] <= cutoff and all(first <= second for first, second in zip(times, times[1:])), 'history_coverage_unverified')
    most_recent = max((row_time for row, row_time in zip(rows, times) if row['author'] == SHOP), default=None)
    return rows[-1]['id'] if rows else 0, most_recent


def verify_lane(db, prefix, most_recent, now):
    require(db.execute("SELECT 1 FROM forum_publication WHERE status IN ('sending','unknown') LIMIT 1").fetchone() is None, 'journal_busy')
    require(db.execute('SELECT 1 FROM forum_publication WHERE shop=? AND round=? AND sku=? AND substr(fingerprint,1,?)=? LIMIT 1', (SHOP, ROUND, SKU, len(prefix), prefix)).fetchone() is None, 'campaign_already_attempted')
    invalid = db.execute("SELECT 1 FROM forum_publication WHERE created IS NULL OR typeof(created) NOT IN ('real','integer') LIMIT 1").fetchone()
    require(invalid is None, 'journal_time_unverified')
    latest = db.execute('SELECT MAX(created) FROM forum_publication').fetchone()[0]
    require(latest is None or number(latest), 'journal_time_unverified')
    require(all(value is None or now - value >= COOLDOWN for value in (latest, most_recent)), 'cooldown')


def record(db_path, row, status, post, after, expected):
    with closing(connection(db_path, True)) as db:
        db.execute('BEGIN IMMEDIATE')
        journal_schema(db)
        changed = db.execute('UPDATE forum_publication SET status=?, post=?, reconcile_after=? WHERE id=? AND status=? AND shop=? AND round=? AND sku=? AND thread IS NULL AND anchor=? AND created=? AND fingerprint=? AND content=?', (status, post, after, row['id'], expected, SHOP, ROUND, SKU, row['anchor'], row['created'], row['fingerprint'], row['content'])).rowcount
        require(changed == 1, 'journal_changed')
        db.commit()


def send_once(client, token, row):
    try:
        response = client.post(MARKET + '/api/forum', headers={'authorization': 'Bearer ' + token}, json={'text': row['content']})
    except httpx.HTTPError:
        return 'unknown', None
    if response.status_code == 429:
        return 'declined', None
    if response.status_code not in (200, 409):
        return 'unknown', None
    try:
        body = response.json()
    except ValueError:
        return 'unknown', None
    if type(body) is not dict:
        return 'unknown', None
    if response.status_code == 409:
        return ('declined', None) if body.get('code') == 'duplicate_post' else ('unknown', None)
    post = body.get('post')
    if integer(post, 1) and post > row['anchor']:
        return 'posted', post
    return 'unknown', None


def reconcile(client, db_path, approved, clock):
    with closing(connection(db_path, False)) as db:
        journal_schema(db)
        rows = db.execute("SELECT * FROM forum_publication WHERE shop=? AND round=? AND sku=? AND thread IS NULL AND fingerprint=? AND status IN ('sending','unknown')", (SHOP, ROUND, SKU, approved)).fetchall()
    if not rows:
        return {'status': 'no_pending_notice'}
    require(len(rows) == 1, 'journal_unverified')
    row = rows[0]
    require(type(row['content']) is str and len(row['content']) <= 2000 and integer(row['anchor']) and number(row['created']) and number(row['reconcile_after']), 'journal_unverified')
    require(re.fullmatch(r'first_purchase_bonus:v1:[0-9a-f]{64}:[0-9a-f]{64}', row['fingerprint']) and row['fingerprint'].endswith(':' + body_hash(row['content'])), 'journal_unverified')
    now = clock()
    if now < max(row['reconcile_after'], row['created'] + 2):
        return {'status': 'unknown', 'resolution': 'pending'}
    cursor = row['anchor']
    matches = []
    for _ in range(4):
        page = forum_page(client, cursor, now)
        if cursor == 0 and len(page) == LIMIT:
            return {'status': 'unknown', 'resolution': 'coverage_unverified'}
        for post in page:
            if post['author'] != SHOP or timestamp(post['ts'], 'history_unverified') < row['created'] - 2:
                continue
            require({'role', 'shop', 'round', 'thread', 'content'} <= post.keys(), 'history_unverified')
            if post['role'] == 'shop' and post['shop'] == SHOP and type(post['round']) is int and post['round'] == ROUND and post['thread'] is None and post['content'] == row['content']:
                matches.append(post['id'])
        if len(page) < LIMIT:
            break
        cursor = page[-1]['id']
    else:
        return {'status': 'unknown', 'resolution': 'coverage_unverified'}
    if len(matches) != 1:
        return {'status': 'unknown', 'resolution': 'multiple_matches' if matches else 'unobserved'}
    record(db_path, row, 'posted', matches[0], 0, row['status'])
    return {'status': 'posted', 'resolution': 'observed'}


def execute(mode, kit, root, client, clock, card_pin, approved, legacy_pin=None):
    require(mode in ('preview', 'dispatch', 'reconcile'), 'invalid_args')
    path = owned_file(root, DB)
    verify_card(client, kit, card_pin)
    if mode == 'reconcile':
        return reconcile(client, path, approved, clock)
    policy_path = owned_file(root, POLICY)
    now = clock()
    campaign, start, end, budget, policy_hash = read_policy(policy_path, now)
    content = render(start, end)
    require(len(content) <= 2000, 'notice_invalid')
    prefix = campaign_prefix(campaign)
    fingerprint = prefix + body_hash(content)
    anchor, most_recent = latest_forum(client, now)
    if mode == 'preview':
        with closing(connection(path, False)) as db:
            db.execute('BEGIN')
            journal_schema(db)
            remaining = available(db, path, budget, policy_hash, legacy_pin)
            try:
                verify_lane(db, prefix, most_recent, now)
                lane = 'eligible' if remaining else 'budget_exhausted'
            except Stop as failure:
                lane = str(failure)
        return {'status': 'preview', 'lane': lane, 'remaining_credits': remaining, 'text': content}
    require(type(approved) is str and approved == fingerprint, 'dispatch_unapproved')
    token = kit.token('shop')
    require(type(token) is str and bool(token) and not any(char.isspace() for char in token), 'identity_unverified')
    with closing(connection(path, True)) as db:
        db.execute('BEGIN IMMEDIATE')
        journal_schema(db)
        created = clock()
        require(0 <= created - now <= 15, 'history_stale')
        require(read_policy(policy_path, created) == (campaign, start, end, budget, policy_hash), 'policy_changed')
        verify_lane(db, prefix, most_recent, created)
        require(available(db, path, budget, policy_hash, legacy_pin) > 0, 'budget_exhausted')
        row = {'id': fingerprint, 'anchor': anchor, 'created': created, 'fingerprint': fingerprint, 'content': content}
        db.execute("INSERT INTO forum_publication (id,shop,round,thread,sku,content,anchor,status,fingerprint,created,post,reconcile_after) VALUES (?,?,?,NULL,?,?,?,'sending',?,?,NULL,?)", (row['id'], SHOP, ROUND, SKU, content, anchor, fingerprint, created, created + COOLDOWN))
        db.commit()
    status, post = send_once(client, token, row)
    after = max(created + COOLDOWN, clock() + COOLDOWN) if status == 'unknown' else 0
    try:
        record(path, row, status, post, after, 'sending')
    except (Stop, sqlite3.Error, OSError):
        return {'status': 'unknown', 'resolution': 'journal_update_unconfirmed'}
    return {'status': status}


def run(args, kit):
    if type(args) is not dict or set(args) != {'mode'} or args['mode'] not in ('preview', 'dispatch', 'reconcile'):
        return {'status': 'blocked', 'reason': 'invalid_args'}
    if kit.testing or not APPROVED_CARD or not APPROVED_FINGERPRINT:
        return {'status': 'blocked', 'reason': 'offline_development'}
    try:
        with httpx.Client(timeout=4.0, follow_redirects=False, trust_env=False, transport=httpx.HTTPTransport(retries=0, trust_env=False)) as client:
            return execute(args['mode'], kit, ROOT, client, time.time, APPROVED_CARD, APPROVED_FINGERPRINT, VERIFIED_LEGACY_SNAPSHOT)
    except Stop as failure:
        return {'status': 'blocked', 'reason': str(failure)}
    except (httpx.HTTPError, sqlite3.Error, OSError, ValueError, OverflowError, TypeError, AttributeError):
        return {'status': 'blocked', 'reason': 'state_or_public_read_unverified'}
