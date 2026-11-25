"""Verify public shop evidence and construct the native notice approval input."""
from hashlib import sha256
import math
import re
from urllib.parse import urlsplit

NAME="outseop-r4"
WALLET="0x5fdc134d790efb72df1bbb922f2b49fcade349c6"
CARD_SUFFIX="/.well-known/agent-card.json"
FINGERPRINT=re.compile(r"[a-zA-Z0-9_:.-]{16,256}\Z")


def wallet_matches(value):
    return isinstance(value,str) and value.lower()==WALLET


def checked_base(url):
    if not isinstance(url,str) or any(ch.isspace() for ch in url):
        raise ValueError("untrusted public Card base")
    parts=urlsplit(url)
    if (parts.scheme!="https" or not parts.hostname or parts.username or parts.password
            or parts.query or parts.fragment or parts.path not in ("","/") or parts.port not in (None,443)):
        raise ValueError("untrusted public Card base")
    return url.rstrip("/")


def named(data,key):
    if (not isinstance(data,dict) or type(data.get("round")) is not int or data["round"]!=4
            or not isinstance(data.get(key),list)):
        raise ValueError("unexpected public round or registry data")
    rows=[row for row in data[key] if isinstance(row,dict) and row.get("name")==NAME]
    if len(rows)!=1:
        raise ValueError("unexpected registered shop cardinality")
    return rows[0]


def public_observation(*,local_card,public_card,shops,agents,observed_at,valid_until,policy_bytes,
                        reviewed_fingerprint=None):
    if (type(observed_at) not in (int,float) or type(valid_until) not in (int,float)
            or not math.isfinite(observed_at) or not math.isfinite(valid_until)
            or not 0<valid_until-observed_at<=150):
        raise ValueError("unsafe notice attestation time span")
    if (reviewed_fingerprint is not None
            and (not isinstance(reviewed_fingerprint,str) or not FINGERPRINT.fullmatch(reviewed_fingerprint))):
        raise ValueError("unreviewed notice approval fingerprint")
    if not isinstance(policy_bytes,bytes) or not 0<len(policy_bytes)<=4096:
        raise ValueError("unreviewed notice policy bytes")
    shop=named(shops,"shops")
    agent=named(agents,"agents")
    base=checked_base(shop.get("url"))
    expected_card=base+CARD_SUFFIX
    if (shop.get("url")!=base or not wallet_matches(shop.get("pubkey"))
            or not isinstance(agent.get("roles"),list) or "shop" not in agent["roles"]
            or agent.get("card")!=expected_card):
        raise ValueError("registry mismatch")
    for card in (local_card,public_card):
        if not isinstance(card,dict) or card.get("name")!=NAME or card.get("roles")!=["shop"]:
            raise ValueError("Card shop fields differ")
        wallets=card.get("wallets")
        if not isinstance(wallets,dict) or not wallet_matches(wallets.get("shop")):
            raise ValueError("Card wallet mismatch")
        interfaces=card.get("supportedInterfaces")
        expected={"protocolBinding":"JSONRPC","protocolVersion":"1.0"}
        if (not isinstance(interfaces,list) or len(interfaces)!=1 or not isinstance(interfaces[0],dict)
                or checked_base(interfaces[0].get("url"))!=base
                or any(interfaces[0].get(key)!=value for key,value in expected.items())):
            raise ValueError("Card interface mismatch")
    return {"shop":NAME,"round":4,"wallet":WALLET,"shop_url":base,"card_url":expected_card,
            "observed_at":observed_at,"valid_until":valid_until,
            "policy_sha256":sha256(policy_bytes).hexdigest(),"approved_fingerprint":reviewed_fingerprint}

