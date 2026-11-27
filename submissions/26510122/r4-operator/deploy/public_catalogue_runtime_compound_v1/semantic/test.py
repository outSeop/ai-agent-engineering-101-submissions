def test(run,kit):
    assert run({'op':'semantic_candidates','text':'x','product_phrase':'x','queries':['x']},kit)['status']=='unavailable'
    assert run({'op':'semantic_candidates','text':'침대와 침구 재고와 가격을 알려주세요','groups':[{'product_phrase':'침대','queries':['침대']},{'product_phrase':'침구','queries':['침구']}]},kit)['status'] in ('unavailable','rendered')
    assert run({'op':'semantic_candidates','text':'침대 말고 침구','groups':[{'product_phrase':'침대','queries':['침대']},{'product_phrase':'침구','queries':['침구']}]},kit)['status']=='unavailable'
    assert run({'op':'semantic_candidates','text':'침대와 침구 브랜드를 알려주세요','groups':[{'product_phrase':'침대','queries':['침대']},{'product_phrase':'침구','queries':['침구']}]},kit)['status']=='unavailable'
    assert run({'op':'semantic_candidates','text':'침대와 침구','groups':[{'product_phrase':'침대','queries':['침대']},{'product_phrase':'침구','queries':['침구']}]},kit)['status'] in ('unavailable','rendered')