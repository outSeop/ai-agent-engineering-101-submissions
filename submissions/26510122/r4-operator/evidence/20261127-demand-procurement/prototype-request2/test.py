from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Barrier
import time


def test(run, kit):
    assert kit.testing
    with TemporaryDirectory() as tmp:
        db = Path(tmp) / 'requests.sqlite3'
        now = time.time()
        items = [{'sku': f'FILL-{index:05d}', 'name': f'Filler display {index:05d}',
                  'category': 'Synthetic'} for index in range(5630)]
        items.extend([
            {'sku': 'FRUIT-A', 'name': 'Golden Apple', 'category': 'Synthetic'},
            {'sku': 'FRUIT-B', 'name': 'Green Apple', 'category': 'Synthetic'},
            {'sku': 'KR-PEAR', 'name': '국산 신고배', 'category': 'Synthetic'},
            {'sku': 'TEA-M', 'name': 'Cloudberry Reserve', 'category': 'Synthetic'},
            {'sku': 'Tail-SkU', 'name': 'Silver Quince', 'category': 'Synthetic'},
        ])
        catalog = {'observed_at': now - 1, 'valid_until': now + 100, 'round': 4, 'items': items}

        def fixture(**changes):
            raw = json.dumps(dict(catalog, **changes), ensure_ascii=False).encode('utf-8')
            kit.stock_request_fixture = (raw, str(db))

        def request(text, ref, **changes):
            args = {'op': 'record', 'text': text, 'event_ref': ref,
                    'observed_at': now - 5, 'source': 'external_completed'}
            args.update(changes)
            outcome = run(args, kit)
            assert set(outcome) == {'status', 'count'}, outcome
            return outcome

        fixture()
        insufficient = {'status': 'insufficient_evidence', 'count': 0}
        unavailable = {'status': 'catalog_unavailable', 'count': 0}
        invalid = {'status': 'invalid_request', 'count': 0}
        for index, text in enumerate([
            'Can I buy mystery fruit?', 'Can I buy tail-skux?', 'Can I buy x-tail-sku?',
            'Can I buy a case for Tail-SkU?', 'Can I buy a substitute for Silver Quince?',
        ]):
            outcome = request(text, f'synthetic:spoof:{index}', explicit_sku='TAIL-SKU',
                              queries=['tail-sku', 'Silver Quince'], product_phrase='Silver Quince')
            assert outcome == insufficient, (text, outcome)
        for index, text in enumerate([
            'Can I buy apple?', 'Do you have Golden Apple or Silver Quince?',
            'Can I buy Golden Apple and Silver Quince?', 'Silver Quince looks nice.',
            'I do not want to buy Silver Quince.', 'Can I buy Silver Quince without payment?',
            'I want to buy Silver Quince as a probe.', 'Can I buy Silver Quince for my allergy?',
            'Can I buy Silver Quince for user@example.test?', 'Can I buy Silver Quince for a refund?',
            'Can I buy Silver Quince with a transaction receipt?', 'Can I buy Silver Quince as proof?',
            '신고배 구매 안 할래요.', '신고배 환불 가능한가요?', '신고배 재고 없나요?',
            'Synthetic test: Can I buy Silver Quince?',
        ]):
            outcome = request(text, f'synthetic:blocked:{index}')
            assert outcome == insufficient, (text, outcome)
        assert request('Can I buy Silver Quince?', 'synthetic:old', observed_at=now-86401) == invalid
        assert request('Can I buy Silver Quince?', 'synthetic:future', observed_at=now+40) == invalid
        assert request('Can I buy Silver Quince?', 'synthetic:nan', observed_at=float('nan')) == invalid
        assert request('Can I buy Silver Quince?', ' synthetic:bad') == invalid
        assert request('Can I buy Silver Quince?', 'synthetic:origin', source='operator') == invalid
        assert request('Can I buy Silver Quince?', 'synthetic:extra', identity='test') == invalid
        for changes in [
            {'observed_at': now-130, 'valid_until': now-1}, {'observed_at': now+10},
            {'observed_at': now-151}, {'valid_until': float('inf')}, {'round': 4.0},
            {'items': items + [{'sku': 'tail-SKU', 'name': 'Other', 'category': 'Synthetic'}]},
            {'items': items + [{'sku': 'EXTRA', 'name': 'Other', 'category': 'Synthetic', 'price': 3}]},
            {'items': items * 2},
        ]:
            fixture(**changes)
            assert request('Can I buy tail-sku?', 'synthetic:bad-catalog') == unavailable
        for raw in (b' ' * (2 * 1024 * 1024 + 1), b'{"round":4,"round":4}', b'\xff'):
            kit.stock_request_fixture = (raw, str(db))
            assert request('Can I buy tail-sku?', 'synthetic:bad-bytes') == unavailable
        assert not db.exists()
        fixture()
        assert request('Can I buy tail-sku?', 'synthetic:tail', explicit_sku='FRUIT-A',
                       queries=['Green Apple']) == {'status': 'recorded', 'count': 1}
        assert request('Can I buy TAIL-SKU?', 'synthetic:tail') == {'status': 'duplicate', 'count': 1}
        assert request('Is sILVER QUINCE available?', 'synthetic:name') == {'status': 'recorded', 'count': 2}
        assert request('신고배 재고 있나요?', 'synthetic:korean') == {'status': 'recorded', 'count': 3}
        assert request('Do you have cloudberry?', 'synthetic:term',
                       product_phrase='made up') == {'status': 'recorded', 'count': 4}
        assert request('국산 신고배를 구매하고 싶어요.', 'synthetic:korean-name') == {'status': 'recorded', 'count': 5}
        assert request('Can I buy Green Apple?', 'synthetic:tail') == {'status': 'duplicate', 'count': 5}

        barrier = Barrier(6)

        def concurrent_request(_):
            barrier.wait(timeout=10)
            return request('Can I buy FRUIT-A?', 'synthetic:concurrent')

        with ThreadPoolExecutor(max_workers=6) as executor:
            outcomes = list(executor.map(concurrent_request, range(6)))
        assert outcomes.count({'status': 'recorded', 'count': 6}) == 1, outcomes
        assert outcomes.count({'status': 'duplicate', 'count': 6}) == 5, outcomes
        with sqlite3.connect(db) as connection:
            assert [row[1] for row in connection.execute('PRAGMA table_info(request)')] == [
                'event_hash', 'sku', 'term', 'observed_at', 'confidence']
            rows = connection.execute('SELECT event_hash, sku, term, observed_at, confidence FROM request').fetchall()
        expected = {
            'synthetic:tail': ('Tail-SkU', None, 'exact_sku'),
            'synthetic:name': ('Tail-SkU', None, 'exact_name'),
            'synthetic:korean': ('KR-PEAR', '신고배', 'public_term'),
            'synthetic:term': ('TEA-M', 'Cloudberry', 'public_term'),
            'synthetic:korean-name': ('KR-PEAR', None, 'exact_name'),
            'synthetic:concurrent': ('FRUIT-A', None, 'exact_sku'),
        }
        hashed = {hashlib.sha256(b'r4:stock-request:event:v2\x00' + ref.encode('ascii')).hexdigest(): values
                  for ref, values in expected.items()}
        assert len(rows) == len(hashed)
        for event_hash, sku, term, observed, confidence in rows:
            assert (sku, term, confidence) == hashed[event_hash]
            assert observed == now - 5
