"""Strictly bounded launch pricing and defensible grade-C clearance."""
import json
from pathlib import Path
import re

POLICY_PATH=Path("codex-r4/launch-price-policy.json")
MAX_BUDGET=50_000
MAX_DEAL_BPS=500
MAX_LIFETIME=14*86400
C_MARGIN_BPS=200
LAUNCH_MARGIN_BPS=500
SCHEMA="""
CREATE TABLE IF NOT EXISTS promotion_loss (
    sale_id TEXT PRIMARY KEY REFERENCES sale(id), policy_id TEXT NOT NULL,
    reserved INTEGER NOT NULL CHECK(reserved>0), amount INTEGER NOT NULL CHECK(amount>=0),
    state TEXT NOT NULL CHECK(state IN ('reserved','settled','refunded')), at REAL NOT NULL
);
"""


def current(now):
    """Absent or malformed configuration closes promotional-loss pricing."""
    try:
        with POLICY_PATH.open(encoding="utf-8") as source:
            row=json.loads(source.read(4097))
    except (ValueError,OSError):
        return None
    if (not isinstance(row,dict) or set(row)!={"policy_id","starts_at","ends_at","total_loss_credits","per_deal_bps"}
            or not isinstance(row["policy_id"],str) or not re.fullmatch("[a-z0-9_-]{1,48}",row["policy_id"])):
        return None
    start,end,budget,bps=(row[k] for k in ("starts_at","ends_at","total_loss_credits","per_deal_bps"))
    if (any(type(v) is not int for v in (start,end,budget,bps))
            or not 0<end-start<=MAX_LIFETIME or not start<=now<end
            or not 0<budget<=MAX_BUDGET or not 0<bps<=MAX_DEAL_BPS):
        return None
    return row


def room(db, policy):
    if not policy:
        return 0
    # A changed configuration name cannot reset the same launch loss wallet.
    used=db.execute("SELECT coalesce(sum(amount),0) FROM promotion_loss").fetchone()[0]
    return max(0,policy["total_loss_credits"]-used)


def per_deal(cost, budget, policy):
    return min(budget,cost*policy["per_deal_bps"]//10000) if policy else 0


def fee(price, bps, network):
    return price*bps//10000+network//2


def loss(cost, base, price, bps, network):
    return max(0,cost+network//2+base//100-(price-fee(price,bps,network)))


def preferred(reference, healthy_floor, cost, grade, launch):
    """One public gross price. A fixed benefit buffer is independent of identity."""
    if grade != "C" and not launch:
        return reference
    bps = C_MARGIN_BPS if grade=="C" else LAUNCH_MARGIN_BPS
    return min(reference,healthy_floor+cost*bps//10_000+healthy_floor*2//100)


def reserve(db, sale_id, policy, amount, now):
    db.execute("INSERT INTO promotion_loss VALUES(?,?,?,?,'reserved',?)",
               (sale_id,policy["policy_id"],amount,amount,now))


def resolve(db, sale_id, state, computed=None):
    if state=="settled":
        # The bank-verified payment implies the signed amount. Never grant
        # extra budget if newer policy assumptions differ from that contract.
        db.execute("""UPDATE promotion_loss SET amount=max(reserved,coalesce(?,reserved)),state='settled'
                      WHERE sale_id=? AND state='reserved'""",(computed,sale_id))
    else:
        # Refund review cannot restore exhausted promotional headroom.
        db.execute("UPDATE promotion_loss SET state='refunded' WHERE sale_id=?",(sale_id,))

