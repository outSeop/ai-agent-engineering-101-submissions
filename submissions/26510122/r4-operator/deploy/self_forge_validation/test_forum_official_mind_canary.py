from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock

OPERATOR = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(OPERATOR / "deploy"), str(OPERATOR / "kit")]
from forum_official_mind_canary import Canary, NoWallet, TOOL
import agent_kit


def context():
    return {"ok":True,"result":{"status":"options","spotlight_allowed":True,"items":[
        {"sku":"G01234567","grade":"C","name":"모의 식품","category":"식품>과일","price":550,
         "wallet":"private-wallet","cost":4,"certificate":{"raw":"private"}},
        {"sku":"G01234568","grade":"A","name":"모의 의류","category":"의류","price":990},
    ],"reply_options":[{"buyer":"private-buyer"}]}}


class CanaryTest(TestCase):
    def test_dry_mind_run_without_market_or_post(self):
        io = Mock(return_value=context())
        gate = Canary(io)
        model = Mock()
        model.complete.side_effect = [
            '{"action":"forum_marketing","args":{"action":"context"}}',
            '{"action":"forum_marketing","args":{"action":"publish","sku":"G01234567","grade":"C"}}',
            '{"action":"sleep","args":{"seconds":30}}',
        ]
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root/"logs").mkdir()
            mind=agent_kit.Mind(root,{"max_steps":5},model,gate,
                               {"name":"outseop-r4","market":"fixture"},[])
            mind.run_once([])
        io.assert_called_once_with({"action":"context"})
        self.assertEqual(gate.result,{"status":"dry_selection","sku":"G01234567","grade":"C"})
        observed = model.complete.call_args.args[0][3]["content"]
        for private in ("private-wallet","private-buyer","certificate","cost","모의 의류"):
            self.assertNotIn(private,observed)

    def test_rejects_spoofing_and_second_audited_publish(self):
        io = Mock(side_effect=[context(),{"ok":True,"result":{"status":"posted","post":1,"token":"private"}}])
        gate = Canary(io,True)
        gate.call(TOOL,{"action":"context"})
        self.assertEqual(gate.call(TOOL,{"action":"publish","sku":"G01234568","grade":"A"})["status"],
                         "choice_not_eligible")
        self.assertEqual(gate.call(TOOL,{"action":"publish","sku":"G01234567","grade":"C","text":"override"})["status"],
                         "invalid_action")
        rule={"action":"publish","sku":"G01234567","grade":"C"}
        self.assertEqual(gate.call(TOOL,rule),{"status":"posted","sku":"G01234567","grade":"C","post":1})
        self.assertEqual(gate.call(TOOL,rule)["status"],"choice_not_eligible")
        self.assertEqual(io.call_count,2)
        self.assertEqual(gate.forge({}),{"status":"disabled"})
        with self.assertRaises(PermissionError):
            NoWallet().grant(TOOL,{"wallet":["pay"]},5)

