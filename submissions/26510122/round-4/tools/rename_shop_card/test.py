def test(run, kit):
    result = run({'name': '생활 상점'}, kit)
    assert result['ok'] is True
    assert result['name'] == '생활 상점'
    import json
    with open('card.json', encoding='utf-8') as f:
        assert json.load(f)['name'] == '생활 상점'
