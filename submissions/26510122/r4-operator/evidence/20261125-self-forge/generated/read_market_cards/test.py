def test(run, kit):
    x=run({'url':'https://market.ourolabs.ai/.well-known/agent-card.json'}, kit)
    assert x['status_code']==200
    assert x['text']=='TEST_FIXTURE'
