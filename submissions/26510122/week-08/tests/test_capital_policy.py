from datetime import datetime, timezone
import os
from pathlib import Path
import random
import tempfile
import unittest

from capital_policy import ROUND_END, operating_policy, target_inventory_cost
import inventory_portfolio as portfolio
import inventory_exploration as startup
import replenishment_plan as plans
from stock_policy import demand_forecast
from test_inventory_portfolio import catalog


class CapitalPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old=Path.cwd();os.chdir(self.temp.name)
        self.addCleanup(self.temp.cleanup);self.addCleanup(os.chdir,self.old)

    def inventory(self, now):
        return {'round':3,'balance':5_000_000,'units':[],
                'restock':{'open':True,'opens_at':now-10,'closes_at':now+170}}

    def history(self, now, age=100):
        at=datetime.fromtimestamp(now-age,timezone.utc).isoformat()
        result=[]
        for i in range(2):
            result += [dict(event='receipt_signed',sku='s1',unit=f'paid{i}',cost=4000,at=at),
                       dict(event='settled',sku='s1',unit=f'paid{i}',ledger=i,price=8000,at=at)]
        return result

    def test_growth_uses_75_percent_exposure_and_65_percent_soft_target(self):
        now=ROUND_END-7*86400;inv=self.inventory(now)
        inv['units']=[dict(sku='old',grade='A',cost=1_000_000)]
        risk=plans.inventory_risk(inv,now,pending_cost=0)
        self.assertEqual(risk['inventory_cost_limit'],4_500_000)
        self.assertEqual(risk['available_to_invest'],3_500_000)
        self.assertEqual(risk['cash_reserve'],600_000)
        self.assertEqual(target_inventory_cost(inv,now),3_900_000)
        self.assertEqual(risk['operating_policy']['window_budget'],1_200_000)

    def test_bankruptcy_line_and_pending_commitments_still_bind(self):
        now=ROUND_END-7*86400;inv=self.inventory(now)
        inv.update(balance=1_000_000,bankrupt_line=800_000)
        self.assertEqual(plans.inventory_risk(inv,now,pending_cost=0)['available_to_invest'],100_000)
        self.assertEqual(plans.inventory_risk(inv,now,pending_cost=800_000)['available_to_invest'],0)

    def test_goods_holding_costs_have_a_cash_buffer_through_deadline(self):
        now=ROUND_END-10*86400;inv=self.inventory(now)
        inv['units']=[dict(sku='goods',kind='goods',grade='A',cost=1_000_000)]
        risk=plans.inventory_risk(inv,now,pending_cost=0)
        self.assertEqual(risk['storage_cash_buffer'],100_000)
        self.assertEqual(risk['cash_reserve'],700_000)

    def test_capital_tapers_and_new_exploration_stops_before_end(self):
        self.assertTrue(operating_policy(ROUND_END-73*3600)['allow_new_skus'])
        for remaining,phase,share in [(72,'harvest',.5),(24,'final_day',.25),(2,'sell_only',0),(0,'sell_only',0)]:
            policy=operating_policy(ROUND_END-remaining*3600)
            self.assertEqual((policy['phase'],policy['inventory_capital_share']),(phase,share))
            self.assertFalse(policy['allow_new_skus'])
        inv=self.inventory(ROUND_END-3600)
        self.assertEqual(plans.inventory_risk(inv,ROUND_END-3600,pending_cost=0)['available_to_invest'],0)

    def test_cached_plan_cannot_buy_through_final_two_hour_cutoff(self):
        now=ROUND_END-7210
        observation={'proven':True,'stock_limit':2,'observed_visits':5,'observed_no_stock_visits':0,
                     'observed_visit_rate_while_stocked':None}
        p=plans.create(sku='s1',product=catalog()['s1'],candidate={'qty':1,'target_stock':1},
                       approval={'valid_for_seconds':600,'max_total_qty':1},observation=observation,now=now)
        result,reason=plans.execute(p,inventory=self.inventory(now),product=catalog()['s1'],observation=observation,now=ROUND_END-7199)
        self.assertEqual((result,reason),({'buy':[]},'market_closing'))

    def test_harvest_buys_proven_replacements_without_new_skus(self):
        now=ROUND_END-48*3600;inv=self.inventory(now)
        def model(role,prompt,schema):
            self.assertEqual(prompt['operating_policy']['phase'],'harvest')
            self.assertEqual(prompt['candidates'],[])
            winner=prompt['replenishment_candidates'][0]
            return {'action':'buy','skus':[],'replenishment':[{'sku':winner['sku'],
                'target_stock':winner['target_options'][-1]['target_stock']}],'reason':'Sell before deadline'}
        result=portfolio.run(inv,catalog(),self.history(now),now,model=model,
                             refresh=lambda:(inv,now,True),rng=random.Random(2))
        self.assertTrue(result['buy'])
        self.assertEqual({r['sku'] for r in result['buy']},{'s1'})

    def test_slow_seller_target_does_not_assume_terminal_inventory_has_value(self):
        now=ROUND_END-3*3600;inv=self.inventory(now)
        forecast=demand_forecast('s1',catalog()['s1'],inv,self.history(now,age=5*3600),now)
        self.assertEqual(forecast['terminal_sale_capacity_estimate'],0)
        self.assertEqual(forecast['maximum_target'],0)

    def test_final_cutoff_blocks_portfolio_and_startup_calls(self):
        now=ROUND_END-3600;inv=self.inventory(now)
        def model(*_):self.fail('No new buying calls near market end')
        self.assertEqual(portfolio.run(inv,catalog(),[],now,model=model,refresh=lambda:(inv,now,True)),{'buy':[]})
        self.assertIsNone(startup.run(inv,catalog(),[],{},now,model=model))


if __name__=='__main__':unittest.main()
