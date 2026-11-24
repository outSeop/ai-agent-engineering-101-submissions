def test(run,kit):
    x=run({'paths':['/api/catalog','/api/demand','/api/restock','/api/supply-prices']},kit)
    assert all(v['status']==200 for v in x.values())
