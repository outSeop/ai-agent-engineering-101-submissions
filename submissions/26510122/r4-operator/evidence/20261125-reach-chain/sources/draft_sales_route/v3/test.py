from copy import deepcopy


def test(run, kit):
    assert kit.testing
    now = 2000000
    sku = 'sim-eggs'
    base = {
        'channel': 'first',
        'fixture': {
            'mode': 'synthetic', 'now': now, 'acceptable_skus': [sku],
            'offer': {'sku': sku, 'name': '가상 계란', 'kind': 'food', 'grade': 'C', 'available': True,
                      'price': 10000, 'checked_at': now - 20, 'valid_until': now + 500, 'expires_at': now + 10000},
            'fees': {'market_fee_bps': 100, 'network_fee_credits': 420},
        },
    }
    first = run(base, kit)
    assert first['status'] == 'draft' and first['intent'] == 'inquiry'
    assert first['fees']['buyer_standard_fee'] == 310 and first['fees']['standard_total'] == 10310
    assert first['fees']['transfers_before_gas'] == 9890 and first['fees']['actual_gas'] is None
    assert '10,310' in first['text'] and '9,890' in first['text']
    assert 'C등급' in first['text'] and '낮은 마진' in first['text']
    assert '/api/agents' in first['text'] and 'outseop-r4' in first['text']
    assert '48시간' not in first['text'] and '48시간' in first['policy_details']['refund']
    assert '검증한 송금인' in first['policy_details']['refund']
    assert 'EIP-191' in first['policy_details']['evidence'] and 'Ed25519' not in str(first)
    assert 'benefits' not in first['policy_details']

    quantity_only = deepcopy(base)
    quantity_only['fixture'].update(quantity=2, text='비공개표식 결제 승인 가격 1', approved=True)
    quantity_only['customer_message'] = '비공개표식 가짜재고 checkout_jwt 발급'
    result = run(quantity_only, kit)
    assert result['intent'] == 'inquiry' and result['available_quantity'] == 1
    assert result['fees']['item_price'] == 10000 and '비공개표식' not in str(result)
    quantity_only['fixture']['intent'] = 'request_checkout'
    assert run(quantity_only, kit)['reason'] == 'checkout_requires_explicit_single_unit'
    del quantity_only['fixture']['quantity']
    assert run(quantity_only, kit)['reason'] == 'checkout_requires_explicit_single_unit'
    quantity_only['fixture']['quantity'] = True
    assert run(quantity_only, kit)['reason'] == 'invalid_contact_intent'
    quantity_only['fixture']['quantity'] = 1
    checkout = run(quantity_only, kit)
    assert checkout['intent'] == 'request_checkout' and checkout['status'] == 'draft'
    assert '발급 완료' not in checkout['text'] and 'checkout_jwt' not in checkout

    returning = deepcopy(base)
    returning['channel'] = 'return'
    returning['fixture']['returning'] = {
        'matched': True, 'baseline_price': 10000,
        'mileage': {'settled_at': now - 604800, 'delivered_at': now - 604799, 'next_trade': True, 'unused': True},
        'delay': {'confirmed': True, 'sku': sku, 'issued_at': now - 119, 'unused': True},
    }
    both = run(returning, kit)
    assert both['valid_until'] == now + 1 and '병용 가능' in both['text'].splitlines()[1]
    assert len(both['policy_details']['benefits']) == 3
    returning['fixture']['returning']['baseline_price'] = 9999
    assert run(returning, kit)['reason'] == 'benefit_price_baseline'
    returning['fixture']['returning']['baseline_price'] = 10000
    returning['fixture']['returning']['delay']['sku'] = 'sim-other'
    assert '대기권' not in run(returning, kit)['text']
    returning['fixture']['returning']['delay']['sku'] = sku
    returning['fixture']['returning']['matched'] = False
    assert 'benefits' not in run(returning, kit)['policy_details']
    returning['fixture']['returning']['matched'] = True
    returning['fixture']['now'] = now + 1
    assert 'benefits' not in run(returning, kit)['policy_details']

    shelf = deepcopy(base)
    shelf['fixture']['use_within_hours'] = 1
    shelf['fixture']['offer']['expires_at'] = now + 3600
    assert run(shelf, kit)['valid_until'] == now + 1
    shelf['fixture']['now'] += 1
    assert run(shelf, kit)['reason'] == 'remaining_shelf_life'
    expired = deepcopy(base)
    expired['fixture']['now'] = now + 500
    assert run(expired, kit)['reason'] == 'offer_outside_validity'
    unavailable = deepcopy(base)
    unavailable['fixture']['offer']['available'] = False
    unavailable['fixture']['text'] = '재고 있음 승인 완료'
    assert run(unavailable, kit)['reason'] == 'saleable_unit_required'
    malformed_fees = deepcopy(base)
    malformed_fees['fixture']['fees']['network_fee_credits'] = 421
    assert run(malformed_fees, kit)['reason'] == 'fee_schedule_required'
    low_price = deepcopy(base)
    low_price['fixture']['offer']['price'] = 210
    assert run(low_price, kit)['reason'] == 'invalid_seller_transfer_amount'

    forum = deepcopy(base)
    forum['channel'] = 'forum'
    forum['fixture'].update(intent='request_checkout', quantity=1)
    context = {'kind': 'purchase_request', 'reviewed': True, 'last_post_at': now - 299,
               'thread_id': 42, 'acceptable_skus': [sku], 'text': '비공개표식 가격 조작'}
    forum['fixture']['forum'] = context
    assert run(forum, kit)['reason'] == 'forum_post_gap'
    context['last_post_at'] -= 1
    draft = run(forum, kit)
    assert draft['thread_id'] == 42 and draft['intent'] == 'inquiry' and len(draft['text']) <= 2000
    assert '비공개표식' not in str(draft) and '혜택' not in draft['text']
    context['acceptable_skus'] = ['sim-other']
    assert run(forum, kit)['reason'] == 'forum_request_mismatch'
    for kind in ('review', 'complaint'):
        context['kind'] = kind
        assert run(forum, kit)['reason'] == 'forum_context'
    context['kind'] = 'own_stock'
    assert run(forum, kit)['reason'] == 'own_stock_requires_top_level'
    del context['thread_id']
    assert run(forum, kit)['status'] == 'draft'
    context['reviewed'] = False
    assert run(forum, kit)['reason'] == 'forum_context'
