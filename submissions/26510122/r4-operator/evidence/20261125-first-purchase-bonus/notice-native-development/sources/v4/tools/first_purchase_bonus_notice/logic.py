import hashlib
import json
import math
import os
import re
import sqlite3
import stat
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx

MARKET = 'https://market.ourolabs.ai'
SHOP = 'outseop-r4'
WALLET = '0x5FDC134D790EFB72DF1bbb922F2b49fcADe349C6'
ROUND = 4
SKU = '__first_purchase_bonus__'
ROOT = Path('state/r4-benefits')
POLICY = 'first-purchase-bonus-policy.json'
APPROVAL = 'first-purchase-bonus-notice-approval.json'
DB = 'benefits.sqlite3'
CARD_SUFFIX = '/.well-known/agent-card.json'
COOLDOWN = 330
LIMIT = 100
KST = timezone(timedelta(hours=9))
SHA256 = re.compile(r'[0-9a-f]{64}')
ADDRESS = re.compile(r'0x[0-9a-fA-F]{40}')
FINGERPRINT = re.compile(r'first_purchase_bonus:v3:[0-9a-f]{64}:[0-9a-f]{64}')
ISO_TIME = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})', re.ASCII)

BASELINE_SCHEMA = '''
CREATE TABLE IF NOT EXISTS identity (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1), shop TEXT NOT NULL, wallet TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS account (
    key TEXT PRIMARY KEY, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS customer_profile (
    owner TEXT PRIMARY KEY REFERENCES account(key), profile_id TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS visit (
    id INTEGER PRIMARY KEY, owner TEXT NOT NULL REFERENCES customer_profile(owner),
    started REAL NOT NULL, last_seen REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS visit_latest ON visit(owner,id DESC);
CREATE TABLE IF NOT EXISTS visit_session_transport (
    visit_id INTEGER NOT NULL REFERENCES visit(id), transport_hash TEXT NOT NULL,
    PRIMARY KEY(visit_id,transport_hash)
);
CREATE TABLE IF NOT EXISTS profile_fact (
    id INTEGER PRIMARY KEY, owner TEXT NOT NULL REFERENCES customer_profile(owner),
    field TEXT NOT NULL, fact_key TEXT NOT NULL, value TEXT, source TEXT NOT NULL,
    confidence TEXT NOT NULL CHECK(confidence='self_reported'), at REAL NOT NULL,
    discarded INTEGER NOT NULL CHECK(discarded IN (0,1))
);
CREATE INDEX IF NOT EXISTS profile_fact_latest ON profile_fact(owner,field,fact_key,id DESC);
CREATE TABLE IF NOT EXISTS ticket (
    key TEXT PRIMARY KEY, sku TEXT NOT NULL, owner TEXT REFERENCES account(key),
    created REAL NOT NULL, expires REAL NOT NULL, discount INTEGER NOT NULL,
    ready REAL,
    status TEXT NOT NULL CHECK(status IN ('waiting','held','used','released'))
);
CREATE INDEX IF NOT EXISTS queue_lookup ON ticket(sku,status,expires,created);
CREATE TABLE IF NOT EXISTS sale (
    id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES account(key),
    unit TEXT NOT NULL, sku TEXT NOT NULL, base INTEGER NOT NULL CHECK(base>0),
    cost INTEGER NOT NULL CHECK(cost>=0), price INTEGER NOT NULL CHECK(price>0),
    discount INTEGER NOT NULL CHECK(discount>=0), spent INTEGER NOT NULL CHECK(spent>=0),
    ticket TEXT REFERENCES ticket(key), shop_url TEXT NOT NULL, wallet TEXT NOT NULL, created REAL NOT NULL,
    digest TEXT UNIQUE NOT NULL, jwt TEXT NOT NULL, expected_wei TEXT NOT NULL,
    fee_wei TEXT NOT NULL, gas_cap_wei TEXT NOT NULL, fee_wallet TEXT NOT NULL, grade TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('issued','cancel_requested','paid','missing','settled','refunded')),
    market_order TEXT UNIQUE, payment TEXT UNIQUE, fee_payment TEXT UNIQUE, payer TEXT, settled REAL, broken REAL,
    CHECK(price=base-discount-spent)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_unit ON sale(unit)
    WHERE status IN ('issued','cancel_requested','paid','missing');
CREATE TABLE IF NOT EXISTS sale_category (
    sale_id TEXT PRIMARY KEY REFERENCES sale(id), category TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sale_buyer (
    sale_id TEXT PRIMARY KEY REFERENCES sale(id), market_buyer TEXT NOT NULL, verified_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS lot (
    sale_id TEXT PRIMARY KEY REFERENCES sale(id), owner TEXT NOT NULL REFERENCES account(key),
    amount INTEGER NOT NULL CHECK(amount>0), expires REAL NOT NULL, revoked REAL
);
CREATE TABLE IF NOT EXISTS allocation (
    id INTEGER PRIMARY KEY, sale_id TEXT REFERENCES sale(id), lot_id TEXT NOT NULL REFERENCES lot(sale_id),
    amount INTEGER NOT NULL CHECK(amount>0),
    status TEXT NOT NULL CHECK(status IN ('held','spent','offset','released')),
    CHECK(sale_id IS NOT lot_id)
);
CREATE INDEX IF NOT EXISTS allocation_lot ON allocation(lot_id,status);
CREATE INDEX IF NOT EXISTS allocation_sale ON allocation(sale_id,status);
CREATE TABLE IF NOT EXISTS refund (
    sale_id TEXT PRIMARY KEY REFERENCES sale(id), incoming TEXT NOT NULL UNIQUE,
    payer TEXT NOT NULL, wei TEXT NOT NULL, marker TEXT NOT NULL UNIQUE,
    transfer_wei TEXT NOT NULL, fee_wei TEXT NOT NULL, gas_wei TEXT NOT NULL, fee_payment TEXT,
    reason TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN (
        'requested','sending','pending_unknown','refunded')),
    outgoing TEXT UNIQUE, requested REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS event (
    id INTEGER PRIMARY KEY, at REAL NOT NULL, kind TEXT NOT NULL, reference TEXT NOT NULL,
    details TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS removal (
    unit TEXT PRIMARY KEY, seq INTEGER NOT NULL, reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stock_signal (
    observation TEXT NOT NULL, sku TEXT NOT NULL, outcome TEXT NOT NULL, at REAL NOT NULL,
    qualified INTEGER NOT NULL, PRIMARY KEY(observation,sku,outcome)
);
CREATE TABLE IF NOT EXISTS stockout_observation (
    demand TEXT PRIMARY KEY, sku TEXT NOT NULL, at REAL NOT NULL, reason TEXT NOT NULL, resolved REAL
);
CREATE TABLE IF NOT EXISTS broker_commit (
    request TEXT PRIMARY KEY, at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS broker_offer (
    id TEXT PRIMARY KEY, owner TEXT REFERENCES account(key), sku TEXT NOT NULL,
    base INTEGER NOT NULL CHECK(base>0), expires REAL NOT NULL, consumed REAL
);
CREATE TABLE IF NOT EXISTS cursor (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1), seq INTEGER NOT NULL, hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS promotion_loss (
    sale_id TEXT PRIMARY KEY REFERENCES sale(id), policy_id TEXT NOT NULL,
    reserved INTEGER NOT NULL CHECK(reserved>0), amount INTEGER NOT NULL CHECK(amount>=0),
    state TEXT NOT NULL CHECK(state IN ('reserved','settled','refunded')), at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS stock_observation (
    at INTEGER PRIMARY KEY, skus TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stockout_observation (
    demand TEXT PRIMARY KEY, sku TEXT NOT NULL, at REAL NOT NULL, reason TEXT NOT NULL, resolved REAL
);
CREATE TABLE IF NOT EXISTS stock_plan (
    window TEXT PRIMARY KEY, id TEXT NOT NULL UNIQUE, scope TEXT NOT NULL, planned REAL NOT NULL,
    expires REAL NOT NULL, opens REAL NOT NULL, closes REAL NOT NULL,
    choices TEXT NOT NULL, decision TEXT, status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stock_intent (
    id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES stock_plan(id), sku TEXT NOT NULL,
    qty INTEGER NOT NULL, quote TEXT UNIQUE, total INTEGER NOT NULL, marker TEXT,
    recipient TEXT, wei TEXT, units TEXT, tx TEXT UNIQUE, chain_anchor INTEGER, ledger_anchor INTEGER,
    state TEXT NOT NULL CHECK(state IN (
        'reserved','no_purchase','sending','unknown','paid','accepted','arrived')),
    created REAL NOT NULL, retry_at REAL NOT NULL DEFAULT 0, delivered TEXT,
    UNIQUE(plan_id,sku)
);
CREATE INDEX IF NOT EXISTS stock_intent_state ON stock_intent(state,retry_at);
CREATE TABLE IF NOT EXISTS stock_audit (
    id INTEGER PRIMARY KEY, at REAL NOT NULL, event TEXT NOT NULL, reference TEXT NOT NULL,
    summary TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS forum_publication (
    id TEXT PRIMARY KEY, shop TEXT NOT NULL, round INTEGER NOT NULL,
    thread INTEGER, sku TEXT NOT NULL, content TEXT NOT NULL, anchor INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('sending','unknown','declined','posted')),
    fingerprint TEXT,
    created REAL NOT NULL, post INTEGER UNIQUE, reconcile_after REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS forum_recent ON forum_publication(created,sku,thread);
'''
AWARD_SCHEMA = '''
CREATE TABLE welcome_award (
    payer TEXT NOT NULL PRIMARY KEY CHECK (payer = lower(payer)),
    sale_id TEXT NOT NULL UNIQUE,
    amount INTEGER NOT NULL CHECK (typeof(amount) = 'integer' AND amount BETWEEN 1 AND 5000),
    granted_at INTEGER NOT NULL,
    earned_event_id NOT NULL
)
'''
DDL_TOKEN = re.compile(r"'(?:''|[^'])*'|[A-Za-z_][A-Za-z_0-9]*|[0-9]+|\S")


class Stop(Exception):
    pass


def require(condition, reason):
    if not condition:
        raise Stop(reason)


def integer(value, minimum=0):
    return type(value) is int and value >= minimum


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def wallet_matches(value):
    return type(value) is str and ADDRESS.fullmatch(value) and value.lower() == WALLET.lower()


def digest(value):
    raw = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def parse_json(raw, reason):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, reason)
            result[key] = value
        return result

    def reject_constant(_):
        raise Stop(reason)

    try:
        return json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)
    except (UnicodeError, ValueError, RecursionError):
        raise Stop(reason) from None


def timestamp(value, reason):
    if number(value):
        return float(value)
    if type(value) is str and ISO_TIME.fullmatch(value):
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
        except (ValueError, OverflowError, OSError):
            pass
    raise Stop(reason)


def trusted_stat(info, kind):
    require(kind(info.st_mode), 'state_path_invalid')
    require(hasattr(os, 'geteuid') and info.st_uid == os.geteuid() and not info.st_mode & 0o022, 'state_owner_invalid')
    if kind is stat.S_ISREG:
        require(info.st_nlink == 1, 'state_path_invalid')


def trusted_root(root):
    cwd = Path.cwd()
    target = root.absolute()
    parts = target.relative_to(cwd).parts
    require(len(parts) >= 2 and parts[:2] == ('state', 'r4-benefits') and '..' not in parts, 'state_path_invalid')
    require(cwd.resolve(strict=True) == cwd, 'state_path_invalid')
    trusted_stat(cwd.lstat(), stat.S_ISDIR)
    current = cwd
    for part in parts:
        current /= part
        trusted_stat(current.lstat(), stat.S_ISDIR)
    return target


def owned_bytes(root, name):
    path = trusted_root(root) / name
    listed = path.lstat()
    trusted_stat(listed, stat.S_ISREG)
    require(hasattr(os, 'O_NOFOLLOW'), 'state_path_invalid')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        trusted_stat(opened, stat.S_ISREG)
        require(os.path.samestat(listed, opened), 'state_path_invalid')
        raw = stream.read(16385)
        checked = os.fstat(stream.fileno())
        current = path.lstat()
        trusted_stat(checked, stat.S_ISREG)
        trusted_stat(current, stat.S_ISREG)
        require(os.path.samestat(opened, current) and (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) == (checked.st_size, checked.st_mtime_ns, checked.st_ctime_ns), 'state_changed')
    require(len(raw) <= 16384, 'state_file_invalid')
    return raw


def database_file(root):
    path = trusted_root(root) / DB
    info = path.lstat()
    trusted_stat(info, stat.S_ISREG)
    for suffix in ('-wal', '-shm', '-journal'):
        try:
            sidecar = path.with_name(path.name + suffix).lstat()
        except FileNotFoundError:
            continue
        trusted_stat(sidecar, stat.S_ISREG)
    return path, (info.st_dev, info.st_ino)


def read_policy(root, now):
    raw = owned_bytes(root, POLICY)
    policy = parse_json(raw, 'policy_invalid')
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


def public_base(url):
    require(type(url) is str and 0 < len(url) <= 2048 and url.isascii() and not re.search(r'[\x00-\x20\x7f\\%?#]', url), 'card_unverified')
    parts = urlsplit(url)
    host = parts.netloc
    valid_host = host == 'market.ourolabs.ai' or re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.trycloudflare\.com', host)
    require(parts.scheme == 'https' and valid_host and url == 'https://' + host + parts.path, 'card_unverified')
    require(re.fullmatch(r'(?:/[A-Za-z0-9_~.\-]+)*/?', parts.path) and not any(part in ('.', '..', '.well-known') for part in parts.path.split('/')), 'card_unverified')
    return url.rstrip('/')


def read_approval(root, kit, policy_hash, now):
    try:
        raw = owned_bytes(root, APPROVAL)
    except FileNotFoundError:
        raise Stop('approval_missing') from None
    data = parse_json(raw, 'approval_invalid')
    fields = {'shop', 'round', 'wallet', 'shop_url', 'card_url', 'observed_at', 'valid_until', 'policy_sha256', 'approved_fingerprint'}
    require(type(data) is dict and set(data) == fields, 'approval_invalid')
    require(data['shop'] == SHOP and integer(data['round'], 1) and data['round'] == ROUND and wallet_matches(data['wallet']), 'approval_invalid')
    require(data['shop_url'] == kit.shop_url, 'approval_changed')
    require(data['card_url'] == public_base(data['shop_url']) + CARD_SUFFIX, 'card_unverified')
    observed = timestamp(data['observed_at'], 'approval_invalid')
    expires = timestamp(data['valid_until'], 'approval_invalid')
    require(0 < expires - observed <= 150 and observed <= now < expires, 'approval_stale')
    claimed_hash = data['policy_sha256']
    require(type(claimed_hash) is str and SHA256.fullmatch(claimed_hash) and claimed_hash == policy_hash, 'approval_policy_changed')
    approved = data['approved_fingerprint']
    require(approved is None or (type(approved) is str and FINGERPRINT.fullmatch(approved)), 'approval_invalid')
    return data, hashlib.sha256(raw).hexdigest()


def read_public(client, path, params=None):
    response = client.get(MARKET + path, params=params)
    require(response.status_code == 200, 'public_read_failed')
    return parse_json(response.content, 'public_read_failed')


def registry_row(client, path, key, reason):
    body = read_public(client, path)
    require(type(body) is dict and integer(body.get('round'), 1) and body['round'] == ROUND and type(body.get(key)) is list, reason)
    require(all(type(row) is dict and type(row.get('name')) is str for row in body[key]), reason)
    rows = [row for row in body[key] if row['name'] == SHOP]
    require(len(rows) == 1, reason)
    return rows[0]


def verify_registry(client, snapshot):
    shop = registry_row(client, '/api/shops', 'shops', 'shop_registry_unverified')
    require(shop.get('url') == snapshot['shop_url'] and wallet_matches(shop.get('pubkey')), 'shop_registry_unverified')
    agent = registry_row(client, '/api/agents', 'agents', 'agent_registry_unverified')
    roles = agent.get('roles')
    require(type(roles) is list and all(type(role) is str for role in roles) and 'shop' in roles and agent.get('card') == snapshot['card_url'], 'agent_registry_unverified')


def latest_forum(client, now):
    rows = read_public(client, '/api/forum', {'since': 0, 'limit': LIMIT})
    require(type(rows) is list and len(rows) <= LIMIT, 'history_unverified')
    previous_id = 0
    previous_time = None
    oldest = None
    own_latest = None
    for row in rows:
        require(type(row) is dict and integer(row.get('id'), 1) and row['id'] > previous_id, 'history_unverified')
        require(type(row.get('author')) is str and bool(row['author'].strip()) and row.get('role') in ('shop', 'buyer', 'market'), 'history_unverified')
        require(integer(row.get('round'), 1) and 'thread' in row and (row['thread'] is None or integer(row['thread'], 1)) and type(row.get('text')) is str, 'history_unverified')
        require(type(row.get('refs')) is list and integer(row.get('likes')) and integer(row.get('dislikes')) and number(row.get('score')), 'history_unverified')
        row_time = row.get('ts')
        require(integer(row_time, 1) and row_time <= now + 2 and (previous_time is None or previous_time <= row_time), 'history_unverified')
        if oldest is None:
            oldest = row_time
        if row['author'] == SHOP and row['role'] == 'shop' and row['round'] == ROUND:
            own_latest = row_time
        previous_id = row['id']
        previous_time = row_time
    if len(rows) == LIMIT:
        require(oldest <= now - COOLDOWN, 'history_coverage_unverified')
    return previous_id, own_latest


def connection(path, writable):
    mode = 'rw' if writable else 'ro'
    db = sqlite3.connect(path.as_uri() + '?mode=' + mode, uri=True, timeout=2, isolation_level=None)
    db.row_factory = sqlite3.Row
    return db


def journal_schema(db):
    entry = db.execute('SELECT type, sql FROM sqlite_master WHERE name=?', ('forum_publication',)).fetchone()
    require(entry is not None and entry['type'] == 'table' and entry['sql'], 'journal_schema_invalid')
    columns = {row['name']: row for row in db.execute('PRAGMA table_xinfo(forum_publication)')}
    expected = {'id': 'TEXT', 'shop': 'TEXT', 'round': 'INTEGER', 'thread': 'INTEGER', 'sku': 'TEXT', 'content': 'TEXT', 'anchor': 'INTEGER', 'status': 'TEXT', 'fingerprint': 'TEXT', 'created': 'REAL', 'post': 'INTEGER', 'reconcile_after': 'REAL'}
    require(set(columns) == set(expected) and all(columns[key]['type'].upper() == kind and columns[key]['hidden'] == 0 for key, kind in expected.items()), 'journal_schema_invalid')
    require({name for name, col in columns.items() if col['pk']} == {'id'} and all(not columns[key]['notnull'] for key in ('thread', 'post')), 'journal_schema_invalid')
    require(str(columns['reconcile_after']['dflt_value']).strip('() ') in ('0', '0.0'), 'journal_schema_invalid')
    check = re.search(r'check\s*\(\s*["`\[]?status["`\]]?\s+in\s*\(([^()]*)\)\s*\)', entry['sql'], re.I)
    require(check is not None and {part.strip().strip(chr(39) + chr(34)).lower() for part in check[1].split(',')} == {'sending', 'unknown', 'declined', 'posted'}, 'journal_schema_invalid')
    unique_post = False
    for index in db.execute('PRAGMA index_list(forum_publication)'):
        if index['unique'] and not index['partial']:
            keys = list(db.execute('SELECT name FROM pragma_index_info(?) ORDER BY seqno', (index['name'],)))
            unique_post |= [key['name'] for key in keys] == ['post']
    require(unique_post and db.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND tbl_name='forum_publication'").fetchone() is None, 'journal_schema_invalid')


def ddl_tokens(sql):
    tokens = [token if token.startswith("'") else token.lower() for token in DDL_TOKEN.findall(sql)]
    name_at = 3 if tokens[:2] == ['create', 'unique'] else 2
    if tokens[name_at:name_at + 3] == ['if', 'not', 'exists']:
        del tokens[name_at:name_at + 3]
    return tuple(tokens)


BASELINE_DEFINITIONS = tuple(ddl_tokens(statement) for statement in BASELINE_SCHEMA.split(';') if statement.strip())
AWARD_DEFINITION = ddl_tokens(AWARD_SCHEMA)


def budget_available(db, budget):
    reason = 'award_schema_unverified'
    entries = {row['name'].lower(): row for row in db.execute('SELECT type, name, sql FROM main.sqlite_master')}
    for expected in BASELINE_DEFINITIONS:
        kind, name = expected[2:4] if expected[1] == 'unique' else expected[1:3]
        entry = entries.get(name)
        require(entry is not None and entry['type'] == kind and entry['sql'] and ddl_tokens(entry['sql']) == expected, reason)
    identity_rows = db.execute('SELECT singleton, shop, wallet FROM main.identity LIMIT 2').fetchall()
    require(len(identity_rows) == 1, reason)
    singleton, shop, wallet = identity_rows[0]
    require(type(singleton) is int and singleton == 1 and shop == SHOP and wallet_matches(wallet), reason)
    require(not any(entry['type'] in ('table', 'view') and name != 'welcome_award' and ('award' in name or 'first_purchase_bonus' in name) for name, entry in entries.items()), reason)
    award = entries.get('welcome_award')
    if award is None:
        require(db.execute("SELECT count(*) FROM main.sale WHERE status IN ('settled','refunded')").fetchone()[0] == 0, reason)
        return True
    require(award['type'] == 'table' and award['sql'] and ddl_tokens(award['sql']) == AWARD_DEFINITION, reason)
    total, invalid = db.execute("SELECT COALESCE(SUM(CASE WHEN typeof(amount)='integer' AND amount BETWEEN 1 AND 5000 THEN amount ELSE 0 END),0), COUNT(CASE WHEN typeof(amount)<>'integer' OR amount NOT BETWEEN 1 AND 5000 THEN 1 END) FROM main.welcome_award").fetchone()
    require(invalid == 0 and integer(total), 'award_state_invalid')
    return total < budget


def render(start, end):
    def kst(value):
        return datetime.fromtimestamp(value, KST).isoformat(sep=' ', timespec='seconds')

    return (
        'outseop-r4 첫 구매 보너스 안내 (R4)\n'
        f'{kst(start)}부터 {kst(end)} KST 마감까지 적용합니다.\n'
        '기존 1% 혜택은 유지됩니다. 최초로 확인된 원송금 지갑의 첫 구매는 정산과 인도 확인 후 추가 5%를 지급합니다. 지갑당 한 번, 최대 5,000 크레딧이며 각 혜택은 크레딧 단위로 절사합니다.\n'
        '전체 지급 한도는 최대 50,000 크레딧입니다. 지급이 확정된 순서대로 산정액 전액을 지급합니다. 남은 예산으로 전액 지급이 어려우면 지급하지 않습니다.\n'
        '추가 보너스는 최초 정상 정산 시각부터 7일 동안 유효하며 (기존 적립 기한 유지) 다음 구매부터 사용할 수 있습니다. 환불 시 회수하며 재지급하지 않습니다.\n'
        '문의는 https://market.ourolabs.ai/board 에서 상점명 outseop-r4를 찾아 최신 Agent Card를 확인해 주세요.'
    )


def campaign_prefix(campaign, version):
    return 'first_purchase_bonus:' + version + ':' + digest([SHOP, ROUND, SKU, campaign]) + ':'


def proposed_fingerprint(policy, snapshot, content):
    return campaign_prefix(policy[0], 'v3') + digest([SHOP, 'shop', ROUND, None, SKU, WALLET, snapshot['shop_url'], snapshot['card_url'], policy[4], content])


def verify_lane(db, campaign, own_latest, now):
    require(db.execute("SELECT 1 FROM forum_publication WHERE status IN ('sending','unknown') LIMIT 1").fetchone() is None, 'journal_busy')
    prefixes = tuple(campaign_prefix(campaign, version) for version in ('v1', 'v2', 'v3'))
    attempted = db.execute('SELECT 1 FROM forum_publication WHERE shop=? AND round=? AND sku=? AND substr(fingerprint,1,?) IN (?,?,?) LIMIT 1', (SHOP, ROUND, SKU, len(prefixes[-1]), *prefixes)).fetchone()
    require(attempted is None, 'campaign_already_attempted')
    invalid = db.execute("SELECT 1 FROM forum_publication WHERE typeof(created) NOT IN ('real','integer') OR typeof(status)<>'text' OR status NOT IN ('sending','unknown','declined','posted') LIMIT 1").fetchone()
    require(invalid is None, 'journal_time_unverified')
    latest = db.execute('SELECT MAX(created) FROM forum_publication').fetchone()[0]
    require(latest is None or number(latest), 'journal_time_unverified')
    require(all(value is None or now - value >= COOLDOWN for value in (latest, own_latest)), 'cooldown')


def send_once(client, token, content, anchor):
    try:
        response = client.post(MARKET + '/api/forum', headers={'authorization': 'Bearer ' + token}, json={'text': content})
        if response.status_code == 429:
            return 'declined', None
        if response.status_code not in (200, 201, 409):
            return 'unknown', None
        body = parse_json(response.content, 'post_response_unverified')
        if type(body) is not dict:
            return 'unknown', None
        if response.status_code == 409:
            return ('declined', None) if body.get('code') == 'duplicate_post' else ('unknown', None)
        post = body.get('post')
        if integer(post, 1) and post > anchor:
            return 'posted', post
    except (httpx.HTTPError, Stop):
        pass
    return 'unknown', None


def finish(root, source, row, status, post, after):
    path, _ = source
    require(database_file(root) == source, 'journal_changed')
    with closing(connection(path, True)) as db:
        db.execute('BEGIN IMMEDIATE')
        require(database_file(root) == source, 'journal_changed')
        journal_schema(db)
        fingerprint, content, anchor, created = row
        updated = db.execute("UPDATE forum_publication SET status=?, post=?, reconcile_after=? WHERE id=? AND status='sending' AND shop=? AND round=? AND thread IS NULL AND sku=? AND fingerprint=? AND content=? AND anchor=? AND created=? AND post IS NULL", (status, post, after, fingerprint, SHOP, ROUND, SKU, fingerprint, content, anchor, created)).rowcount
        require(updated == 1, 'journal_changed')
        db.commit()


def execute(mode, kit, root, client, clock):
    require(mode in ('preview', 'dispatch'), 'invalid_args')
    require(kit.name == SHOP and kit.market == MARKET and wallet_matches(kit.address('shop')), 'identity_unverified')
    source = database_file(root)
    path, _ = source
    now = clock()
    policy = read_policy(root, now)
    campaign, start, end, budget, policy_hash = policy
    approval = read_approval(root, kit, policy_hash, now)
    snapshot, _ = approval
    content = render(start, end)
    require(len(content) <= 2000, 'notice_invalid')
    fingerprint = proposed_fingerprint(policy, snapshot, content)
    approved = snapshot['approved_fingerprint']
    require(approved is None or approved == fingerprint, 'approval_fingerprint_changed')
    if mode == 'dispatch':
        require(approved == fingerprint, 'dispatch_unapproved')
    verify_registry(client, snapshot)
    observed = clock()
    anchor, own_latest = latest_forum(client, observed)
    if mode == 'preview':
        with closing(connection(path, False)) as db:
            db.execute('BEGIN')
            require(database_file(root) == source, 'journal_changed')
            journal_schema(db)
            funded = budget_available(db, budget)
            checked = clock()
            require(read_policy(root, checked) == policy, 'policy_changed')
            require(read_approval(root, kit, policy_hash, checked) == approval, 'approval_changed')
            try:
                verify_lane(db, campaign, own_latest, checked)
                lane = 'eligible' if funded else 'budget_exhausted'
            except Stop as failure:
                lane = str(failure)
        return {'status': 'preview', 'lane': lane, 'fingerprint': fingerprint, 'text': content}
    token = kit.token('shop')
    require(type(token) is str and bool(token) and token.isascii() and all(32 < ord(char) < 127 for char in token), 'identity_unverified')
    with closing(connection(path, True)) as db:
        db.execute('BEGIN IMMEDIATE')
        require(database_file(root) == source, 'journal_changed')
        journal_schema(db)
        verify_lane(db, campaign, own_latest, clock())
        require(budget_available(db, budget), 'budget_exhausted')
        created = clock()
        require(0 <= created - observed <= 15, 'history_stale')
        require(read_policy(root, created) == policy, 'policy_changed')
        require(read_approval(root, kit, policy_hash, created) == approval, 'approval_changed')
        require(clock() < min(end, timestamp(snapshot['valid_until'], 'approval_invalid')), 'source_expired')
        db.execute("INSERT INTO forum_publication (id,shop,round,thread,sku,content,anchor,status,fingerprint,created,post,reconcile_after) VALUES (?,?,?,NULL,?,?,?,'sending',?,?,NULL,?)", (fingerprint, SHOP, ROUND, SKU, content, anchor, fingerprint, created, created + COOLDOWN))
        db.commit()
    status, post = send_once(client, token, content, anchor)
    after = max(created, clock()) + COOLDOWN if status == 'unknown' else 0
    try:
        finish(root, source, (fingerprint, content, anchor, created), status, post, after)
    except (Stop, sqlite3.Error, OSError):
        return {'status': 'unknown', 'resolution': 'journal_update_unconfirmed'}
    return {'status': status}


def run(args, kit):
    if type(args) is not dict or set(args) != {'mode'} or args['mode'] not in ('preview', 'dispatch'):
        return {'status': 'blocked', 'reason': 'invalid_args'}
    if kit.testing:
        return {'status': 'blocked', 'reason': 'offline_development'}
    try:
        with httpx.Client(timeout=4.0, follow_redirects=False, trust_env=False, transport=httpx.HTTPTransport(retries=0, trust_env=False)) as client:
            return execute(args['mode'], kit, ROOT, client, time.time)
    except Stop as failure:
        return {'status': 'blocked', 'reason': str(failure)}
    except (httpx.HTTPError, sqlite3.Error, OSError, ValueError, OverflowError, TypeError, AttributeError):
        return {'status': 'blocked', 'reason': 'state_or_public_read_unverified'}
