"""Keyless worker for the pinned official native customer context tool."""
from contextlib import redirect_stderr, redirect_stdout
import json
from pathlib import Path
import sys


def main():
    bundle,kit,scratch=(Path(value).resolve(strict=True) for value in sys.argv[1:])
    sys.path[:0]=[str(Path(__file__).resolve().parent),str(kit)]
    import agent_kit
    from native_customer_context_adapter import IsolatedNativeBuilder
    agent_kit.mk.LOG_FILE=None
    raw=sys.stdin.buffer.read(1024*1024+1)
    if len(raw)>1024*1024:
        return 2
    inputs=json.loads(raw)
    if set(inputs)!={"base","snapshot"}:
        return 2
    try:
        with open("/dev/null","w") as muted, redirect_stdout(muted), redirect_stderr(muted):
            result=IsolatedNativeBuilder(agent_kit,bundle,scratch)(inputs["base"],inputs["snapshot"])
    except Exception:
        return 2
    print(json.dumps(result,ensure_ascii=False,separators=(",",":"),allow_nan=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())

