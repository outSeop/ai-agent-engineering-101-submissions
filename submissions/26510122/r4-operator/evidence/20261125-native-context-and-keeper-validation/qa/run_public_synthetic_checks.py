"""Run exactly the three public synthetic suites (21 tests), never Model API."""
from pathlib import Path
import unittest
import qa_card_renewal_apply3_independent as renewal
import test_card_keeper_same_choice_host_candidate as keeper
import test_customer_native_context_canary_host as customer
suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(cls) for cls in
    (renewal.RenewalIntegrationQA,keeper.KeeperQA,customer.CanaryTests))
if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
