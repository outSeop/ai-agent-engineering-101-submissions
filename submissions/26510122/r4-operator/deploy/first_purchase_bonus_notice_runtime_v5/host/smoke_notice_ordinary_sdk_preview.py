"""Use the genuine ordinary SDK preview and real public GETs with a synthetic ledger."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory

import httpx
from check_notice_public_card_host import observe


HERE=Path(__file__).resolve().parent
OP=HERE.parents[3]
SCHEMA=HERE.parent/"validation/first-purchase-bonus-notice-exact-schema.json"
NAME="first_purchase_bonus_notice"
FILES={"logic.py","test.py","permission.yml","forge.json"}


class NoWallet:
    def grant(self,name,permission,timeout):
        if (name!=NAME or any(permission.get(k) for k in ("wallet","exec","handles"))
                or permission.get("pay_limit",0)!=0 or permission.get("network")!=["market.ourolabs.ai"]
                or permission.get("identity")!=["shop"] or permission.get("write")!=["state/r4-benefits"]):
            raise ValueError("unexpected notice permissions")
        return None


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",type=Path,required=True)
    parser.add_argument("--forge-sha256",required=True)
    parser.add_argument("--policy",type=Path,required=True)
    args=parser.parse_args()
    os.umask(0o077)
    sys.path.insert(0,str(OP/"kit"))
    import agent_kit as official
    files={name:(args.source/name).read_bytes() for name in FILES}
    forge=json.loads(files["forge.json"])
    if (sha256(files["forge.json"]).hexdigest()!=args.forge_sha256 or forge.get("tool")!=NAME
            or forge.get("version")!=5
            or forge.get("sha256")!={name:sha256(files[name]).hexdigest() for name in FILES-{"forge.json"}}):
        raise ValueError("unreviewed notice package")
    policy=args.policy.read_bytes()
    with httpx.Client(timeout=6.0,follow_redirects=False,trust_env=False) as client:
        def read(url):
            response=client.get(url)
            response.raise_for_status()
            return response.json()
        facts=observe(read,policy)
    with TemporaryDirectory(prefix="r4-notice-preview-") as folder:
        root=Path(folder)
        target=root/"tools"/NAME
        target.mkdir(mode=0o700,parents=True)
        for name,body in files.items():
            (target/name).write_bytes(body)
        state=root/"state/r4-benefits"
        state.mkdir(mode=0o700,parents=True)
        records=json.loads(SCHEMA.read_bytes())
        with sqlite3.connect(state/"benefits.sqlite3") as db:
            for record in records:
                # Absence of awards before the first grant is an expected live case.
                if record["variable"]!="AWARD_SCHEMA":
                    db.executescript(record["ddl"])
            db.execute("INSERT INTO identity VALUES(1,?,?)",(facts["shop"],facts["wallet"]))
        (state/"first-purchase-bonus-policy.json").write_bytes(policy)
        (state/"first-purchase-bonus-notice-approval.json").write_text(json.dumps(facts))
        ctx={"name":facts["shop"],"market":"https://market.ourolabs.ai","shop_url":facts["shop_url"],
             "tokens":{},"addresses":{"shop":facts["wallet"]},"signer":NoWallet()}
        official.mk.LOG_FILE=None
        answer=official.Toolbox(root,ctx).run(NAME,"call",{"mode":"preview"})
        result=answer.get("result") if answer.get("ok") else None
        if not isinstance(result,dict) or result.get("status")!="preview":
            print(json.dumps({"ordinary_sdk":True,"sdk_mode":"call","synthetic_ledger":True,
                              "actual_public_gets":True,"preview":False,
                              "reason":result.get("reason") if isinstance(result,dict) else "sdk_failed","posted":False}))
            return 1
        text=result.get("text","")
        ok="정산" in text and "7일" in text and any(phrase in text for phrase in ("다음 거래","다음 구매")) and "발급일부터" not in text
        print(json.dumps({"ordinary_sdk":True,"sdk_mode":"call","synthetic_ledger":True,"actual_public_gets":True,
                          "preview":True,"lane":result.get("lane"),"expiry_wording_verified":ok,
                          "text_sha256":sha256(text.encode()).hexdigest(),"posted":False}))
        return 0 if ok else 1


if __name__=="__main__":
    raise SystemExit(main())

