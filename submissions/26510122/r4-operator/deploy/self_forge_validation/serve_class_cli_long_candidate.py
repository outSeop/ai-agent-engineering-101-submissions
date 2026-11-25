"""Configure the unmodified official cli_model adapter for long development replies."""
import argparse
from pathlib import Path
import sys


def serve(kit, command, timeout=310):
    if timeout not in (310, 610):
        raise ValueError("unsupported adapter deadline")
    sys.path.insert(0, str(kit.resolve(strict=True)))
    import cli_model

    cli_model.TIMEOUT = timeout
    sys.argv = [str(kit / "cli_model.py"), "--cmd", command, "--port", "19001"]
    cli_model.main()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kit", type=Path, required=True)
    parser.add_argument("--cmd", required=True, help="reviewed Windows Python bridge command")
    parser.add_argument("--timeout-seconds", type=int, choices=(310,610), default=310)
    args = parser.parse_args()
    serve(args.kit,args.cmd,args.timeout_seconds)

