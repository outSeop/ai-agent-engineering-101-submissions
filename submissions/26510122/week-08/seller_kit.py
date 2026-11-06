"""Load the shared official kit read-only and attach supply observability."""
import importlib.util
from pathlib import Path
import sys
from procurement_transport import instrument


def main():
    path=Path(sys.argv[1]).resolve();sys.argv.pop(1)
    spec=importlib.util.spec_from_file_location('observed_official_market_kit',path)
    kit=importlib.util.module_from_spec(spec);sys.modules[spec.name]=kit
    spec.loader.exec_module(kit)
    instrument(kit);kit.main()


if __name__=='__main__':main()
