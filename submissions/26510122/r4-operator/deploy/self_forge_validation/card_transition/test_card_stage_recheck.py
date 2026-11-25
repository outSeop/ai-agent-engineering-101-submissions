from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from unittest import TestCase

from card_apply_authority_host import StageOrigin, normalized_fresh, sha
from card_stage_recheck_controller import continue_verified_stage
from unittest.mock import Mock


class CardRecheck(TestCase):
    def setUp(self):
        temp=TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)
        self.before=b'{"name":"outseop-r4"}'
        self.stamp=int(time.time())
        row={"sku":"G00000001","price_credits":1500,"grade":"C","state":"available","valid_until":self.stamp+150}
        self.view={"schema":"outseop-r4.card-offers.v1","shop":"outseop-r4","card_sha256":sha(self.before),
                   "replace_text":"fixture text","observed_at":self.stamp,"valid_until":self.stamp+150,"offers":[row]}
        self.raw=json.dumps(self.view).encode()
        self.body={"schema":"outseop-r4.card-stage.v1","shop":"outseop-r4","view_sha256":sha(self.raw),
                   "skus":["G00000001"],"valid_until":self.stamp+150,"before_sha256":sha(self.before),"before_card_json":self.before.decode()}
        self.capture_start=time.time_ns()
        body=json.dumps(self.body).encode()
        self.response={"status":"staged","record_id":sha(body),"view_sha256":sha(self.raw)}
        self.file=self.path/(sha(body)+".json")
        self.file.write_bytes(body)

    def capture(self):
        return StageOrigin.capture(self.path,self.response,self.raw,"a"*64,self.capture_start,["G00000001"])

    def fresh(self):
        fresh=deepcopy(self.view)
        fresh["observed_at"]+=2
        fresh["valid_until"]+=2
        fresh["offers"][0]["valid_until"]+=2
        return fresh

    def test_exact_same_run_origin_and_ttl_does_not_extend(self):
        origin=self.capture()
        fresh=self.fresh()
        observed=(self.stamp+2)*10**9
        result=normalized_fresh(origin,self.raw,fresh,self.before,observed)
        self.assertEqual(result["offers"],self.view["offers"])
        self.assertEqual(result["valid_until"],self.view["valid_until"])
        self.assertNotEqual(result["observed_at"],self.view["observed_at"])

    def test_wrong_record_bytes_and_old_stage_rejected(self):
        with self.assertRaises(ValueError):
            StageOrigin.capture(self.path,self.response,self.raw,"a"*64,time.time_ns(),["G00000001"])
        self.file.write_bytes(b"{}")
        with self.assertRaises(ValueError):
            self.capture()

    def test_changes_in_price_grade_or_freshness_are_rejected(self):
        origin=self.capture()
        for field,value in (("price_credits",1),("grade","A"),("state","reserved")):
            fresh=self.fresh()
            fresh["offers"][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                normalized_fresh(origin,self.raw,fresh,self.before,(self.stamp+2)*10**9)
        with self.assertRaises(ValueError):
            normalized_fresh(origin,self.raw,self.view,self.before,self.capture_start)


    def test_in_process_continuation_gets_exact_fresh_bytes_only(self):
        origin=self.capture()
        observed=self.stamp+2
        fresh=normalized_fresh(origin,self.raw,self.fresh(),self.before,observed*10**9)
        encoded=json.dumps(fresh).encode()
        card=self.path/"card.json"
        card.write_bytes(self.before)
        hook=Mock()
        args=dict(origin=origin,original_view_raw=self.raw,fresh_view_raw=encoded,
                  before_card_raw=self.before,current_card_path=card)
        continue_verified_stage(hook,**args,clock=lambda:observed)
        hook.assert_called_once_with(origin=origin,original_view_raw=self.raw,
                                     fresh_view_raw=encoded,before_card_raw=self.before)
        hook.reset_mock()
        with self.assertRaises(ValueError):
            continue_verified_stage(hook,**args,clock=lambda:self.stamp+150)
        hook.assert_not_called()
        card.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            continue_verified_stage(hook,**args,clock=lambda:observed)
        hook.assert_not_called()
