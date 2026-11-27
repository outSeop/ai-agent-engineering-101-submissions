
def test(run, kit):
    from pathlib import Path
    from tempfile import mkdtemp
    from types import SimpleNamespace
    from unittest.mock import patch
    import sys
    sys.path.insert(0,str(Path.cwd()/"codex-r4"))
    from test_forum import ForumFixture, MOCK_SKU
    parent=Path("state/r4-benefits/tests")
    parent.mkdir(parents=True,exist_ok=True)
    fixture=ForumFixture(Path(mkdtemp(dir=parent)))
    fixture.add_unit("u-forge-forum").update(name="클립형 키친타올 걸이",category="주방>키친타올걸이")
    request=fixture.add_post(MOCK_SKU+" A급 구합니다.")
    ns=run.__globals__
    open_original=ns["open_forum"]
    with fixture.patches(), patch.dict(ns,{"time":SimpleNamespace(time=lambda:fixture.now),
                                         "open_forum":lambda wallet:open_original(wallet,fixture.db_path)}):
        options=run({"action":"context"},fixture.kit)
        assert options["reply_options"][0]["thread"]==request["id"]
        fixture.lost_response=True
        decision={"action":"reply","thread":request["id"],"sku":MOCK_SKU,"grade":"A"}
        assert run({"action":"publish","decision":decision},fixture.kit)["status"]=="unknown"
        fixture.advance(40)
        assert run({"action":"reconcile"},fixture.kit)["status"]=="reconciled"
        assert len(fixture.calls)==1
        assert "4,500 크레딧" in fixture.calls[0]["text"]
    return {"authorship":"OpenAI Codex GPT-6.2 Sol","evidence":"model selection bounds, mock forum timeout and exact reconciliation"}
