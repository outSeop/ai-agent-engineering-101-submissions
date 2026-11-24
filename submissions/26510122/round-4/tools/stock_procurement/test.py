
def test(run, kit):
    from pathlib import Path
    import sys
    from tempfile import mkdtemp
    from unittest.mock import patch
    from types import SimpleNamespace

    sys.path.insert(0, str(Path.cwd() / "codex-r4"))
    from test_procurement import StockFixture, MOCK_SKU
    root=Path("state/r4-benefits/tests")
    root.mkdir(parents=True,exist_ok=True)
    f=StockFixture(Path(mkdtemp(dir=root)))
    f.kit.pay=lambda to,wei,marker,role=None:f.pay(to,wei,marker)
    scope=run.__globals__
    original=scope["ledger"]
    clock=SimpleNamespace(time=lambda:f.now,monotonic=scope["time"].monotonic)
    with f.patches(), patch.dict(scope,{"time":clock,"ledger":lambda wallet:original(wallet,f.db_path)}):
        draft=run({"action":"context"},f.kit)
        assert draft["status"]=="draft", draft
        assert draft["context"]["choices"][0]["demand"]["rate"] is None
        approved=run({"action":"plan","plan":draft["plan"],"decision":{
                "action":"buy","lines":[{"sku":MOCK_SKU,"qty":1}],"reason":"isolated one-unit trial"}},f.kit)
        assert approved["status"]=="ready",approved
        f.advance(91)
        assert run({"action":"execute"},f.kit)["status"]=="paid_pending_confirmation"
        assert run({"action":"reconcile"},f.kit)["status"]=="market_accepted_waiting_for_units"
        f.units.extend(f.delivered)
        f.advance(16)
        assert run({"action":"reconcile"},f.kit)["status"]=="arrived"
        assert f.sends==1
    return {"authorship":"OpenAI Codex GPT-6.2 Sol","isolated":"402 quote, mock wallet, same quote hash, exact certified arrival"}
