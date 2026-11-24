def test(run, kit):
    x=run({'urls':[kit.market+'/.well-known/agent-card.json']},kit)
    assert x['cards'][0]['status']==200
