from contextvars import ContextVar
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
import re
from threading import RLock
from types import FunctionType, ModuleType

V11 = ('codex-r4/forum_marketing11.py', 'd4297f458ea0bcbc98c18a621ded5c834d191323e25f34f3361212dd3f9942ed')
V10 = ('codex-r4/forum_marketing10.py', 'bd80f8236c415ffc962b5b651f24232e8e34320a621145954abbbf0bedca073a')
V9 = ('codex-r4/forum_marketing9.py', 'b2edc8dba8c214a22074eb1f3db35ce5eb8234f444cf22710f025078b64e48e9')
CACHE_LIMIT = 8192
COMPILER = ContextVar('forum_marketing_v12_compiler', default=None)
LOCK = RLock()
OWNER = None


def load_verified11():
    path, digest = V11
    source = Path(path).read_bytes()
    if sha256(source).hexdigest() != digest:
        raise ValueError('v11 publisher digest mismatch')
    module = ModuleType('_outseop_r4_forum_marketing_v11')
    module.__file__ = path
    exec(compile(source, path, 'exec'), module.__dict__)
    if module.V10 != V10 or module.V9 != V9:
        raise ValueError('publisher lineage mismatch')
    return module


def new_compiler(compiler=re.compile, maxsize=CACHE_LIMIT):
    return lru_cache(maxsize=maxsize, typed=True)(compiler)


class ClassifierRegex:
    def __getattr__(self, name):
        return getattr(re, name)

    def compile(self, pattern, flags=0):
        compiler = COMPILER.get()
        if compiler is not None and type(pattern) is str and type(flags) in (int, re.RegexFlag):
            return compiler(pattern, flags)
        return re.compile(pattern, flags)

    def subn(self, pattern, repl, string, count=0, flags=0):
        compiler = COMPILER.get()
        if compiler is not None and type(pattern) is str and type(flags) in (int, re.RegexFlag):
            return compiler(pattern, flags).subn(repl, string, count)
        return re.subn(pattern, repl, string, count=count, flags=flags)


def optimize_classifier(module):
    original = module.classify
    namespace = dict(original.__globals__, re=ClassifierRegex())
    module.classify = FunctionType(original.__code__, namespace, original.__name__, original.__defaults__, original.__closure__)
    return module


def run(args, kit):
    global OWNER
    compiler = new_compiler()
    scope = COMPILER.set(compiler)
    try:
        with LOCK:
            if OWNER is None:
                OWNER = optimize_classifier(load_verified11())
            owner = OWNER
        return owner.run(args, kit)
    except Exception:
        return {'status': 'hold'}
    finally:
        COMPILER.reset(scope)
        compiler.cache_clear()
