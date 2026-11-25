from importlib.util import spec_from_file_location, module_from_spec
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock

STAGE=Path(__file__).resolve().parents[1]/"validation/public_catalogue_runtime_v2"


def load(name):
    spec=spec_from_file_location("reviewed_"+name,STAGE/(name+".py"))
    module=module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


broker=load("broker_public_catalogue_host_candidate")
metrics=load("public_catalogue_phase_metrics")
GOOD={"items":[{"sku":"G0000abcd","grade":"C"}]}
EXTRA={"items":[{"sku":"G0000abcd","grade":"C","preferred_price":4812,"remaining_seconds":120}]}


class RenderContractV2(TestCase):
    def check_repair(self, recover):
        render=Mock(return_value={"reply":"G0000abcd C등급 · 4,812크레딧"})
        catalogue=Mock()
        catalogue.render=render
        catalogue.protocol.page_skus.return_value={"G0000abcd"}
        catalogue.open.return_value=catalogue.search.return_value={"status":"ready"}
        catalogue.instruction="public search"
        legacy=Mock(return_value={"outcome":"context","inventory":[],"verified_account":False})
        seen=[]
        journal=Mock()
        def choose(messages,*,timeout):
            seen.append(messages[-1]["content"])
            if len(seen)==1:
                system=messages[0]["content"]
                table=json.loads(system[system.rfind('{"shop_context":'):])
                desc=table["render_public_products"]
                self.assertIn("exactly two keys: sku",desc)
                self.assertIn("Do not copy price, preferred_price, name, remaining_seconds",desc)
                example=json.loads(desc.split("Example: ",1)[1])
                self.assertEqual(example,{"action":"render_public_products",
                                          "args":{"items":[{"sku":"G00000001","grade":"B"}]}})
                return json.dumps({"action":"search_products","args":{"grade":"C"}})
            if len(seen)==2:
                return json.dumps({"action":"render_public_products","args":EXTRA})
            items=json.loads(seen[-1])["tool_result"]
            self.assertEqual(items["outcome"],"invalid_public_selection")
            self.assertEqual(items["expected_args"],broker.CATALOGUE_RENDER_SCHEMA)
            self.assertIn("rejects extra fields",items["reason"])
            self.assertNotIn("4812",seen[-1])
            self.assertNotIn("remaining_seconds",seen[-1])
            self.assertEqual(items["item_count"],{"min":1,"max":3})
            self.assertEqual(items["allowed_grades"],["A","B","C"])
            if not recover:
                raise TimeoutError("offline model timeout")
            return json.dumps({"action":"render_public_products","args":GOOD})

        with TemporaryDirectory() as folder:
            metric_file=Path(folder)/"metrics.json"
            sink=metrics.PhaseMetrics(metric_file)
            def record(event):
                journal(event)
                sink(event)
            flow=broker.Broker(legacy,Mock(complete=choose),max_steps=3,seconds=65,model_seconds=35,
                               catalogue=catalogue,phase_report=record)
            response=flow.handle("현재 C등급 상품 가격을 찾아 주세요.")
            event=journal.call_args.args[0]
            outcome=event["outcome"]
            content=json.loads(metric_file.read_bytes())
        self.assertEqual(event["phase_reasons"]["render"],"invalid_public_selection")
        self.assertEqual(content["outcomes"][outcome]["phase_reasons"]["render"],{"invalid_public_selection":1})
        legacy.assert_called_once()
        if recover:
            render.assert_called_once()
            self.assertEqual(render.call_args.args[0],GOOD)
            self.assertIn("4,812크레딧",response["reply"])
            self.assertEqual(event["reason"],"none")
        else:
            render.assert_not_called()
            self.assertEqual(event["reason"],"model_timeout")

    def test_repair_recovers_without_relaxing_validator(self):
        self.check_repair(True)

    def test_rejection_metric_survives_later_model_timeout(self):
        self.check_repair(False)

