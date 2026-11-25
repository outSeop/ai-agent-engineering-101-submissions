from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import r4_forum_slate_host as host


def item(index, grade, spotlight=True):
    return {"sku":f"G{index:08x}","grade":grade,"name":"상품 2개입","category":"식품",
            "price":1000,"expiry":None,"certificate":True,"spotlight_eligible":spotlight}


def pair(row):
    return {field:row[field] for field in ("sku","grade")}


class Scope(TestCase):
    def test_full_acquisition_does_not_truncate_or_rank(self):
        offers=[item(i,"C") for i in range(1,21)]+[item(21,"A"),item(22,"B")]
        db=Mock()
        db.execute.return_value.fetchone.return_value=None
        with TemporaryDirectory() as temp:
            path=Path(temp)/"forum.py"
            path.write_bytes(b"synthetic legacy source")
            legacy=SimpleNamespace(__file__=str(path),PRESETS={"aggressive":(600,3600,96)},
                                   cooldown=Mock(return_value=None),available_options=Mock(return_value=([],offers,[],True)),
                                   offer_fingerprint=Mock(return_value="synthetic"))
            with patch.object(host,"LEGACY_PIN",sha256(path.read_bytes()).hexdigest()):
                view=host.full_options(db,object(),legacy,100)
        self.assertEqual(view["items"],offers)
        self.assertEqual([x["grade"] for x in view["items"][-2:]],["A","B"])

    def test_post_scope_uses_native_subset_not_source_thread_or_c_only_slates(self):
        a,c=item(1,"A"),item(2,"C")
        thread={"thread":7,"request":"C등급은 빼고 찾습니다.","eligible":[pair(a),pair(c)]}
        snapshot={"schema":"stage","valid_until":140,"spotlight_allowed":True,"items":[a,c],"reply_options":[thread]}
        displayed={"status":"options","spotlight_allowed":True,
                   "items":[dict(x,pack_label="explicit_small",pack_count=2) for x in (a,c)],
                   "reply_options":[{**thread,"eligible":[pair(a)]}]}
        legacy=Mock(return_value={"status":"dry_selection"})
        scoped=host.ScopedExecutor(legacy,lambda:snapshot,lambda _:displayed,clock=lambda:100)
        scoped({"action":"context"})
        self.assertEqual(scoped({"action":"publish","decision":{"action":"reply","thread":7,**pair(c)}}),
                         {"status":"choice_not_eligible"})
        legacy.assert_not_called()
        scoped({"action":"context"})
        request={"action":"publish","decision":{"action":"reply","thread":7,**pair(a)}}
        self.assertEqual(scoped(request),{"status":"dry_selection"})
        self.assertEqual(scoped(request),{"status":"choice_not_eligible"})
        legacy.assert_called_once_with(request)
        altered=deepcopy(displayed)
        altered["items"][0]["price"]=1
        with self.assertRaisesRegex(ValueError,"unproven"):
            host.validate_scope(snapshot,altered)
