import json
from pathlib import Path
import tempfile
import unittest

from buyer_policy import acceptance
from buyer_r3 import opening_request
from ops import buyer_service


class PlainBuyerTests(unittest.TestCase):
    def test_food_message_matches_checkout_requirement_without_budget_or_roleplay(self):
        order = {'kind': 'food', 'use_within_hours': 360, 'budget': 98765}
        message = opening_request('Coffee', 'C1', order)
        self.assertIn(f"{acceptance(order)['min_hours_left']:g} hours", message)
        self.assertIn('market-signed unit certificate', message)
        self.assertNotIn('98765', message)
        self.assertNotIn('hunger', message)

    def test_goods_grade_is_required_and_warranty_is_optional(self):
        message = opening_request('Chair', 'G1', {'kind': 'goods'})
        self.assertIn('Only grade A or B', message)
        self.assertIn('preferred, not required', message)

    def test_frozen_buyer_contains_no_roleplay_modules_or_flags(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); keys = root/'keys'; keys.mkdir()
            for name in ('shop_key.pem', 'buyer_key.pem'): (keys/name).write_text('test fixture only')
            runtime = root/'runtime'
            buyer_service.prepare(runtime, keys)
            manifest = buyer_service.validate(runtime)
            self.assertEqual(manifest['mode'], 'plain')
            self.assertFalse((runtime/'release/buyer_life.py').exists())
            config = json.loads((runtime/'agent.json').read_text())
            self.assertEqual(set(config), {'harness', 'market_buyer', 'review'})
            config['market_buyer']['cmd'] += ' --life'
            (runtime/'agent.json').write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError, 'Roleplay'): buyer_service.validate(runtime)

    def test_release_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); keys = root/'keys'; keys.mkdir()
            for name in ('shop_key.pem', 'buyer_key.pem'): (keys/name).write_text('test fixture only')
            runtime = root/'runtime'; buyer_service.prepare(runtime, keys)
            (runtime/'release/buyer_r3.py').write_text('changed')
            with self.assertRaisesRegex(ValueError, 'integrity'): buyer_service.validate(runtime)


if __name__ == '__main__': unittest.main()
