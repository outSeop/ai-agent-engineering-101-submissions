"""Mock the exact R4 forum's public feed and authenticated publication."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase, main

import httpx

from fixture import Fixture, MOCK_MARKET, MOCK_SKU
import forum
from marketing_card import build_card
from marketing_runtime import MarketingCoordinator


class ForumFixture(Fixture):
    def __init__(self,root):
        super().__init__(root)
        self.posts=[]
        self.calls=[]
        self.lost_response=False

    def add_post(self, text, *, author="fixture-buyer", role="buyer", thread=None):
        item={"id":len(self.posts)+1,"ts":self.now,"round":4,"author":author,"role":role,
              "thread":thread,"text":text}
        self.posts.append(item)
        return item

    def get(self,url,*,params=None,**kwargs):
        if url==MOCK_MARKET+"/api/forum":
            assert params["limit"]==100
            since=params["since"]
            rows=[p for p in self.posts if p["id"]>since]
            return self.response(url,rows[:100] if since else rows[-100:])
        return super().get(url,params=params,**kwargs)

    def post(self,url,*,json,**kwargs):
        if url!=MOCK_MARKET+"/api/forum":
            return super().post(url,json=json,**kwargs)
        self.calls.append(json)
        assert kwargs["headers"]=={"authorization":"Bearer fixture-test-only"}
        result=self.add_post(json["text"],author="outseop-r4",role="shop",thread=json.get("thread"))
        if self.lost_response:
            raise httpx.ReadTimeout("fixture post response lost")
        return self.response(url,{"post":result["id"]})

    def action(self,args):
        db=forum.open_forum(self.kit.address("shop").lower(),self.db_path)
        try:
            with self.patches():
                market=forum.Market(self.kit)
                if args["action"]=="context":
                    return forum.forum_context(db,market,self.now)
                if args["action"]=="publish":
                    return forum.forum_publish(db,market,self.now,args["decision"])
                if args["action"]=="reconcile":
                    return forum.forum_reconcile(db,market,self.now)
                raise AssertionError(args)
        finally:
            db.close()


class ForumTests(TestCase):
    def setUp(self):
        temp=TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.f=ForumFixture(Path(temp.name))
        self.item=self.f.add_unit("u-forum")
        self.item.update(name="[주방] 클립형 키친타올 걸이",category="주방>키친타올걸이")

    def publish(self,**decision):
        return self.f.action({"action":"publish","decision":decision})

    def test_reply_matches_explicit_fresh_demand_and_model_does_not_supply_text(self):
        p=self.f.add_post(f"{MOCK_SKU} A등급 4,500원 이내로 구해요.")
        unrelated=self.f.add_post("검은 등산용 신발을 구합니다.")
        self.assertEqual(self.publish(action="reply",sku=MOCK_SKU,grade="A",thread=unrelated["id"])["status"],
                         "no_fresh_matching_request")
        self.assertEqual(self.publish(action="reply",sku=MOCK_SKU,grade="A",thread=p["id"],text="BUY NOW")["status"],
                         "invalid_choice")
        menu=self.f.action({"action":"context"})
        self.assertEqual(menu["reply_options"][0]["thread"],p["id"])
        self.assertEqual(self.publish(action="reply",sku=MOCK_SKU,grade="A",thread=p["id"])["status"],"posted")
        sent,=self.f.calls
        self.assertEqual(sent["thread"],p["id"])
        self.assertIn("4,500 크레딧",sent["text"])
        for item in ("A등급","A2A","정상 정산","7일","다음 구매","120초","함께 사용할","48시간","운영자"):
            self.assertIn(item,sent["text"])
        self.assertNotIn("checkout_jwt",sent["text"])
        self.assertLessEqual(len(sent["text"]),2000)

    def test_stock_grade_or_budget_changed_since_menu_blocks_publish(self):
        p=self.f.add_post(f"{MOCK_SKU} A등급 4,500원 이내로 구해요.")
        self.assertTrue(self.f.action({"action":"context"})["reply_options"])
        self.item["grade"]="B"
        self.assertEqual(self.publish(action="reply",sku=MOCK_SKU,grade="A",thread=p["id"])["status"],
                         "no_fresh_matching_request")
        self.assertFalse(self.f.calls)

    def test_timeout_reconciles_exact_identity_thread_and_content_without_reposting(self):
        p=self.f.add_post(f"{MOCK_SKU} 구합니다.")
        self.f.lost_response=True
        self.assertEqual(self.publish(action="reply",sku=MOCK_SKU,grade="A",thread=p["id"])["status"],"unknown")
        self.assertEqual(self.publish(action="reply",sku=MOCK_SKU,grade="A",thread=p["id"])["status"],"unresolved_publish")
        proper=self.f.posts.pop()
        self.f.add_post(proper["text"],author="imposter",role="shop",thread=p["id"])
        self.f.advance(31)
        self.assertEqual(self.f.action({"action":"reconcile"})["status"],"unknown")
        self.f.add_post(proper["text"],author="outseop-r4",role="shop",thread=p["id"])
        self.f.advance(121)
        self.assertEqual(self.f.action({"action":"reconcile"})["status"],"reconciled")
        self.assertEqual(len(self.f.calls),1)

    def test_root_rotation_grade_c_and_card_contain_only_real_listings(self):
        self.assertEqual(self.publish(action="spotlight",sku=MOCK_SKU,grade="A")["status"],"posted")
        self.f.advance(forum.POST_GAP+1)
        self.assertEqual(self.publish(action="spotlight",sku=MOCK_SKU,grade="A")["status"],"spotlight_unavailable")
        self.f.advance(forum.SPOTLIGHT_GAP+1)
        self.assertEqual(self.publish(action="spotlight",sku=MOCK_SKU,grade="A")["status"],"no_fresh_offer")
        new=self.f.add_unit("u-rotated",sku="G00000001",grade="C")
        new.update(name="[새상품] 다른 품목",category="생활>다른 품목")
        menu=self.f.action({"action":"context"})
        card=build_card(menu["items"])
        self.assertIn("C등급",card["description"])
        self.assertIn("크레딧",card["description"])
        self.assertNotIn("C등급",build_card([])["description"])
        self.assertEqual(self.publish(action="spotlight",sku=new["sku"],grade="C")["status"],"posted")
        self.assertIn("C등급",self.f.calls[-1]["text"])

    def test_unchanged_offer_not_repeated_after_cooldown(self):
        self.assertEqual(self.publish(action="spotlight",sku=MOCK_SKU,grade="A")["status"],"posted")
        self.f.advance(forum.SKU_GAP+2)
        self.assertEqual(self.publish(action="spotlight",sku=MOCK_SKU,grade="A")["status"],"duplicate_content")
        self.assertEqual(len(self.f.calls),1)

    def test_card_maintenance_and_marketing_only_run_in_shared_idle_window(self):
        events=[]
        context={"status":"waiting","opens_at":self.f.now+301}
        scheduler=MarketingCoordinator(lambda _:None,None,now=lambda:self.f.now)
        stock=SimpleNamespace(tick=lambda:(events.append("stock") or [{},context]))
        scheduler.tick=lambda:events.append("forum")
        scheduler.stop=SimpleNamespace(is_set=lambda:events.count("stock")>=1,wait=lambda _:None)
        scheduler.loop(stock,maintenance=lambda:events.append("card"))
        self.assertEqual(events,["stock","card","forum"])
        events.clear()
        context["opens_at"]=self.f.now+300
        scheduler.loop(stock,maintenance=lambda:events.append("card"))
        self.assertEqual(events,["stock"])
        events.clear()
        context["opens_at"]=self.f.now+301
        scheduler.customer_active=lambda:True
        scheduler.loop(stock,maintenance=lambda:events.append("card"))
        self.assertEqual(events,["stock"])

    def test_marketing_tick_never_sends_raw_market_fields_or_runs_during_customer_call(self):
        self.f.add_post(f"{MOCK_SKU} 구합니다. 권리 "+"a"*43)
        calls=[]
        class Model:
            def complete(_,messages):
                calls.append(messages)
                return json.dumps({"action":"reply","thread":1,"sku":MOCK_SKU,"grade":"A"})
        busy=True
        coordinator=MarketingCoordinator(self.f.action,Model(),customer_active=lambda:busy,now=lambda:self.f.now)
        self.assertEqual(coordinator.tick()["status"],"postponed")
        self.assertFalse(calls)
        busy=False
        self.assertEqual(coordinator.tick()["status"],"posted")
        menu=calls[0][1]["content"]
        self.assertNotIn("a"*43,menu)
        self.assertNotIn("wallet",menu)
        self.assertNotIn("cert\"",menu)
        self.assertIn(MOCK_SKU,menu)


if __name__=="__main__":
    main(verbosity=2)

