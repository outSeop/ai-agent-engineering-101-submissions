import json
from unittest import TestCase

from card_keeper_preflight import retained_selection,digest
from card_stage_recheck_controller import public_continuation_result


class KeeperTest(TestCase):
    def test_exact_continuation_and_stop_on_facts_change(self):
        card=json.dumps({"description":"stage block\n\nretained"}).encode()
        row={"sku":"G00000002","name":"public item","state":"available","price_credits":1000,"grade":"C",
             "valid_until":150,"expires_at":None}
        old=json.dumps({"offers":[row]}).encode()
        event={"schema":"outseop-r4.card-publication-event.v1","op":"apply","shop":"outseop-r4",
               "after_sha256":digest(card),"view_sha256":digest(old),"skus":[row["sku"]],
               "offer_until":150,"block":{"start":0,"end":11,"text":"stage block"}}
        view={"offers":[dict(row,valid_until=200)],"valid_until":200,
              "card_sha256":digest(card),"replace_text":"stage block"}
        def choose():
            return retained_selection("a"*64,event,old,view,card,now=60)
        self.assertEqual(choose()["skus"],["G00000002"])
        self.assertEqual(choose()["selection_origin"],"derived_continue_prior_class_selection")
        view["offers"][0]["price_credits"]=1001
        self.assertEqual(choose(),{"status":"requires_class_selection"})

    def test_published_receipt_allowlists_only_verified_fields(self):
        result={"status":"applied","event":"a"*64,"card_sha256":"f"*64,"guard":"skipped","token":"private"}
        projected=public_continuation_result(result)
        self.assertEqual(set(projected),{"status","event","card_sha256","guard"})
        self.assertEqual(projected["status"],"applied")
        self.assertEqual(public_continuation_result(dict(result,guard="unknown"))["status"],"unverified_receipt")
        self.assertEqual(public_continuation_result({"status":"dry","other":"private"}),{"status":"dry"})

