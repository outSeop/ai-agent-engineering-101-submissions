"""Refund, restart, authoritative evidence and concurrency regression tests."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import patch

import dispatcher as shop
from fixture import BUYER, COIN, MOCK_SKU, Fixture
import refund_admin


class Contract(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="r4-contract-")
        self.addCleanup(self.temp.cleanup)
        self.f = Fixture(Path(self.temp.name))

    def call(self, text, **args):
        return self.f.call(dict(args, text=text))

    def buy(self, unit, owner=None):
        self.f.add_unit(unit)
        out = self.call(f"구매 {MOCK_SKU}" + (f" 권리 {owner}" if owner else ""))
        self.assertIn("checkout_jwt", out.get("data", {}), out)
        return out

    def settled(self, output):
        data = self.f.settle(output)
        self.assertTrue(self.f.sync()["current"])
        return data

    def request(self, sale, owner):
        return self.call(f"환불 {sale['tx_hash']} 권리 {owner}")

    def refund(self, sale, owner, pay=None):
        if not pay:
            pay = self.f.pay
        self.assertIn("검토를 접수", self.request(sale, owner)["reply"])
        with self.f.patches():
            db = self.f.open()
            try:
                record = refund_admin.list_requests(db)[0]
                return refund_admin.send(db, self.f.market(), record["sale_id"], pay, self.f.now)
            finally:
                db.close()

    def test_payment_without_delivery_waits_for_proven_removal_and_checks_costs(self):
        first = self.buy("u-1")
        owner = self.f.right(first)
        payment, fee = self.f.payments(first["data"]["checkout_jwt"])
        self.assertIn("정산과 인도를 확인", self.call(f"결제확인 {payment} 권리 {owner}")["reply"])
        command = f"환불 {payment} 권리 {owner} 수수료 {fee}"
        self.assertIn("아직 인도", self.call(command)["reply"])
        # Inventory omission without durable market evidence is insufficient.
        unit = self.f.units.pop()
        self.assertIn("아직 인도", self.call(command)["reply"])
        self.f.expire(unit)
        self.f.receipts[fee]["effectiveGasPrice"] = hex(10**30)
        self.assertIn("검토를 접수", self.call(command)["reply"])
        with self.f.patches():
            db = self.f.open()
            try:
                claim = refund_admin.list_requests(db)[0]
                self.assertEqual(claim["reason"], "paid_no_delivery")
                self.assertEqual(int(claim["fee_wei"]), 90 * COIN)
                self.assertEqual(int(claim["gas_wei"]), 420 * COIN)
                self.assertEqual(int(claim["wei"]), (4500 + 45 - 210 + 420) * COIN)
                self.assertEqual(refund_admin.send(db, self.f.market(), claim["sale_id"], self.f.pay, self.f.now)["status"],
                                 "refunded")
                self.assertEqual(db.execute("SELECT count(*) FROM lot").fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT status FROM sale").fetchone()[0], "refunded")
            finally:
                db.close()

    def test_uncertain_transfer_survives_process_restart_without_second_send(self):
        first = self.buy("u-1")
        owner = self.f.right(first)
        sold = self.settled(first)
        self.f.advance(3600)
        self.f.breakage(sold)

        def did_send_lost_response(*args):
            self.f.pay(*args)
            raise TimeoutError("mock receipting timeout")

        result = self.refund(sold, owner, did_send_lost_response)
        self.assertEqual(result["status"], "pending_unknown")
        self.assertEqual(self.f.sends, 1)
        with self.f.patches():
            db = self.f.open()
            try:
                req = refund_admin.list_requests(db)[0]
                sale_id = req["sale_id"]
                with self.assertRaises(shop.Unavailable):
                    refund_admin.send(db, self.f.market(), sale_id, self.f.pay, self.f.now)
                invalid = self.f.transfer(self.f.kit.address("shop"), "0x" + "b"*40, int(req["wei"]), req["marker"])
                self.assertEqual(refund_admin.confirm(db, self.f.market(), sale_id, invalid, self.f.now)["status"],
                                 "pending_unknown")
                self.assertEqual(db.execute("SELECT status FROM sale").fetchone()[0], "settled")
                result = refund_admin.recover(db, self.f.market(), sale_id, self.f.now)
                self.assertEqual(result["status"], "refunded")
                self.assertEqual(refund_admin.recover(db, self.f.market(), sale_id, self.f.now), result)
            finally:
                db.close()
        self.assertEqual(self.f.sends, 1)

    def test_order_of_source_and_usage_refund_never_creates_free_points(self):
        for reverse_order in (False, True):
            with self.subTest(reverse_order=reverse_order), TemporaryDirectory() as temp:
                self.f = Fixture(Path(temp))
                first = self.buy("u-1")
                owner = self.f.right(first)
                a = self.settled(first)
                b = self.settled(self.buy("u-2", owner))
                self.f.advance(3600)
                self.f.breakage(a)
                self.f.breakage(b)
                start, end = (b, a) if reverse_order else (a, b)
                self.assertEqual(self.refund(start, owner)["status"], "refunded")
                self.assertIn("45 credits" if reverse_order else "0 credits", self.call("잔액 권리 " + owner)["reply"])
                self.assertEqual(self.refund(end, owner)["status"], "refunded")
                self.assertIn("0 credits", self.call("잔액 권리 " + owner)["reply"])
                db = self.f.open()
                try:
                    self.assertEqual(db.execute("SELECT count(*) FROM lot WHERE revoked IS NOT NULL").fetchone()[0], 2)
                    self.assertEqual(db.execute("SELECT count(*) FROM refund WHERE status='refunded'").fetchone()[0], 2)
                    self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
                finally:
                    db.close()

    def test_concurrent_refund_approval_claims_transfer_once(self):
        purchase = self.buy("u-1")
        owner = self.f.right(purchase)
        sale = self.settled(purchase)
        self.f.advance(3600)
        self.f.breakage(sale)
        self.assertIn("검토를 접수", self.request(sale, owner)["reply"])
        with self.f.patches():
            def attempt(_):
                connection = self.f.open()
                try:
                    pending = refund_admin.list_requests(connection)
                    if not pending:
                        return False
                    return refund_admin.send(connection, self.f.market(), pending[0]["sale_id"], self.f.pay, self.f.now)["status"]
                except shop.Unavailable:
                    return False
                finally:
                    connection.close()
            with ThreadPoolExecutor(max_workers=6) as executor:
                answers = list(executor.map(attempt, range(6)))
        self.assertEqual(answers.count("refunded"), 1)
        self.assertEqual(self.f.sends, 1)

    def test_ordinary_settlement_and_48h_boundary(self):
        purchase = self.buy("u-1")
        owner = self.f.right(purchase)
        sale = self.settled(purchase)
        self.assertIn("확인하지", self.request(sale, owner)["reply"])
        self.f.advance(48 * 3600 + 1)
        self.f.breakage(sale, hours=48.0)
        self.assertIn("확인하지", self.request(sale, owner)["reply"])
        self.assertEqual(self.f.sends, 0)
        # A precisely observed break at 48 hours is within the promised window.
        with TemporaryDirectory() as temp:
            self.f = Fixture(Path(temp))
            purchase = self.buy("u-2")
            owner = self.f.right(purchase)
            sale = self.settled(purchase)
            self.f.advance(48 * 3600)
            self.f.breakage(sale, hours=48.0)
            self.assertIn("검토를 접수", self.request(sale, owner)["reply"])

    def test_expiry_releases_held_miles_but_timeout_and_cancel_alone_do_not(self):
        first = self.buy("u-1")
        owner = self.f.right(first)
        self.settled(first)
        second = self.buy("u-2", owner)
        self.assertEqual(second["data"]["price"], 4455)
        self.call(f"취소 {MOCK_SKU} 권리 {owner}")
        self.f.advance(600)
        self.assertIn("0 credits", self.call("잔액 권리 " + owner)["reply"])
        self.assertNotIn("checkout_jwt", self.call(f"구매 {MOCK_SKU}").get("data", {}))
        self.f.expire(self.f.units[0])
        self.assertTrue(self.f.sync()["current"])
        self.assertIn("45 credits", self.call("잔액 권리 " + owner)["reply"])
        self.f.advance(shop.WEEK - 600)
        self.assertIn("0 credits", self.call("잔액 권리 " + owner)["reply"])

    def test_tampered_hash_chain_and_wrong_payment_receipt_do_not_earn(self):
        purchase = self.buy("u-1")
        owner = self.f.right(purchase)
        settlement = self.f.settle(purchase)
        correct = settlement["amount"]
        settlement["amount"] = correct - 1
        self.assertEqual(self.call("잔액 권리 " + owner)["reply"], shop.BUSY)
        settlement["amount"] = correct
        original = self.f.receipts[settlement["tx_hash"]]["status"]
        self.f.receipts[settlement["tx_hash"]]["status"] = "0x0"
        self.assertFalse(self.f.sync()["current"])
        self.f.receipts[settlement["tx_hash"]]["status"] = original
        self.assertTrue(self.f.sync()["current"])
        self.assertIn("45 credits", self.call("잔액 권리 " + owner)["reply"])

    def test_operator_permission_cannot_be_smuggled_over_a2a_and_wallet_is_pinned(self):
        a = self.buy("u-1")
        owner = self.f.right(a)
        self.assertEqual(shop.HELP, self.call("", data={"op": "send", "rights": owner}, op="approve-and-send")["reply"])
        self.assertEqual(self.f.sends, 0)
        with self.assertRaises(shop.Unavailable):
            shop.open_db(self.f.db_path, BUYER)
        with patch.object(self.f.kit, "name", "another-shop"):
            self.assertEqual(self.call("잔액 권리 " + owner)["reply"], shop.BUSY)

    def test_price_floor_and_invalid_numbers(self):
        self.f.add_unit("u-1", price=4500, cost=4490)
        self.assertNotIn("checkout_jwt", self.call(f"구매 {MOCK_SKU}").get("data", {}))
        self.f.units[0]["cost"] = True
        self.assertEqual(self.call(f"구매 {MOCK_SKU}")["reply"], shop.BUSY)
        with self.assertRaises(shop.Unavailable):
            shop.whole(-100)


if __name__ == "__main__":
    main(verbosity=2)

