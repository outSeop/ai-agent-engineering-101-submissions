"""Customer profile tests with the same dispatcher, actual ledger, and transport fixture."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main

import dispatcher as shop
from fixture import BUYER, MOCK_SKU, Fixture
import profile_admin
import refund_admin


class CustomerProfile(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="r4-profile-")
        self.addCleanup(self.temp.cleanup)
        self.f = Fixture(Path(self.temp.name))

    def call(self, text, **args):
        return self.f.call(dict(args, text=text))

    def buy(self, unit_id, *, owner=None, category="kitchen", price=4500, task=None):
        unit = self.f.add_unit(unit_id, price=price)
        unit["category"] = category
        request = f"구매 {MOCK_SKU}" + (f" 권리 {owner}" if owner else "")
        out = self.call(request, claimed_from="same-claimed-persona", task_id=task)
        self.assertIn("checkout_jwt", out.get("data", {}), out)
        return out

    def find(self, code):
        db = self.f.open()
        try:
            row = shop.one(db, "SELECT profile_id FROM customer_profile WHERE owner=?", shop.key_of(code))
            return row["profile_id"]
        finally:
            db.close()

    def display(self, profile_id):
        db = self.f.open()
        try:
            return profile_admin.profile(db, profile_id, self.f.now)
        finally:
            db.close()

    def test_30_minute_gap_and_duplicate_transport_do_not_inflate_visits(self):
        q = self.buy("u-1", task="original")
        code = self.f.right(q)
        profile_id = self.find(code)
        self.assertEqual(self.display(profile_id)["visits"]["visits"], 1)
        self.f.advance(1799)
        for _ in range(3):
            self.call(f"잔액 권리 {code}", task_id="dup")
        self.assertEqual(self.display(profile_id)["visits"]["visits"], 1)
        self.f.advance(1799)
        self.call(f"잔액 권리 {code}", task_id="dup")
        self.assertEqual(self.display(profile_id)["visits"]["visits"], 1)
        self.f.advance(1)
        self.call(f"잔액 권리 {code}", task_id="dup")
        self.assertEqual(self.display(profile_id)["visits"]["visits"], 2)
        self.call(f"잔액 권리 {code}", task_id="different-in-same-session")
        visits = self.display(profile_id)["visits"]
        self.assertEqual(visits["visits"], 2)
        self.assertEqual(visits["definition"], "authenticated_contact_sessions")
        self.call(f"잔액 권리 {'a'*43}", claimed_from="same-claimed-persona", task_id="new")
        self.assertEqual(self.display(profile_id)["visits"]["visits"], 2)

    def test_same_market_buyer_and_wallet_do_not_merge_rights_or_infer_income(self):
        a = self.buy("u-1", price=200000)
        b = self.buy("u-2")
        code_a, code_b = self.f.right(a), self.f.right(b)
        sale_a = self.f.settle(a, buyer=BUYER)
        self.f.settle(b, buyer=BUYER)
        self.assertTrue(self.f.sync()["current"])
        id_a, id_b = self.find(code_a), self.find(code_b)
        self.assertNotEqual(id_a, id_b)
        av, bv = self.display(id_a), self.display(id_b)
        self.assertEqual(av["mileage"]["available"], 2000)
        self.assertEqual(bv["mileage"]["available"], 45)
        for view in av, bv:
            self.assertEqual(view["self_reported"]["income_bracket"]["confidence"], "unknown")
            self.assertIsNone(view["self_reported"]["income_bracket"]["value"])
            link = view["market_buyer_links"][0]
            self.assertEqual(link["market_buyer"], "fixture-buyer")
            self.assertEqual(link["payment_wallet"], BUYER)
            self.assertEqual(link["source"], "market_ledger_and_rpc")
        self.assertIn("확인할 수 없습니다", self.call(f"결제확인 {sale_a['tx_hash']} 권리 {code_b}",
                                                    claimed_from="fixture-buyer")["reply"])
        self.assertIn("확인할 수 없습니다", self.call(f"잔액 권리 {id_a}")["reply"])

    def test_family_income_preferences_and_tombstones_keep_structured_provenance(self):
        q = self.buy("u-1")
        code = self.f.right(q)
        ident = self.find(code)
        for text in ("가족 자녀 2", "가구 4", "소득 quintile 3", f"선호 sku {MOCK_SKU} 좋아함",
                     "선호 category 생활용품 피함"):
            self.assertIn("기록했습니다", self.call(f"프로필 {text} 권리 {code}")["reply"])
        self.assertIn("확인할 수 없습니다", self.call(f"프로필 가족 자녀 김예시 권리 {code}")["reply"])
        self.assertIn("확인할 수 없습니다", self.call(f"프로필 소득 9 권리 {code}")["reply"])
        stored = self.display(ident)["self_reported"]
        self.assertEqual(stored["income_bracket"]["value"], {"scale": "quintile", "band": 3})
        self.assertEqual(stored["family"][0]["value"], {"relation": "child", "count": 2})
        self.assertEqual(stored["household_size"]["source"], "customer_a2a_self_report")
        self.assertEqual(len(stored["preferences"]), 2)
        self.assertIn("기록했습니다", self.call(f"프로필 가족 자녀 1 권리 {code}")["reply"])
        self.assertIn("기록했습니다", self.call(f"프로필 삭제 소득 권리 {code}")["reply"])
        self.assertNotIn(code, self.f.db_path.read_bytes().decode("utf-8", "ignore"))
        db = self.f.open()
        try:
            events = profile_admin.facts(db, ident, history=True)
            self.assertEqual([e["value"]["count"] for e in events if e["field"] == "family"], [2, 1])
            self.assertTrue(events[-1]["discarded"])
            self.assertNotIn(code, json.dumps(events))
            self.assertNotIn("김예시", json.dumps(events, ensure_ascii=False))
        finally:
            db.close()
        self.assertEqual(self.display(ident)["self_reported"]["income_bracket"]["confidence"], "unknown")

    def test_operator_intake_is_idempotent_strict_and_never_updates_ledger(self):
        ident = self.find(self.f.right(self.buy("u-1")))
        data = {"profile_id": ident, "facts": [{"type": "family", "relation": "parent", "count": 1},
                                             {"type": "income_bracket", "scale": "decile", "band": 9}]}
        db = self.f.open()
        try:
            self.assertEqual(profile_admin.ingest(db, data, self.f.now)["recorded"], 2)
            self.assertEqual(profile_admin.ingest(db, data, self.f.now)["recorded"], 0)
            invalid = {"profile_id": ident, "facts": [{"type": "family", "relation": "child", "count": 1,
                                                       "child_name": "never store"}]}
            with self.assertRaises(shop.Unavailable):
                profile_admin.ingest(db, invalid, self.f.now)
            with self.assertRaises(shop.Unavailable):
                profile_admin.ingest(db, {"profile_id": ident, "facts": [{"type": "income_bracket", "band": 8}]}, self.f.now)
            rows = profile_admin.facts(db, ident, history=True)
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(row["source"] == "operator_recorded_self_report" for row in rows))
            self.assertEqual(db.execute("SELECT count(*) FROM lot").fetchone()[0], 0)
        finally:
            db.close()

    def test_purchase_preference_and_mileage_projection_tracks_real_state_changes(self):
        a = self.buy("u-1")
        owner = self.f.right(a)
        view = self.display(self.find(owner))
        self.assertEqual(view["purchases"], {"by_sku": [], "by_category": []})
        self.assertEqual(view["mileage"]["available"], 0)
        first = self.f.settle(a)
        self.assertTrue(self.f.sync()["current"])
        b = self.buy("u-2", owner=owner, category="생활용품")
        self.assertEqual(self.display(self.find(owner))["mileage"]["reserved"], 45)
        self.f.settle(b)
        self.f.advance(3600)
        self.f.breakage(first)
        self.assertTrue(self.f.sync()["current"])
        before = self.display(self.find(owner))
        self.assertEqual(before["purchases"]["by_sku"][0], {"item": MOCK_SKU, "settled": 2, "refunded": 0,
                                                          "broken": 1, "retained": 1})
        self.assertEqual(before["purchases"]["by_category"][0]["item"], "household")
        self.assertIn("검토를 접수", self.call(f"환불 {first['tx_hash']} 권리 {owner}")["reply"])
        with self.f.patches():
            db = self.f.open()
            try:
                req, = refund_admin.list_requests(db)
                self.assertEqual(refund_admin.send(db, self.f.market(), req["sale_id"], self.f.pay, self.f.now)["status"],
                                 "refunded")
            finally:
                db.close()
        after = self.display(self.find(owner))
        self.assertEqual(after["purchases"]["by_sku"][0]["refunded"], 1)
        self.assertEqual(after["mileage"]["available"], 0)
        self.assertEqual(after["self_reported"]["preferences"], [])

    def test_additive_backfill_assigns_profile_id_to_older_account_without_inventing_visits(self):
        older_key = shop.key_of("z" * 43)
        db = self.f.open()
        try:
            db.execute("INSERT INTO account VALUES(?,?)", (older_key, self.f.now - 86400))
            profile_admin.ensure_profiles(db)
            first, = profile_admin.profile_rows(db)
            profile_admin.ensure_profiles(db)
            self.assertEqual(profile_admin.profile_rows(db), [first])
            view = profile_admin.profile(db, first["profile_id"], self.f.now)
            self.assertEqual(view["visits"]["visits"], 0)
            self.assertEqual(view["self_reported"]["family"], [])
            self.assertEqual(db.execute("SELECT key FROM account").fetchone()[0], older_key)
        finally:
            db.close()


if __name__ == "__main__":
    main(verbosity=2)

