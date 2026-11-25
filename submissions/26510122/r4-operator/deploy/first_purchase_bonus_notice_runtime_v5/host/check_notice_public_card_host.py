"""Read only the public Card and market registry, without signer or tokens."""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from time import time
from urllib.parse import urlsplit

import httpx
from first_purchase_bonus_notice_approval_host import CARD_SUFFIX, checked_base, named, public_observation

MARKET="https://market.ourolabs.ai"
LOCAL="http://127.0.0.1:18805/.well-known/agent-card.json"


def observe(read,policy_bytes):
    began=time()
    local=read(LOCAL)
    shops=read(MARKET+"/api/shops")
    agents=read(MARKET+"/api/agents")
    base=checked_base(named(shops,"shops")["url"])
    host=urlsplit(base).hostname
    if host!=urlsplit(MARKET).hostname and not host.endswith(".trycloudflare.com"):
        raise ValueError("public Card host outside the reviewed routes")
    public=read(base+CARD_SUFFIX)
    current=time()
    if not 0<=current-began<30:
        raise ValueError("public Card observations took too long")
    return public_observation(local_card=local,public_card=public,shops=shops,agents=agents,
                              observed_at=began,valid_until=began+150,policy_bytes=policy_bytes)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy",type=Path,required=True,help="already approved bonus policy file")
    args=parser.parse_args()
    with httpx.Client(timeout=6.0,follow_redirects=False,trust_env=False) as client:
        def read(url):
            try:
                response=client.get(url)
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError,ValueError) as exc:
                raise ValueError("public Card/registry observation failed at "+str(urlsplit(url).hostname)) from exc
        facts=observe(read,args.policy.read_bytes())
    print(json.dumps({"local_public_card_registry_match":True,"public_card_url_sha256":sha256(facts["card_url"].encode()).hexdigest(),
                      "policy_sha256":facts["policy_sha256"],
                      "observed_at_utc":datetime.fromtimestamp(facts["observed_at"],timezone.utc).isoformat(),
                      "approval_written":False,"posted":False}))


if __name__=="__main__":
    main()

