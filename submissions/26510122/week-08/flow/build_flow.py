"""Build the editable inline flow and an optional standalone browser copy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--renderer", type=Path, help="visualize skill scripts/render.py")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    spec = json.loads((root / "flow-spec.json").read_text(encoding="utf-8"))
    template = (root / "flow-template.html").read_text(encoding="utf-8")
    payload = json.dumps(spec, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    if template.count("__FLOW_SPEC_JSON__") != 1:
        raise ValueError("expected one flow data placeholder")
    fragment = root / "agent-flow.html"
    fragment.write_text(template.replace("__FLOW_SPEC_JSON__", payload), encoding="utf-8")
    print(fragment)
    if args.renderer:
        subprocess.run([sys.executable, str(args.renderer), str(fragment),
                        str(root / "agent-flow-standalone.html"), "--force", "--title", "R3 에이전트 흐름"], check=True)


if __name__ == "__main__":
    main()
