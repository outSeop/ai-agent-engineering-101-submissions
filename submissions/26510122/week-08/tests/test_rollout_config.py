import json,shlex,tempfile,unittest
from pathlib import Path
from ops.rollout_linux import rebound_seller_config


class RolloutConfigTests(unittest.TestCase):
    def test_new_restock_entrypoint_is_rebound_from_stage_to_live_release(self):
        with tempfile.TemporaryDirectory() as directory:
            stage=Path(directory)/'stage';stage.mkdir();live=Path(directory)/'live'
            original={'harness':'seller','seller':{'cmd':shlex.join(['python',str(stage/'release/seller_r3.py')])},
                      'restock':{'cmd':shlex.join(['python',str(stage/'release/procurement_scheduler.py'),'--execute','--state','{state}'])}}
            (stage/'agent.json').write_text(json.dumps(original))
            result=rebound_seller_config(stage,live)
            self.assertEqual(shlex.split(result['restock']['cmd']),
                             ['python',str(live/'release/procurement_scheduler.py'),'--execute','--state','{state}'])
            self.assertEqual(json.loads((stage/'agent.json').read_text()),original)
