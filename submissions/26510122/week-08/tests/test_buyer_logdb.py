import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from buyer_logdb import sync


class BuyerLogDBTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('logs','.market'): (self.root/name).mkdir()

    def write(self, source, rows):
        (self.root/source).write_text(''.join(json.dumps(r)+'\n' for r in rows))

    def query(self, sql):
        with sqlite3.connect(self.root/'state/buyer.sqlite3') as db: return db.execute(sql).fetchall()

    def test_receipt_is_pending_and_only_actual_payment_is_purchase(self):
        self.write('logs/buyer-events.jsonl', [dict(event='negotiation',order='o1',result='receipt_pending'),
            dict(event='settled',order='o1',ledger=1,grade='A',value=200,shop='url',shop_name='shop')])
        self.assertEqual(sync(self.root)['confirmed_purchases'],0)
        self.write('.market/payments.jsonl',[dict(order='o1',item='s1',shop='url',price=100,paid=True,ledger=1)]*2)
        result=sync(self.root)
        self.assertEqual(result['confirmed_purchases'],1)
        self.assertEqual(self.query('SELECT shop_name,grade,value,price FROM confirmed_purchases'),[('shop','A',200,100)])
        self.assertEqual(sync(self.root)['indexed_lines'],0)

    def test_failed_payment_remains_visible_without_becoming_purchase(self):
        self.write('.market/payments.jsonl',[dict(order='o1',paid=False,reason='certificate missing')])
        self.assertEqual(sync(self.root)['confirmed_purchases'],0)
        self.assertIn('certificate missing',self.query('SELECT payload FROM events')[0][0])

    def test_partial_line_is_retried_not_lost(self):
        p=self.root/'logs/buyer-events.jsonl'; p.write_text('{"event":"no_candidate","order":"o1"}')
        self.assertEqual(sync(self.root)['events'],0)
        with p.open('a') as f:f.write('\n')
        self.assertEqual(sync(self.root)['events'],1)

    def test_rotation_preserves_events_and_restarts_cursor(self):
        p=self.root/'logs/buyer-events.jsonl'
        self.write('logs/buyer-events.jsonl',[dict(event='old',order='o1')]);sync(self.root)
        p.rename(p.with_suffix('.previous'))
        self.write('logs/buyer-events.jsonl',[dict(event='new',order='o2')]);sync(self.root)
        self.assertEqual(self.query('SELECT event FROM events ORDER BY id'),[('old',),('new',)])

    def test_malformed_complete_line_is_recorded_with_provenance(self):
        (self.root/'logs/buyer-events.jsonl').write_text('broken\n{"event":"valid"}\n')
        result=sync(self.root)
        self.assertEqual(result['parse_errors'],1)
        self.assertEqual(self.query('SELECT byte_offset FROM events ORDER BY id'),[(0,),(7,)])

    def test_orders_survive_next_order_and_secrets_are_not_captured(self):
        self.write('logs/buyer-events.jsonl',[])
        for order in ('o1','o2'):
            (self.root/'.market/order.json').write_text(json.dumps(dict(order=order,item='coffee',budget=100,
                acceptable=['c1'],use_within_hours=360,mandates='private',nonce='private')))
            sync(self.root)
        sync(self.root)
        rows=self.query("SELECT order_id,payload FROM events WHERE event='order_received'")
        self.assertEqual([r[0] for r in rows],['o1','o2'])
        self.assertNotIn('private',str(rows))
        self.assertEqual(len((self.root/'logs/buyer-order-observations.jsonl').read_text().splitlines()),2)


if __name__=='__main__':unittest.main()
