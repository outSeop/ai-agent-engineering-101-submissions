from contextlib import ExitStack
from hashlib import sha256
from time import monotonic
from threading import RLock
from types import ModuleType
import hmac
import json
import math
import os
from pathlib import Path
import re
import stat

import httpx

V9_PATH = Path('codex-r4/forum_marketing9.py')
V9_HASH = 'b2edc8dba8c214a22074eb1f3db35ce5eb8234f444cf22710f025078b64e48e9'
POLICY = Path('state/r4-benefits/marketing-owner-policy.json')
SCHEMA = 'outseop-r4.marketing-owner.v1'
TICK_URL = 'http://127.0.0.1:18812/_internal/r4-marketing/tick'
HEX64 = re.compile(r'[0-9a-f]{64}')
READS = ('context', 'slate_context')
LOCK = RLock()
V9 = None


def hold():
    return {'status': 'hold'}


def unique_object(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError('duplicate JSON key')
    return result


def hex64(value):
    return type(value) is str and HEX64.fullmatch(value) is not None


def secure_file(info, uid):
    return (stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600
            and info.st_uid == uid and info.st_nlink == 1 and 0 < info.st_size <= 4096)


def identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def read_policy_at(root, relative):
    if relative.is_absolute() or '..' in relative.parts:
        return None
    uid = os.geteuid()
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    with ExitStack() as stack:
        directory = os.open(root, directory_flags)
        stack.callback(os.close, directory)
        parents = []
        for part in relative.parts[:-1]:
            child = os.open(part, directory_flags, dir_fd=directory)
            stack.callback(os.close, child)
            info = os.fstat(child)
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or info.st_mode & 0o022:
                return None
            parents.append((directory, part, child, identity(info)))
            directory = child
        leaf = relative.name
        fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        stack.callback(os.close, fd)
        before = os.fstat(fd)
        if not secure_file(before, uid):
            return None
        with os.fdopen(fd, 'rb', closefd=False) as handle:
            raw = handle.read(4097)
        after = os.fstat(fd)
        named = os.stat(leaf, dir_fd=directory, follow_symlinks=False)
        if len(raw) != before.st_size or identity(before) != identity(after) or identity(before) != identity(named):
            return None
        for parent, part, child, snapshot in reversed(parents):
            named = os.stat(part, dir_fd=parent, follow_symlinks=False)
            if identity(named) != snapshot or identity(os.fstat(child)) != snapshot:
                return None
    policy = json.loads(raw.decode('utf-8'), object_pairs_hook=unique_object)
    if (type(policy) is not dict or set(policy) != {'schema', 'active', 'generation', 'token'}
            or policy['schema'] != SCHEMA or policy['active'] is not True
            or not hex64(policy['generation']) or not hex64(policy['token'])):
        return None
    return policy


def read_policy():
    try:
        return read_policy_at('.', POLICY)
    except (OSError, ValueError, TypeError, AttributeError, NotImplementedError, RecursionError):
        return None


def request_tick(policy):
    response = httpx.post(TICK_URL, json={'generation': policy['generation']},
                          headers={'Authorization': 'Bearer ' + policy['token']},
                          timeout=130, trust_env=False, follow_redirects=False)
    if response.status_code == 200:
        result = json.loads(response.content.decode('utf-8'), object_pairs_hook=unique_object)
        if result == {'status': 'marketing_transferred'}:
            return {'status': 'marketing_transferred'}
    return hold()


def load_v9():
    global V9
    if V9 is None:
        source = V9_PATH.read_bytes()
        if sha256(source).hexdigest() != V9_HASH:
            raise ValueError('v9 digest mismatch')
        module = ModuleType('_outseop_r4_forum_marketing_v9')
        module.__file__ = str(V9_PATH)
        exec(compile(source, module.__file__, 'exec'), module.__dict__)
        V9 = module
    return V9


def delegate(args, kit, duration=None):
    with LOCK:
        previous = load_v9()
        if duration is None:
            return previous.run(args, kit)
        deadline = monotonic() + duration
        if previous.PARENT is None:
            previous.PARENT = previous.load_parent()
        parent = previous.PARENT
        original = parent.Market

        class BoundedMarket(original):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.deadline = min(self.deadline, deadline)

            def window_page(self, since, limit, read_deadline):
                return super().window_page(since, limit, min(read_deadline, self.deadline))

        parent.Market = BoundedMarket
        try:
            return previous.run(args, kit)
        finally:
            parent.Market = original


def run(args, kit):
    if type(args) is not dict:
        return hold()
    action = args.get('action')
    if action not in (*READS, 'publish', 'reconcile'):
        return hold()
    if any(isinstance(key, str) and key.startswith('scheduler_') and key != 'scheduler_generation' for key in args):
        return hold()
    has_generation = 'scheduler_generation' in args
    has_timeout = 'operation_timeout' in args
    try:
        if not has_generation and not has_timeout:
            if action in READS:
                return delegate(args, kit)
            if action == 'publish':
                return hold()
            policy = read_policy()
            return request_tick(policy) if policy is not None else hold()
        if not (has_generation and has_timeout):
            return hold()
        generation, duration = args['scheduler_generation'], args['operation_timeout']
        if not hex64(generation) or type(duration) not in (int, float) or not 0 < duration <= 40 or not math.isfinite(duration):
            return hold()
        policy = read_policy()
        if policy is None or not hmac.compare_digest(generation, policy['generation']):
            return hold()
        original_args = args.copy()
        del original_args['scheduler_generation']
        del original_args['operation_timeout']
        return delegate(original_args, kit, duration)
    except Exception:
        return hold()
