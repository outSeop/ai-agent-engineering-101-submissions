def test(run, kit):
    out=run({'quote':'q-test','pay':{'to':'0x0','wei':'0','data':'0x'}},kit)
    assert out['tx_hash'].startswith('0x')
