"""Configure the unmodified official cli_model adapter for long development replies."""
import argparse
from pathlib import Path
import sys


def serve(kit, command):
    sys.path.insert(0, str(kit.resolve(strict=True)))
    import cli_model

    cli_model.TIMEOUT = 310
    sys.argv = [str(kit / "cli_model.py"), "--cmd", command, "--port", "19001"]
    cli_model.main()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kit", type=Path, required=True)
    parser.add_argument("--cmd", required=True, help="reviewed Windows Python bridge command")
    args = parser.parse_args()
    serve(args.kit,args.cmd)

