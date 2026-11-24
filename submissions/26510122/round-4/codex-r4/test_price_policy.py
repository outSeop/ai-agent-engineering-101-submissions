"""Launch-budget and grade-C pricing regression fixtures."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import patch
from uuid import uuid4

import dispatcher as core
from fixture import Fixture, MOCK_SKU
import price_policy as policy
import refund_admin


class PricePolicyTest(TestCase):
    def setUp(self):
        temp=TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.fixture=Fixture(self.root)
        self.config=self.root/"trial.json"
        self.patch=patch.object(policy,"POLICY_PATH",self.config)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def config_policy(self,budget=50_000,bps=500):
        self.config.write_text(json.dumps({
            "policy_id":"fixture-launch","starts_at":int(self.fixture.now)-1,
            "ends_at":int(self.fixture.now)+14*86400-1,
            "total_loss_credits":budget,"per_deal_bps":bps}))

    def quote_params(self,sku=MOCK_SKU,price=3400,**args):
        return {"_broker":{"action":"quote_and_send","sku":sku,"proposed_price":price,
                           "commit":uuid4().hex,**args}}

    def row(self):
        db=self.fixture.open()
        try:
            return db.execute("SELECT * FROM promotion_loss ORDER BY at").fetchall()
        finally:
            db.close()

    def test_loss_is_rejected_without_valid_policy_and_below_per_deal_allowance(self):
        self.fixture.add_unit("u-loss",cost=2987)
        self.assertEqual(self.fixture.call(self.quote_params())["outcome"],"price_out_of_bounds")
        self.config_policy(bps=501)
        self.assertIsNone(policy.current(self.fixture.now))
        self.config_policy()
        self.assertEqual(self.fixture.call(self.quote_params(price=3190))["outcome"],"price_out_of_bounds")
        paid=self.fixture.call(self.quote_params())
        self.assertEqual(paid["data"]["price"],3400)
        res,=self.row()
        self.assertEqual(res["reserved"],policy.loss(2987,3400,3400,100,420))
        self.assertEqual(res["state"],"reserved")
        self.assertLessEqual(res["reserved"],149)

    def test_signed_exposure_does_not_double_spend_between_distinct_requests(self):
        self.config_policy(budget=40)
        a=self.fixture.add_unit("u-budget-a",cost=2987)
        sku="G00000002"
        self.fixture.add_unit("u-budget-b",sku=sku,cost=2987)
        price=core.price_terms(a,100,420,40)[1]
        with self.fixture.patches(), ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda x:core.run(self.quote_params(x,price),self.fixture.kit),(MOCK_SKU,sku)))
        self.assertEqual(sum("checkout_jwt" in r.get("data",{}) for r in results),1)
        self.assertEqual(sum(r.get("outcome")=="price_out_of_bounds" for r in results),1)
        res,=self.row()
        self.assertLessEqual(res["amount"],40)

    def test_launch_exposure_survives_settlement_and_refund_policy_expiry(self):
        self.config_policy()
        self.fixture.add_unit("u-bad-goods",cost=2987)
        quote=self.fixture.call(self.quote_params())
        owner=self.fixture.right(quote)
        sale=self.fixture.settle(quote)
        self.fixture.sync()
        start,=self.row()
        self.assertEqual(start["state"],"settled")
        self.assertEqual(start["amount"],start["reserved"])
        self.fixture.breakage(sale)
        claim=self.fixture.call({"text":f"환불 {sale['tx_hash']} 권리 {owner}"})
        self.assertIn("검토를 접수",claim["reply"])
        with self.fixture.patches():
            db=self.fixture.open()
            try:
                refund,=refund_admin.list_requests(db)
                self.assertEqual(refund_admin.send(db,self.fixture.market(),refund["sale_id"],self.fixture.pay,
                                                   self.fixture.now)["status"],"refunded")
            finally:
                db.close()
        ended,=self.row()
        self.assertEqual(ended["state"],"refunded")
        self.assertEqual(ended["amount"],start["amount"])
        self.fixture.advance(14*86400)
        self.assertIsNone(policy.current(self.fixture.now))

    def test_active_launch_ab_preferred_matches_default_checkout_and_forum_price(self):
        import forum
        unit=self.fixture.add_unit("u-active",cost=2987)
        unit.update(name="[신라] 모델 비교 상품",category="생활>상품")
        inactive=self.fixture.call({"_broker":{"action":"context"}})["inventory"][0]
        self.assertEqual(inactive["preferred_price"],4500)
        self.config_policy()
        active=self.fixture.call({"_broker":{"action":"context"}})["inventory"][0]
        self.assertLess(active["preferred_price"],inactive["preferred_price"])
        self.assertGreater(active["preferred_price"],core.price_terms(unit,100,420)[1])
        with self.fixture.patches():
            db=self.fixture.open()
            try:
                rows=forum.stock_offers(db,forum.Market(self.fixture.kit),self.fixture.now)
            finally:
                db.close()
        self.assertEqual(rows[0]["price"],active["preferred_price"])
        checkout=self.fixture.call({"text":f"구매 {MOCK_SKU}"})
        self.assertEqual(checkout["data"]["price"],active["preferred_price"])
        self.assertEqual(self.row(),[])

    def test_grade_c_preference_is_near_cost_and_includes_verified_points(self):
        c=self.fixture.add_unit("u-grade-c",grade="C",cost=2800)
        offered=self.fixture.call({"_broker":{"action":"context"}})["inventory"][0]
        self.assertEqual(offered["grade"],"C")
        self.assertLess(offered["preferred_price"],offered["reference_price"])
        margin=(offered["preferred_price"]-policy.fee(offered["preferred_price"],100,420)
                -c["cost"]-210-offered["preferred_price"]//100)
        self.assertGreaterEqual(margin,0)
        self.assertLessEqual(margin,125)
        earlier="G00000001"
        self.fixture.add_unit("u-earned",sku=earlier,cost=2800)
        previous=self.fixture.call({"text":f"구매 {earlier}"})
        owner=self.fixture.right(previous)
        self.fixture.settle(previous)
        self.fixture.sync()
        context=self.fixture.call({"_broker":{"action":"context","right":owner}})
        with_benefit=next(r for r in context["inventory"] if r["sku"]==MOCK_SKU)
        self.assertEqual(context["redeemable_mileage"],45)
        self.assertEqual(with_benefit["preferred_price"],offered["preferred_price"])
        redeemed=self.fixture.call({"text":f"구매 {MOCK_SKU} 권리 {owner}"})
        self.assertEqual(redeemed["data"]["price"],offered["preferred_price"]-45)
        self.assertEqual(self.row(),[])


    def test_combined_wait_and_miles_reduce_same_public_c_price(self):
        earlier="G00000001"
        self.fixture.add_unit("u-combine-earned",sku=earlier,cost=2800)
        previous=self.fixture.call({"text":f"구매 {earlier}"})
        owner=self.fixture.right(previous)
        self.fixture.settle(previous)
        self.fixture.sync()
        self.fixture.add_unit("u-combine-block",grade="C",cost=2800)
        public=self.fixture.call({"_broker":{"action":"context"}})["inventory"][0]["preferred_price"]
        blocked=self.fixture.call({"text":f"구매 {MOCK_SKU}"})
        self.assertEqual(blocked["data"]["price"],public)
        delayed=self.fixture.call({"text":f"구매 {MOCK_SKU} 권리 {owner}"})
        ticket=self.fixture.right(delayed,"대기")
        self.fixture.settle(blocked)
        self.fixture.sync()
        self.fixture.add_unit("u-combine-return",grade="C",cost=2800)
        scoped=self.fixture.call({"_broker":{"action":"context","right":owner,"wait":ticket}})
        self.assertEqual(scoped["inventory"][0]["preferred_price"],public)
        self.assertEqual(scoped["wait_discount"],public//100)
        bought=self.fixture.call({"text":f"대기 {ticket} 권리 {owner}"})
        self.assertEqual(bought["data"]["price"],public-public//100-45)


if __name__=="__main__":
    main(verbosity=2)

