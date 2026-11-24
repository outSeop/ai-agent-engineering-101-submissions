def test(run,kit):
    x=run({'sku':'G0026722f','qty':1,'quote_only':True},kit)
    assert x['phase']=='quote'
    assert x['status'] in (402,429,400)
