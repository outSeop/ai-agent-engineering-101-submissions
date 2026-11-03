from datetime import datetime, timezone
import json
import os
from pathlib import Path
import random
import tempfile
import unittest

import inventory_portfolio as portfolio
import replenishment_plan as plans
from stock_policy import sales_evidence, replenishment_candidates
from supply_reconciliation import reconcile, pending_quantity
from test_inventory_portfolio import catalog, inventory


def history(n=3):
    rows = []
    for i in range(n):
        at = datetime.fromtimestamp(990+i, timezone.utc).isoformat()
        rows += [{'event':'receipt_signed','sku':'s1','unit':f'sold{i}','cost':4000,'at':at},
                 {'event':'settled','sku':'s1','unit':f'sold{i}','ledger':i+1,'price':8000,'at':at}]
    return rows


class AmpleStockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.old = Path.cwd(); os.chdir(self.temp.name)

    def tearDown(self):
        os.chdir(self.old); self.temp.cleanup()

    def run_batch(self, model, inv=None, refresh=None, rows=None):
        inv = inv or inventory()
        return portfolio.run(inv, catalog(), rows if rows is not None else history(), 1000,
                             model=model, refresh=refresh or (lambda:(inv,1000,True)), rng=random.Random(1))

    def mixed(self, role, prompt, schema, target=6, new_count=6):
        self.assertEqual(prompt['replenishment_candidates'][0]['sku'], 's1')
        anchor = prompt['exploration_anchor_sku']
        skus = ([anchor] + [r['sku'] for r in prompt['candidates'] if r['sku'] != anchor])[:new_count]
        return {'action':'buy','skus':skus,'replenishment':[{'sku':'s1','target_stock':target}],
                'reason':'Six-unit seller buffer plus a diverse new basket'}

    def test_exploration_and_proven_replenishment_share_one_approval(self):
        result = self.run_batch(self.mixed)
        self.assertEqual(result['buy'][0], {'sku':'s1','qty':5})
        self.assertEqual(len(result['buy']), 7)
        self.assertTrue(all(r['qty']==1 for r in result['buy'][1:]))
        state = json.loads(portfolio.STATE.read_text())
        self.assertEqual(state['intents'][0]['kind'], 'replenishment')
        used = sum(i['cost_ceiling']*i['qty'] for i in state['intents'] if i['kind']=='exploration')
        self.assertEqual(used,45000)
        self.assertEqual(sum(i['cost_ceiling']*pending_quantity(i) for i in state['intents']),82500)

    def test_fresh_stock_growth_cannot_raise_the_approved_target(self):
        inv = inventory()
        current = inventory()
        current['units'] += [dict(current['units'][1], unit=f'arrived{i}') for i in range(2)]
        result = self.run_batch(lambda *args:self.mixed(*args,target=4,new_count=1), inv,
                                refresh=lambda:(current,1000,True))
        self.assertEqual(result['buy'][0], {'sku':'s1','qty':1})  # fresh 3 -> approved 4, never 6

    def test_unknown_sku_or_nonexistent_depth_choice_cannot_be_bought(self):
        for choice in ({'sku':'not-a-candidate','target_stock':6}, {'sku':'s1','target_stock':99}):
            portfolio.STATE.unlink(missing_ok=True)
            def model(*args):
                answer = self.mixed(*args)
                answer['replenishment'] = [choice]
                return answer
            self.assertEqual(self.run_batch(model), {'buy':[]})
            self.assertEqual(json.loads(portfolio.STATE.read_text())['intents'], [])

    def test_combined_budget_is_checked_not_just_each_half(self):
        inv = inventory(); inv['units'][0]['cost'] = 1924000  # total exposure=1.95m, room=50k
        self.assertEqual(self.run_batch(self.mixed, inv), {'buy':[]})
        self.assertEqual(json.loads(portfolio.STATE.read_text())['intents'], [])

    def test_only_linked_positive_settlements_qualify_for_six_unit_depth(self):
        self.assertFalse(sales_evidence('s1',history(2),1000)['proven'])
        self.assertTrue(sales_evidence('s1',history(3),1000)['proven'])
        unknown_cost = [r for r in history(3) if r['event']=='settled']
        self.assertFalse(sales_evidence('s1',unknown_cost,1000)['proven'])
        self.assertEqual(replenishment_candidates(catalog(),inventory(),history(2),1000), [])

    def test_partial_bulk_arrival_keeps_remaining_units_and_cash_reserved(self):
        self.run_batch(self.mixed)
        state = json.loads(portfolio.STATE.read_text())
        bulk = state['intents'][0]
        event = {'event':'settled','sku':'s1','unit':'new0','ledger':99,
                 'at':datetime.fromtimestamp(1010,timezone.utc).isoformat()}
        reconcile(state['intents'], {'units':[]}, [event], 1020)
        self.assertEqual(bulk['status'],'issued_unknown')
        self.assertEqual(pending_quantity(bulk),4)
        self.assertEqual(bulk['cost_ceiling']*pending_quantity(bulk),30000)
        portfolio.STATE.write_text(json.dumps(state))
        self.assertEqual(plans.pending_exploration_cost({'units':[]}),75000)
        rest = [dict(event,unit=f'new{i}',ledger=99+i) for i in range(1,5)]
        reconcile(state['intents'], {'units':[]}, rest, 1020)
        self.assertEqual(bulk['status'],'settled')
        self.assertEqual(pending_quantity(bulk),0)

    def test_later_same_sku_restock_does_not_attach_to_an_already_received_batch(self):
        rows = [{'sku':'s1','at':900,'qty':2,'status':'observed_inventory','prior_units':[],
                 'cost_ceiling':7500,'observed_units':['old0','old1']},
                {'sku':'s1','at':1000,'qty':2,'status':'issued_unknown','prior_units':[], 'cost_ceiling':7500}]
        event = {'event':'settled','sku':'s1','unit':'new0','ledger':99,
                 'at':datetime.fromtimestamp(1010,timezone.utc).isoformat()}
        reconcile(rows, {'units':[]}, [event], 1020)
        self.assertNotIn('new0',rows[0]['observed_units'])
        self.assertEqual(rows[1]['observed_units'],['new0'])
        self.assertEqual(pending_quantity(rows[1]),1)

    def test_cached_six_unit_plan_rechecks_proven_status(self):
        obs = {'observed_visits':3,'observed_no_stock_visits':0,'observed_visit_rate_while_stocked':None,'proven':True}
        p = plans.create(sku='s1',product=catalog()['s1'],candidate={'qty':5,'target_stock':6},
                         approval={'valid_for_seconds':600,'max_total_qty':5},observation=obs,now=1000)
        result, _ = plans.execute(p,inventory=inventory(),product=catalog()['s1'],observation=obs,now=1000)
        self.assertEqual(result,{'buy':[{'sku':'s1','qty':5}]})
        result, reason = plans.execute(p,inventory=inventory(),product=catalog()['s1'],observation={**obs,'proven':False},now=1001)
        self.assertIsNone(result)
        self.assertEqual(reason,'sales_evidence_changed')

    def test_exploitation_window_can_replenish_without_requiring_a_new_sku(self):
        inv = inventory(24)
        for unit in inv['units']: unit['cost'] = 65000
        def model(role,prompt,schema):
            self.assertEqual(prompt['maximum_new_skus'],0)
            self.assertEqual(prompt['policy']['mode'],'exploit')
            return {'action':'buy','skus':[],'replenishment':[{'sku':'s1','target_stock':6}],
                    'reason':'Replace the proven seller only'}
        result = portfolio.run(inv,catalog(),history(),1000,model=model,
                               refresh=lambda:(inv,1000,True),rng=random.Random(2))
        self.assertEqual(result,{'buy':[{'sku':'s1','qty':5}]})


if __name__ == '__main__':
    unittest.main()
