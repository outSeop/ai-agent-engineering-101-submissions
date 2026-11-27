import hashlib
import json
import os
import sqlite3
import tempfile
import time


def test(run, kit):
    with tempfile.TemporaryDirectory() as directory:
        database = os.path.join(directory, 'requests.sqlite3')
        now = time.time()
        items = [{'sku': f'F-{i:05d}', 'name': f'표본 재료 {i:05d}', 'category': '표본'} for i in range(5630)]
        items.extend([
            {'sku': 'DEUL-300', 'name': '들녘 취나물300g', 'category': '산나물'},
            {'sku': 'DEUL-500', 'name': '푸른 취나물500g', 'category': '산나물'},
            {'sku': 'SOY-100', 'name': '고소한 두유 100ml', 'category': '음료'},
        ])
        catalog = {'observed_at': now - 1, 'valid_until': now + 100, 'round': 4, 'items': items}

        def install(document):
            kit.stock_request_fixture = (json.dumps(document, ensure_ascii=False).encode('utf-8'), database)

        def call(ref, text, expected=1, **updates):
            args = {'op': 'record', 'text': text, 'event_ref': ref,
                    'observed_at': time.time(), 'source': 'external_completed'}
            args.update(updates)
            response = run(args, kit)
            assert set(response) == {'status', 'count'}, response
            assert response['count'] == expected, (ref, response)
            return response

        def event_key(ref):
            return hashlib.sha256(b'r4:stock-request:event:v2' + bytes([0]) + ref.encode('ascii')).hexdigest()

        install(catalog)
        call('partial', '취나물 재고와 가격 보여 주세요', explicit_sku='SOY-100')
        call('sku', 'deul-300 가격 알려 주세요', explicit_sku='SOY-100')
        call('title', '들녘 취나물300g 재고 있나요?')
        call('late-item', 'F-05629 price')
        call('neutral', '취나물 재고와 가격 보여 주세요. 결제는 나중에 할게요.')
        call('weak', '오틀리 바리스타 재고와 가격 보여 주세요', product_phrase='오틀리 바리스타', queries=['두유'])
        call('old-valid', 'DEUL-300 stock', observed_at=time.time() - 86399)
        call('future', 'DEUL-300 price', 0, observed_at=time.time() + 999)
        call('old', 'DEUL-300 price', 0, observed_at=time.time() - 86401)
        call('bool', 'DEUL-300 price', 0, observed_at=True)
        call('nan', 'DEUL-300 price', 0, observed_at=float('nan'))
        call('inf', 'DEUL-300 price', 0, observed_at=float('inf'))
        call('string', 'DEUL-300 price', 0, observed_at=str(time.time()))
        call('case', 'DEUL-300 price', 0, source='External_completed')
        call('proof', '취나물 재고와 가격 보여 주세요. 결제 증빙 발급해 주세요.', 0)
        call('refund', '취나물 재고와 가격 보여 주세요. 환불해 주세요.', 0)
        call('private', '취나물 가격 알려 주세요. 제 주소는 서울입니다.', 0)
        call('finance', 'DEUL-300 price in tOKRW', 0)
        call('date', '2026-11-27 취나물 가격 알려 주세요', 0)
        call('negative', '취나물 말고 두유 가격 알려 주세요', 0)
        call('two', '취나물과 두유 가격 알려 주세요', 0)
        call('partial-substring', '나물 가격 알려 주세요', 0)
        call('fake', '오틀리 바리스타 가격 알려 주세요', 0, product_phrase='다른 품목', queries=['두유'])
        call('fake-term', '오틀리 바리스타 가격 알려 주세요', 0, product_phrase='오틀리 바리스타', queries=['두유', '비공개품목'])
        assert call('partial', 'SOY-100 price', 0)['status'] == 'duplicate'
        with sqlite3.connect(database) as connection:
            connection.execute('INSERT INTO request VALUES (?, ?, ?, ?, ?)',
                               (event_key('prior-version'), 'SOY-100', None, now, 'exact_sku'))
        assert call('prior-version', 'DEUL-300 price', 0)['status'] == 'duplicate'
        install(dict(catalog, observed_at=now - 101, valid_until=now - 1))
        call('expired', 'DEUL-300 price', 0)
        install(dict(catalog, valid_until=now + 151))
        call('long-ttl', 'DEUL-300 price', 0)
        install(dict(catalog, items=items + [{'sku': 'deul-300', 'name': '중복', 'category': '표본'}]))
        call('duplicate-catalog', 'DEUL-300 price', 0)
        with sqlite3.connect(database) as connection:
            records = dict((key, (sku, term, confidence)) for key, sku, term, confidence in
                           connection.execute('SELECT event_hash, sku, term, confidence FROM request'))
        expected = {
            'partial': (None, '취나물', 'public_term'),
            'sku': ('DEUL-300', None, 'exact_sku'),
            'title': ('DEUL-300', None, 'exact_name'),
            'late-item': ('F-05629', None, 'exact_sku'),
            'neutral': (None, '취나물', 'public_term'),
            'weak': (None, '두유', 'public_term'),
            'old-valid': ('DEUL-300', None, 'exact_sku'),
            'prior-version': ('SOY-100', None, 'exact_sku'),
        }
        assert records == {event_key(ref): row for ref, row in expected.items()}, records
