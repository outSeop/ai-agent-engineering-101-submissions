"""Independent immutable legacy refund proof QA; all chain evidence is synthetic."""
from base64 import urlsafe_b64encode
from contextlib import closing
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from unittest import TestCase, main
from unittest.mock import patch

from eth_account import Account
from legacy_refund_fixture import existing_refund_case

ROOT = Path(os.environ["R4_QA_REFUND_TOOLS"]).resolve(strict=True)
KIT = Path(os.environ["R4_QA_OFFICIAL_KIT"]).resolve(strict=True)
sys.path.insert(0, str(KIT))
import market_kit
import maroo


def load(label):
    directory = ROOT / f"refund_{label}_proof"
    manifest = json.loads((directory / "forge.json").read_text())
    if (manifest["tool"], manifest["version"]) != (directory.name, 1):
        raise AssertionError("unexpected candidate")
    for filename, expected in manifest["sha256"].items():
        if sha256((directory / filename).read_bytes()).hexdigest() != expected:
            raise AssertionError("forge hash mismatch")
    source = directory / "logic.py"
    scope = {}
    exec(compile(source.read_bytes(), str(source), "exec"), scope)
    return scope


def encode(value):
    return urlsafe_b64encode(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).decode().rstrip("=")


class Proofs(TestCase):
    def test_official_checkout_signer_and_encoding(self):
        helper = load("checkout")
        with existing_refund_case() as (fixture, case):
            sale_id = case["claim"]["sale_id"]
            payload = fixture.payload(case["checkout"]["data"]["checkout_jwt"])
            handle = maroo.Wallet.from_hex(fixture.kit.key.key.hex())
            authentic = market_kit.jwt_sign(handle, payload)
            other = maroo.Wallet.from_hex(Account.create().key.hex())
            header, data, sig = authentic.split(".")
            variants = {
                "authentic": (authentic, "verified"),
                "wrong_signer": (market_kit.jwt_sign(other, payload), "unverified"),
                "tampered_payload": (header + "." + encode(dict(payload, price=1)) + "." + sig, "unverified"),
                "wrong_alg": (encode({"alg":"none","typ":"JWT"}) + "." + data + "." + sig, "unverified"),
                "malformed_b64": (header + "." + data + "=." + sig, "unverified"),
                "wrong_signature_length": (header + "." + data + ".AA", "unverified"),
            }
            helper["DB"] = str(fixture.db_path)
            for label, (jwt, status) in variants.items():
                with self.subTest(label=label), closing(fixture.open()) as db:
                    db.execute("UPDATE sale SET jwt=?,digest=? WHERE id=?", (jwt, sha256(jwt.encode()).hexdigest(), sale_id))
                    self.assertEqual(helper["run"]({"sale_id": sale_id}, fixture.kit)["status"], status)
            self.assertEqual(fixture.sends, 0)

    def test_payment_and_receipt_helpers_use_legacy_rows_without_disclosing_values(self):
        payment, receipt = load("payment"), load("receipt")
        with existing_refund_case() as (fixture, case):
            claim = case["claim"]
            sale_id = claim["sale_id"]
            seller = fixture.kit.address("shop").lower()
            outgoing = fixture.transfer(seller, claim["payer"], int(claim["wei"]), claim["marker"])
            for tx in (claim["incoming"], claim["fee_payment"], outgoing):
                row = fixture.txs[tx]
                fixture.receipts[tx].update({"from": row["from"], "to": row["to"]})
            for helper in (payment, receipt):
                helper["DB"] = str(fixture.db_path)

            def rpc(url, *, json, **kwargs):
                if json["method"] == "eth_chainId":
                    return fixture.response(url, {"jsonrpc":"2.0","id":1,"result":hex(450815)})
                if json["method"] == "eth_getBlockByNumber":
                    tx = fixture.txs[outgoing]
                    return fixture.response(url, {"jsonrpc":"2.0","id":1,"result":{
                        "hash":tx["blockHash"],"number":tx["blockNumber"],"transactions":[outgoing]}})
                return fixture.post(url, json=json, **kwargs)

            with closing(fixture.open()) as db:
                db.execute("UPDATE refund SET status='pending_unknown', outgoing=? WHERE sale_id=?", (outgoing,sale_id))
                sale = db.execute("SELECT * FROM sale WHERE id=?", (sale_id,)).fetchone()
            args = {"sale_id": sale_id}
            with patch("httpx.get", fixture.get), patch("httpx.post", rpc):
                self.assertEqual(payment["run"](args, fixture.kit), {"status":"payment_evidence_verified"})
                self.assertEqual(receipt["run"](args, fixture.kit), {"status":"refund_receipt_verified"})
                goods, fee, gas = payment["verify_payments"](sale, seller)
                self.assertEqual((goods, fee, gas), tuple(int(claim[k]) for k in ("transfer_wei","fee_wei","gas_wei")))
                original_receipt = fixture.receipts[claim["incoming"]]
                original_receipt["effectiveGasPrice"] = hex(10**30)
                self.assertEqual(payment["verify_payments"](sale, seller)[2], int(sale["gas_cap_wei"]))
                original_receipt["gasUsed"] = "0x0001"
                self.assertEqual(payment["run"](args, fixture.kit)["reason"], "invalid_rpc_quantity")
                fixture.receipts[outgoing]["to"] = "0x" + "a"*40
                self.assertEqual(receipt["run"](args, fixture.kit)["status"], "unverified")
            with closing(fixture.open()) as db:
                self.assertEqual(db.execute("SELECT status FROM refund").fetchone()[0], "pending_unknown")
            self.assertEqual(fixture.sends, 0)


if __name__ == "__main__":
    main()

