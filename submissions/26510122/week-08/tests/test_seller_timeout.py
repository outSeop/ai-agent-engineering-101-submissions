import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import market_memory
import seller_r3


class ReservationExpiryTests(unittest.TestCase):
    def test_abandoned_reservation_releases_unit_but_receipt_hold_remains(self):
        with tempfile.TemporaryDirectory() as directory:
            previous=Path.cwd();os.chdir(directory)
            try:
                now=time.monotonic();unit={'unit':'u1','sku':'G1','grade':'A','name':'Lamp','category':'goods'}
                seller=seller_r3.Seller()
                seller.open['abandoned']={'unit':unit,'last_activity':now-301,'opened_monotonic':now-301}
                seller.holds['u2']=now+600
                second={**unit,'unit':'u2'}
                market_memory.record('opening',task_id='abandoned',sku='G1',unit='u1',grade='A',ask=100)
                with patch.object(seller_r3,'read_inventory',return_value={'round':3,'units':[unit,second]}):
                    self.assertEqual([u['unit'] for u in seller.available('G1')],['u1'])
                self.assertNotIn('abandoned',seller.open)
                self.assertIn('u2',seller.holds)
                self.assertEqual(market_memory._attempts(market_memory.events())[0]['outcome'],'EXPIRED_UNKNOWN')
            finally:os.chdir(previous)

    def test_active_pings_cannot_exceed_total_reservation_lifetime(self):
        with tempfile.TemporaryDirectory() as directory:
            previous=Path.cwd();os.chdir(directory)
            try:
                now=time.monotonic();seller=seller_r3.Seller()
                seller.open['old']={'unit':{'sku':'G1','unit':'u1'},'last_activity':now,'opened_monotonic':now-901}
                seller.expire_negotiations(now)
                self.assertFalse(seller.open)
            finally:os.chdir(previous)
