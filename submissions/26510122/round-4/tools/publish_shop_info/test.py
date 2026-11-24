
def test(run, kit):
    import json
    from pathlib import Path
    from types import SimpleNamespace
    import inspect

    card=Path("card.json")
    root=Path.cwd()
    assert "runtime" in root.parts and root.name=="agent-work", "use isolated agent-work only"
    card.write_text(json.dumps({"name":"outseop-r4","wallets":{"shop":"fixture"},
                                "identity":{"fixture":True},"other":[1,2]}),encoding="utf-8")
    args={"description":"테스트 설명: 실제 재고 확인과 정상 정산 뒤 적립.",
          "skills":[{"id":"checkout","name":"재고와 결제","description":"테스트 기능",
                     "tags":["inventory"],"examples":["재고를 알려주세요"]}]}
    assert run(args,kit)["status"]=="published"
    actual=json.loads(card.read_text())
    assert set(actual)=={"name","wallets","identity","other","description","skills"}
    assert actual["wallets"]=={"shop":"fixture"}
    assert actual["identity"]=={"fixture":True} and actual["other"]==[1,2]
    assert actual["name"]=="outseop-r4" and actual["skills"]==args["skills"]
    before=card.read_bytes()
    invalid=[dict(args,name="another"),dict(args,description="x"*1001),dict(args,skills=[dict(args["skills"][0],tags=[])]),
             dict(args,skills=[dict(args["skills"][0],examples="not a list")]),
             dict(args,skills=args["skills"]*2),dict(args,skills=[dict(args["skills"][0],wallet="no")])]
    for candidate in invalid:
        assert run(candidate,kit)["status"]=="rejected"
        assert card.read_bytes()==before
    assert run(args,SimpleNamespace(name="other"))["status"]=="rejected"
    assert run(args,kit)["status"]=="published" and card.read_bytes()==before
    card.write_text('{"name":"outseop-r4"}',encoding="utf-8")
    return {"authorship":"OpenAI Codex GPT-6.2 Sol","test":"isolated fake card publication and protected field preservation"}
