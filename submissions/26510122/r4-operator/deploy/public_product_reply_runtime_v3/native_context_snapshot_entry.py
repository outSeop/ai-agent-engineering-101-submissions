"""Separate read-only producer for a fresh representative customer-offer cache."""
import argparse
import json
import os
from pathlib import Path
import sys
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operator",type=Path,required=True)
    parser.add_argument("--manifest-sha256",required=True)
    parser.add_argument("--publish-cache",action="store_true")
    args=parser.parse_args()
    operator=args.operator.resolve(strict=True)
    freeze=Path(__file__).resolve().parent
    sys.path[:0]=[str(freeze),str(operator/"kit")]
    from native_context_runtime import atomic,verified_freeze
    verified_freeze(freeze,args.manifest_sha256)
    from card_offer_producer_host import acquire
    from customer_offer_mind_canary import make_context
    started=time.monotonic()
    registered,observed,offers,catalog=acquire(operator.parent/"round-4")
    document=make_context(offers,catalog,observed)
    raw=json.dumps(document,ensure_ascii=False,separators=(",",":"),allow_nan=False).encode()
    if len(raw)>512*1024 or time.time()>=document["valid_until"]:
        raise ValueError("offer producer cache unavailable")
    if args.publish_cache:
        from card_source_read_lane import safe_directory
        os.umask(0o077)
        target=operator/"runtime/native-customer-context"
        target.mkdir(mode=0o700,exist_ok=True)
        safe_directory(target)
        scratch=target/"scratch"
        scratch.mkdir(mode=0o700,exist_ok=True)
        safe_directory(scratch)
        atomic(target/"latest.json",raw)
    return {"status":"cached" if args.publish_cache else "prepared_only",
            "representative_count":len(document["units"]),"elapsed_seconds":round(time.monotonic()-started,3)}


if __name__=="__main__":
    print(json.dumps(main()))

