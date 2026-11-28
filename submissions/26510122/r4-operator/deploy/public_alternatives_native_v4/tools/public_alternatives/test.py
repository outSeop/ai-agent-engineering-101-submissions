def test(run, kit):
    import os

    stock_path = 'host_inputs/stock-state.json'
    stock_mtime_ns = os.stat(stock_path).st_mtime_ns
    os.utime(stock_path, ns=(1_000_000_000, stock_mtime_ns))
    text = '초콜릿 실재고와 가격을 알려주세요'
    context = run({'op': 'context', 'text': text}, kit)
    assert set(context) == {'status', 'snapshot', 'observed_at', 'valid_until', 'items'}, context
    assert context['status'] == 'options' and len(context['snapshot']) == 64
    assert 1 <= len(context['items']) <= 12
    expected = {('G00000001', 'A'): 3200, ('G00000002', 'B'): 2850, ('G00000003', 'C'): 900}
    for item in context['items']:
        assert set(item) == {'sku', 'name', 'category', 'grade', 'preferred_price', 'expires_at'}
        assert expected[(item['sku'], item['grade'])] == item['preferred_price']
    offered = context['items'][0]
    selection = {'sku': offered['sku'], 'grade': offered['grade']}
    request = {'op': 'render', 'text': text, 'snapshot': context['snapshot'], 'items': [selection]}
    answer = run(request, kit)
    assert answer['status'] == 'rendered', answer
    assert '대안' in answer['reply'] and '원래 요청 조건은 확인되지 않았습니다' in answer['reply']
    assert '체크아웃 문서' in answer['reply'] and '발급하지 않았습니다' in answer['reply']
    assert len(answer['reply']) <= 450 and offered['sku'] in answer['reply'] and offered['name'] in answer['reply']
    assert answer['public_facts'] == [dict(selection, preferred_price=offered['preferred_price'])]
    assert answer['observed_at'] == context['observed_at'] and answer['valid_until'] == context['valid_until']
    denied = run({'op': 'context', 'text': text + '. 대체품은 필요 없어요.'}, kit)
    assert set(denied) == {'status', 'reason'} and denied['status'] == 'unavailable'
    first = '1' if context['snapshot'][0] == '0' else '0'
    rejected = run(dict(request, snapshot=first + context['snapshot'][1:]), kit)
    assert set(rejected) == {'status', 'reason'} and rejected['status'] == 'unavailable'
