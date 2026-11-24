"""R4 wholesale protocol fixtures with no real market or signer."""
from base64 import b64encode
from hashlib import sha256
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import patch

import httpx
from eth_account import Account
from eth_account.messages import encode_defunct

import dispatcher as sales
from fixture import Fixture, MOCK_MARKET, MOCK_SKU, COIN, MARKET_WALLET
import procurement as stock
import refund_admin
from stock_runtime import StockCoordinator


class StockFixture(Fixture):
    def __init__(self, root):
        super().__init__(root)
        self.start = self.now + 90
        self.end = self.start + 180
        self.catalog = [{"sku":MOCK_SKU,"list_price":4500,"name":"키친타올 걸이",
                         "category":"주방용품>수납","kind":"goods","shelf_hours":None}]
        self.cash = 3000000
        self.storage = 0
        self.fee = 0
        self.calls = []
        self.status_queue = []
        self.quote_override = None
        self.arrive_on_confirm = False
        self.bank = Account.create()
        self.delivered = []
        self.quoted = []

    def get(self, url, **kwargs):
        if url==MOCK_MARKET+"/api/chain":
            result=super().get(url,**kwargs).json()
            result["market_address"]=self.bank.address
            return self.response(url,result)
        if url==MOCK_MARKET+"/api/catalog":
            return self.response(url,self.catalog)
        if url==MOCK_MARKET+"/api/inventory":
            assert kwargs["headers"] == {"authorization":"Bearer fixture-test-only"}
            return self.response(url,{"round":4,"wallet":self.kit.address("shop"),"balance":self.cash,
                                     "bankrupt_line":500000,"storage_per_day":.12,"goods_lose_a_grade_every_hours":48,
                                     "storage_due_with_next_lot":self.storage,"next_dislike_fee":self.fee,
                                     "surge":[],"restock":{"open":self.start<=self.now<self.end,
                                                          "opens_at":self.start,"closes_at":self.end},
                                     "units":self.units})
        return super().get(url,**kwargs)

    def post(self, url, *, json, **kwargs):
        if url!=MOCK_MARKET+"/api/supply":
            return super().post(url,json=json,**kwargs)
        assert kwargs["headers"] == {"authorization":"Bearer fixture-test-only"}
        self.calls.append(json)
        if "quote" in json:
            status=self.status_queue.pop(0) if self.status_queue else 200
            if status!=200:
                return self.response(url,{},code=status)
            self.delivered=[]
            for unit in self.quoted:
                cert={"unit":unit["unit"],"sku":unit["sku"],"shop":"outseop-r4"}
                sig=self.bank.sign_message(encode_defunct(primitive=sales.canonical(cert))).signature
                self.delivered.append(dict(unit,cert={"cert":cert,"sig":b64encode(sig).decode()}))
            if self.arrive_on_confirm:
                self.units.extend(self.delivered)
            return self.response(url,{"units":self.delivered})
        item=next(x for x in self.catalog if x["sku"]==json["sku"])
        qid="q-1234567890abcdef"
        self.quoted = [dict(item,unit=f"u-{i+1:012x}",cost=2700,grade="A",expires_at=None)
                       for i in range(json["qty"])]
        quote={"quote":qid,"expire_in":140,"expires_in":140,"goods":2700*json["qty"],"storage":self.storage,
               "forum_fees":self.fee,"total":2700*json["qty"]+self.storage+self.fee,
               "units":self.quoted}
        quote["pay"]={"to":self.bank.address,"wei":str(quote["total"]*COIN),
                      "data":"0x"+sha256(qid.encode()).hexdigest()}
        if self.quote_override:
            self.quote_override(quote)
        return self.response(url,quote,code=402)

    def open_proc(self):
        return stock.ledger(self.kit.address("shop").lower(),self.db_path)

    def action(self, args, *, pay=None):
        db=self.open_proc()
        try:
            with self.patches():
                market=stock.Market(self.kit)
                op=args["action"]
                if op=="context":
                    return stock.stock_context(db,market,self.now,args.get("line_cap",10))
                if op=="plan":
                    return stock.stock_plan(db,market,self.now,args["plan"],args["decision"])
                if op=="execute":
                    return stock.stock_execute(db,market,self.now,pay or self.pay)
                if op=="reconcile":
                    return stock.stock_reconcile(db,market,self.now)
                raise AssertionError(op)
        finally:
            db.close()


class Procurement(TestCase):
    def setUp(self):
        temp=TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.f=StockFixture(Path(temp.name))

    def approve(self, *, qty=1):
        context=self.f.action({"action":"context"})
        self.assertEqual(context["status"],"draft")
        self.assertEqual(context["context"]["choices"][0]["options"][0]["qty"],1)
        plan=self.f.action({"action":"plan","plan":context["plan"],"decision":{
            "action":"buy","lines":[{"sku":MOCK_SKU,"qty":qty}],"reason":"One controlled trial"}})
        return context,plan

    def state(self):
        db=self.f.open_proc()
        try:
            return db.execute("SELECT * FROM stock_intent ORDER BY created DESC LIMIT 1").fetchone()
        finally:
            db.close()

    def test_real_shape_draft_coldstart_validation_and_window_execution(self):
        context,invalid=self.approve(qty=2)
        self.assertEqual(invalid["status"],"quantity_not_offered")
        self.assertIsNone(context["context"]["choices"][0]["demand"]["rate"])
        self.assertEqual(context["context"]["novel_limit"],10)
        self.assertEqual(context["context"]["finance"]["inventory_target"],1950000)
        self.assertEqual(context["context"]["finance"]["inventory_maximum"],2400000)
        self.assertEqual(self.approve()[1]["status"],"ready")
        self.assertEqual(self.f.action({"action":"execute"})["status"],"window_closed")
        self.f.advance(91)
        self.assertEqual(self.f.action({"action":"execute"})["status"],"paid_pending_confirmation")
        self.assertEqual(self.f.sends,1)
        self.assertEqual(self.f.calls,[{"sku":MOCK_SKU,"qty":1}])
        self.assertEqual(self.state()["state"],"paid")
        self.assertEqual(self.f.action({"action":"execute"})["status"],"unresolved_prior_payment")
        self.assertEqual(self.f.sends,1)

    def test_wallet_transition_is_durable_and_unknown_recovery_never_sends_twice(self):
        self.approve()
        self.f.advance(91)
        def interrupted(to,wei,marker):
            self.assertEqual(self.state()["state"],"sending")
            self.f.pay(to,wei,marker)
            raise TimeoutError("simulated response lost")
        self.assertEqual(self.f.action({"action":"execute"},pay=interrupted)["status"],"payment_unknown")
        self.assertEqual(self.state()["state"],"unknown")
        self.assertEqual(self.f.action({"action":"reconcile"})["status"],"market_accepted_waiting_for_units")
        self.assertEqual(self.f.sends,1)
        self.assertEqual(self.state()["state"],"accepted")
        self.f.units.extend(self.f.delivered)
        self.f.advance(16)
        self.assertEqual(self.f.action({"action":"reconcile"})["source"],"exact_physical_units")
        self.assertEqual(self.f.sends,1)

    def test_503_same_quote_and_hash_and_no_arrival_until_exact_ids(self):
        self.approve()
        self.f.advance(91)
        self.f.action({"action":"execute"})
        self.f.status_queue=[503,200]
        self.assertEqual(self.f.action({"action":"reconcile"})["market_status"],503)
        self.f.advance(16)
        self.assertEqual(self.f.action({"action":"reconcile"})["status"],"market_accepted_waiting_for_units")
        self.assertEqual(self.f.calls[-1],self.f.calls[-2])
        self.assertEqual(self.f.sends,1)
        self.f.units.append(dict(self.f.delivered[0],unit="u-wrong-equivalent-count"))
        self.f.advance(16)
        self.assertEqual(self.f.action({"action":"reconcile"})["status"],"accepted_awaiting_units")
        self.f.advance(16)
        item=self.state()
        self.f.entry("supply",{"shop":"outseop-r4","sku":MOCK_SKU,"qty":1,"total":2700,
                                "tx_hash":item["tx"],"units":json.loads(item["units"])})
        self.assertEqual(self.f.action({"action":"reconcile"})["source"],"own_market_ledger")

    def test_quote_wallet_price_grade_expiry_or_unit_tampering_cannot_pay(self):
        changes = [
            lambda q:q["pay"].update(to="0x"+"b"*40),
            lambda q:q["pay"].update(data="0x"+"3"*64),
            lambda q:q["pay"].update(wei=str(7*COIN)),
            lambda q:q.update(expires_in=1),
            lambda q:q["units"][0].update(kind="food",expires_at=self.f.now+10),
            lambda q:q["units"][0].update(grade="C",cost=3400),
            lambda q:q["units"][0].update(sku="wrong-sku"),
        ]
        for change in changes:
            with TemporaryDirectory() as temp:
                self.f=StockFixture(Path(temp))
                self.approve()
                self.f.advance(91)
                self.f.quote_override=change
                self.assertEqual(self.f.action({"action":"execute"})["status"],"no_purchase")
                self.assertEqual(self.f.sends,0)
                self.assertEqual(self.state()["state"],"no_purchase")

    def test_food_trial_requires_two_hours_plus_handling_buffer(self):
        self.f.catalog[0].update(kind="food",shelf_hours=24)
        self.approve()
        self.f.advance(91)
        self.f.quote_override=lambda quote: quote["units"][0].update(expires_at=self.f.now+7500)
        self.assertEqual(self.f.action({"action":"execute"})["status"],"paid_pending_confirmation")
        self.assertEqual(self.f.sends,1)

    def test_one_short_lived_unit_rejects_entire_proven_food_lot(self):
        self.f.catalog[0].update(kind="food",shelf_hours=24)
        view=self.f.action({"action":"context"})
        ctx=view["context"]
        choice=ctx["choices"][0]
        choice["tier"]="proven"
        choice["options"]=[{"scenario":"buffer_long","horizon_hours":2,"target":4,
                            "qty":4,"estimated_ceiling":14400}]
        db=self.f.open_proc()
        try:
            db.execute("UPDATE stock_plan SET choices=? WHERE id=?", (json.dumps(ctx),view["plan"]))
        finally:
            db.close()
        self.assertEqual(self.f.action({"action":"plan","plan":view["plan"],"decision":{
            "action":"buy","lines":[{"sku":MOCK_SKU,"qty":4}],"reason":"two hours of confirmed demand"}})["status"],"ready")
        self.f.advance(91)
        def lifetimes(quote):
            for unit in quote["units"]:
                unit["expires_at"]=self.f.now+7500
            quote["units"][-1]["expires_at"]=self.f.now+1200
        self.f.quote_override=lifetimes
        self.assertEqual(self.f.action({"action":"execute"})["status"],"no_purchase")
        self.assertEqual(self.f.sends,0)
        self.assertEqual(self.f.calls,[{"sku":MOCK_SKU,"qty":4}])
        self.assertEqual(self.state()["state"],"no_purchase")

    def test_expired_window_and_refresh_cash_stop_stale_model_approval(self):
        self.approve()
        self.f.advance(91)
        self.f.cash=500001
        self.assertEqual(self.f.action({"action":"execute"})["status"],"fresh_cash_limit")
        self.assertEqual(self.f.calls,[])
        self.f.advance(180)
        self.assertEqual(self.f.action({"action":"execute"})["status"],"window_closed")
        self.assertEqual(self.f.sends,0)

    def test_typed_stockout_cannot_create_proven_sales_and_pending_reserves_cash(self):
        db=self.f.open_proc()
        try:
            db.execute("INSERT INTO stockout_observation VALUES('event',?,?,?,NULL)", (MOCK_SKU,self.f.now,"stockout"))
            signal=stock.forecast(db,MOCK_SKU,self.f.now,.12,COIN)
            self.assertEqual(signal["positive_sales_12h"],0)
            self.assertGreater(signal["rate"],0)
        finally:
            db.close()
        self.approve()
        self.f.advance(91)
        self.f.action({"action":"execute"})
        with self.f.patches():
            db=self.f.open_proc()
            try:
                market=stock.Market(self.f.kit)
                self.assertEqual(stock.capacity(db,market.snapshot(),self.f.now,market.chain())["pending_cost"],2700)
            finally:
                db.close()

    def test_concurrent_quote_window_blocks_second_wallet_attempt(self):
        self.approve()
        self.f.advance(91)
        entered, finish = Event(), Event()
        original = self.f.post
        def slow_first(url, *, json, **kwargs):
            if url.endswith("/api/supply") and "sku" in json:
                entered.set()
                assert finish.wait(5)
            return original(url,json=json,**kwargs)
        with patch.object(self.f,"post",slow_first), self.f.patches(), ThreadPoolExecutor(max_workers=2) as pool:
            def invoke():
                db=self.f.open_proc()
                try:
                    return stock.stock_execute(db,stock.Market(self.f.kit),self.f.now,self.f.pay)
                finally:
                    db.close()
            first = pool.submit(invoke)
            try:
                self.assertTrue(entered.wait(3))
                self.f.advance(11)
                self.assertEqual(pool.submit(invoke).result(timeout=3)["status"],"unresolved_prior_payment")
            finally:
                finish.set()
            self.assertEqual(first.result(timeout=3)["status"],"paid_pending_confirmation")
        self.assertEqual(self.f.sends,1)
        self.assertEqual(len(self.f.calls),1)

    def test_stale_reservation_loses_wallet_cas_and_cert_must_match(self):
        self.approve()
        self.f.advance(91)
        def cancel_reservation(_quote):
            db=self.f.open_proc()
            try:
                db.execute("UPDATE stock_intent SET state='no_purchase' WHERE state='reserved'")
            finally:
                db.close()
        self.f.quote_override=cancel_reservation
        self.assertEqual(self.f.action({"action":"execute"})["status"],"prepayment_reservation_no_longer_current")
        self.assertEqual(self.f.sends,0)
        self.assertEqual(self.state()["state"],"no_purchase")
        self.assertFalse(stock.verified_unit({"sku":MOCK_SKU,"unit":"u-1",
                          "cert":{"cert":{"sku":MOCK_SKU,"unit":"u-1","shop":"outseop-r4"},"sig":"wrong"}},
                          MOCK_SKU,self.f.bank.address.lower()))

    def test_coldstart_can_select_three_diverse_trials_and_prepare_for_full_window(self):
        self.f.start=self.f.now+240
        self.f.end=self.f.start+180
        base=self.f.catalog[0]
        self.f.catalog.extend([
            dict(base,sku="G00000001",list_price=45000,category="운동>용품"),
            dict(base,sku="G00000002",list_price=23000,category="가정>수납"),
            dict(base,sku="G00000003",list_price=100,category="소형>수납"),
        ])
        view=self.f.action({"action":"context","line_cap":3})
        eligible={c["sku"]:c for c in view["context"]["choices"]}
        self.assertEqual(set(eligible),{MOCK_SKU,"G00000001","G00000002"})
        self.assertEqual(view["context"]["novel_limit"],3)
        self.assertGreaterEqual(len(view["context"]["alternatives"]),2)
        self.assertTrue(all(c["demand"]["rate"] is None and c["options"][0]["qty"]==1 for c in eligible.values()))
        decision={"action":"buy","lines":[{"sku":sku,"qty":1} for sku in eligible]}
        self.assertEqual(self.f.action({"action":"plan","plan":view["plan"],"decision":decision})["status"],"ready")
        self.f.advance(240+100)
        snapshot=self.f.action({"action":"context","line_cap":3})
        self.assertEqual(snapshot["status"],"ready")
        self.assertEqual(self.f.action({"action":"execute"})["status"],"paid_pending_confirmation")

    def test_unresolved_refund_blocks_wholesale_wallet(self):
        self.approve()
        self.f.add_unit("u-customer-goods")
        checkout=self.f.call({"text":f"구매 {MOCK_SKU}"})
        self.assertIn("checkout_jwt",checkout.get("data",{}))
        db=self.f.open_proc()
        try:
            sale=db.execute("SELECT id FROM sale").fetchone()["id"]
            db.execute("""
                INSERT INTO refund(sale_id,incoming,payer,wei,marker,transfer_wei,fee_wei,gas_wei,reason,status,requested)
                VALUES(?,?,?,?,?,?,?,?,?,'pending_unknown',?)
            """,(sale,"0x"+"a"*64,"0x"+"b"*40,"1","0x"+"c"*64,"1","0","0","fixture",self.f.now))
        finally:
            db.close()
        self.f.advance(91)
        self.assertEqual(self.f.action({"action":"execute"})["status"],"unresolved_refund_payment")
        self.assertEqual(self.f.sends,0)
        self.assertEqual(self.f.calls,[])

    def test_unresolved_wholesale_wallet_blocks_operator_refund_send(self):
        with TemporaryDirectory() as temp:
            customer=Fixture(Path(temp))
            customer.add_unit("u-normal-sale")
            checkout=customer.call({"text":f"구매 {MOCK_SKU}"})
            owner=customer.right(checkout)
            settled=customer.settle(checkout)
            self.assertTrue(customer.sync()["current"])
            customer.breakage(settled)
            self.assertIn("검토를 접수",customer.call({"text":f"환불 {settled['tx_hash']} 권리 {owner}"})["reply"])
            db=stock.ledger(customer.kit.address("shop").lower(),customer.db_path)
            try:
                db.execute("INSERT INTO stock_plan VALUES('window','id','wallet',0,2,0,2,'{}',NULL,'ready')")
                db.execute("INSERT INTO stock_intent(id,plan_id,sku,qty,total,state,created) VALUES('pending','id',?,1,1,'unknown',0)",
                           (MOCK_SKU,))
                record=refund_admin.list_requests(db)[0]
                with customer.patches(), self.assertRaisesRegex(sales.Unavailable,"unresolved wholesale"):
                    refund_admin.send(db,customer.market(),record["sale_id"],customer.pay,customer.now)
                self.assertEqual(customer.sends,0)
            finally:
                db.close()

    def test_background_model_is_called_once_and_only_with_customer_idle(self):
        view=self.f.action({"action":"context"})
        model_calls=[]
        class Model:
            def complete(_, messages):
                model_calls.append(messages)
                return '{"action":"buy","lines":[{"sku":"G0026722f","qty":1}],"reason":"test choice"}'
        busy=True
        worker=StockCoordinator(self.f.action,Model(),customer_active=lambda:busy,now=lambda:self.f.now)
        worker.tick()
        self.assertFalse(model_calls)
        busy=False
        self.assertEqual(worker.tick()[-1]["status"],"ready")
        self.assertEqual(len(model_calls),1)
        self.f.advance(91)
        self.assertEqual(worker.tick()[-1]["status"],"paid_pending_confirmation")
        self.assertEqual(len(model_calls),1)
        self.assertEqual(self.f.sends,1)
        self.assertIn(view["plan"],worker.plan_attempts)


if __name__ == "__main__":
    main(verbosity=2)

