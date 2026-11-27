def test(run,kit):
    assert run({'op':'semantic_candidates','text':'x','product_phrase':'x','queries':['x']},kit)['status']=='unavailable'
    assert run({'op':'semantic_candidates','text':'쌀 재고와 가격을 알려주세요. 쌀은 어떤 상품이 있나요? 결제는 나중에 할게요.','product_phrase':'쌀','queries':['쌀','백미']},kit)['status'] in ('unavailable','rendered')
    assert run({'op':'semantic_candidates','text':'쌀 재고와 가격을 알려주세요. 쌀은 어떤 상품이 있나요? 쌀 말고 보리입니다.','product_phrase':'쌀','queries':['쌀']},kit)['status']=='unavailable'
    assert run({'op':'semantic_candidates','text':'쌀 재고와 가격을 알려주세요. 쌀은 어떤 상품이 있나요?','product_phrase':'쌀','queries':['쌀']},kit)['status'] in ('unavailable','rendered')
