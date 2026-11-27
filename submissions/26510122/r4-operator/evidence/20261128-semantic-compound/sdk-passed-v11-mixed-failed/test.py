def test(run,kit):
    assert run({'op':'semantic_candidates','text':'x','product_phrase':'x','queries':['x']},kit)['status']=='unavailable'
    assert run({'op':'semantic_candidates','text':'쌀 재고와 가격을 알려주세요. 쌀은 어떤 상품이 있나요? 결제는 나중에 할게요.','product_phrase':'쌀','queries':['쌀','백미']},kit)['status'] in ('unavailable','rendered')
    assert run({'op':'semantic_candidates','text':'쌀 재고와 가격을 알려주세요. 쌀은 어떤 상품이 있나요? 쌀 말고 보리입니다.','product_phrase':'쌀','queries':['쌀']},kit)['status']=='unavailable'
    assert run({'op':'semantic_candidates','text':'쌀 재고와 가격을 알려주세요. 쌀은 어떤 상품이 있나요?','product_phrase':'쌀','queries':['쌀']},kit)['status'] in ('unavailable','rendered')
    def test_mixed_facts_preview(run,kit):
        a={'op':'semantic_candidates','text':'빵 재고와 가격, 소비기한을 알려주세요. 재고가 있으면 결제서도 부탁해요.','product_phrase':'빵','queries':['재고','가격','소비기한']}
        r=run(a,kit)
        assert r.get('payment_request')=={'status':'not_issued','reason':'product_selection_required'}
        assert '결제서는 발행하지 않았습니다.' in str(r.get('rendered'))
        assert 'G00000001' in str(r.get('hold'))
        assert 'G00000001' in str(r.get('actual'))
        assert 'G00000001' in str(r.get('source'))
