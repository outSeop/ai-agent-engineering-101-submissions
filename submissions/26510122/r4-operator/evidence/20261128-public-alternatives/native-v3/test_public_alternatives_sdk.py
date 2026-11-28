"""Independent synthetic ordinary SDK checks for the read-only alternatives tool."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
import time

OP=Path(__file__).resolve().parents[3]
ASSET=OP/"deploy/public_catalogue_runtime_v8a/catalogue"
TOOL="public_alternatives"

def digest(value):
    return sha256(value).hexdigest()

def make_fixture():
    now = int(time.time())
    units = [
        {"unit_ref": "synthetic_unit_alpha", "sku": "G00000001", "name": "채소 반찬",
         "category_path": ["식품", "간편식"], "state": "available", "grade": "A",
         "price_credits": 3200, "standard_fee_credits": 91, "expires_at": now + 86400},
        {"unit_ref": "synthetic_unit_beta", "sku": "G00000002", "name": "면 반찬",
         "category_path": ["식품", "간편식"], "state": "available", "grade": "B",
         "price_credits": 2850, "standard_fee_credits": 91, "expires_at": now + 90000},
        {"unit_ref": "synthetic_unit_gamma", "sku": "G00000003", "name": "합성 수첩",
         "category_path": ["생활용품", "문구"], "state": "available", "grade": "C",
         "price_credits": 900, "standard_fee_credits": 50, "expires_at": None},
    ]
    document = {"schema": "outseop-r4.customer-offers.v1", "shop": "outseop-r4",
                "observed_at": now - 1, "valid_until": now + 120, "units": units}
    raw = json.dumps(document, ensure_ascii=False).encode()
    state = {"schema": "outseop-r4.public-stock-state.v1", "snapshot": digest(raw),
             "observed_at": document["observed_at"], "valid_until": document["valid_until"],
             "rows": [{"sku": u["sku"], "grade": u["grade"], "expires_at": u["expires_at"],
                       "preferred_price": u["price_credits"], "stock_status": "available"}
                      for u in units]}
    return raw, json.dumps(state, ensure_ascii=False).encode()

class NoWallet:
    def grant(self, name, permission, timeout):
        if any(permission.get(key) for key in ("network","write","identity","wallet","exec","pay_limit","handles")):
            raise AssertionError("unexpected capability")
        return None

def copy_tool(from_path, to_path, name):
    leaves = ("logic.py","test.py","permission.yml","forge.json")
    files = {leaf:(from_path/leaf).read_bytes() for leaf in leaves}
    receipt = json.loads(files["forge.json"])
    actual = {leaf:sha256(data).hexdigest() for leaf,data in files.items() if leaf!="forge.json"}
    if receipt.get("tool")!=name or receipt.get("sha256")!=actual:
        raise ValueError("SDK source hashes do not match")
    to_path.mkdir(mode=0o700)
    for leaf,data in files.items():
        path=to_path/leaf
        path.write_bytes(data)
        path.chmod(0o400)

def check(source, root):
    sys.path.insert(0,str(OP/"kit"))
    import agent_kit
    agent_kit.mk.LOG_FILE=None
    tools=root/"tools"
    tools.mkdir(mode=0o700)
    copy_tool(ASSET,tools/"public_catalogue","public_catalogue")
    copy_tool(source,tools/TOOL,TOOL)
    inputs=root/"host_inputs"
    inputs.mkdir(mode=0o700)
    cache=inputs/"customer_offer_context.json"
    stock=inputs/"stock-state.json"
    box=agent_kit.Toolbox(root,{"name":"outseop-r4","market":"https://example.invalid","tokens":{},
                              "addresses":{},"signer":NoWallet()})
    raw, sidecar=make_fixture()
    def write(path, data):
        if path.exists():
            path.chmod(0o600)
        path.write_bytes(data)
        path.chmod(0o400)
    def install(cache_bytes=raw, stock_bytes=sidecar):
        write(cache,cache_bytes)
        write(stock,stock_bytes)
    def call(args):
        result=box.run(TOOL,"call",args)
        if not result.get("ok") or result.get("printed"):
            return {"status":"sdk_runtime_failure"}
        return result["result"]
    def unavailable(response):
        return response.get("status")=="unavailable"
    def change_row(state,sku,**updates):
        for row in state["rows"]:
            if row["sku"]==sku:
                row.update(updates)
    cases={}
    question="초콜릿의 현재 재고와 가격을 알려주세요."
    context_args={"op":"context","text":question}
    install()
    menu=call(context_args)
    items=menu.get("items",[])
    cases["verified_bounded_context"]=(menu.get("status")=="options"
        and menu.get("snapshot")==sha256(raw).hexdigest() and 0<len(items)<=12
        and len(json.dumps(menu,ensure_ascii=False))<=5500
        and all(set(item)=={"sku","name","category","grade","preferred_price","expires_at"} for item in items)
        and not any(unit in json.dumps(menu) for unit in ("synthetic_unit_alpha","synthetic_unit_beta","synthetic_unit_gamma")))
    if not items:
        return cases
    row=items[0]
    sku=row["sku"]
    choice={"sku":sku,"grade":row["grade"]}
    args={"op":"render","text":question,"snapshot":menu["snapshot"],"items":[choice]}
    rendered=call(args)
    reply=rendered.get("reply","")
    cases["only_verified_alternative_and_no_checkout"]=(rendered.get("status")=="rendered"
        and len(reply)<=450 and sku in reply and f"{row['preferred_price']:,}" in reply
        and row["grade"] in reply and "대안" in reply
        and any(term in reply for term in ("확인되지","확인하지","미확인"))
        and any(term in reply for term in ("발행하지","발급하지","미발급")))
    cases["wrong_snapshot_denied"]=unavailable(call(dict(args,snapshot="0"*64)))
    cases["duplicate_selection_denied"]=unavailable(call(dict(args,items=[choice,choice])))
    cases["off_menu_denied"]=unavailable(call(dict(args,items=[{"sku":"GFFFFFFFF","grade":"A"}])))
    for label,text in (
       ("do_not_substitute","초콜릿 재고와 가격을 알려주세요. 대안은 필요 없어요."),
       ("allergy_must_not_be_guessed","초콜릿 재고와 가격을 알려주세요. 땅콩 알레르기가 있어요."),
       ("limited_price_must_not_be_dropped","초콜릿 재고를 1,000크레딧 이하만 알려주세요."),
       ("specific_sku_without_relation_must_not_be_forced","GFFFFFFFF 재고와 가격을 알려주세요."),
       ("payment_must_use_original_route","초콜릿 결제권을 보내주세요."),
       ("current_original_candidate_keeps_original_path","채소 반찬 재고와 가격을 알려주세요."),
    ):
        cases[label]=unavailable(call(dict(context_args,text=text)))
    for label, updates in (
        ("new_reservation_blocks_render",{"stock_status":"reserved_pending"}),
        ("reconciling_blocks_render",{"stock_status":"reconciling"}),
        ("changed_price_blocks_render",{"preferred_price":row["preferred_price"]+1}),
        ("changed_expiry_blocks_render",{"expires_at":int(time.time())+200000}),
    ):
        state=json.loads(sidecar)
        change_row(state,sku,**updates)
        install(stock_bytes=json.dumps(state).encode())
        cases[label]=unavailable(call(args))
    document=json.loads(raw)
    state=json.loads(sidecar)
    document["observed_at"]=state["observed_at"]=int(time.time())-20
    document["valid_until"]=state["valid_until"]=int(time.time())-1
    stale_raw=json.dumps(document,ensure_ascii=False).encode()
    state["snapshot"]=sha256(stale_raw).hexdigest()
    install(stale_raw,json.dumps(state).encode())
    cases["stale_denied"]=unavailable(call(context_args))
    install()
    state=json.loads(sidecar)
    state["snapshot"]="1"*64
    install(stock_bytes=json.dumps(state).encode())
    cases["sidecar_hash_mismatch_denied"]=unavailable(call(context_args))
    return cases

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source",type=Path,required=True)
    args=p.parse_args()
    with tempfile.TemporaryDirectory(prefix="r4-native-alternative-qa-") as directory:
        cases=check(args.source.resolve(strict=True),Path(directory))
    output={"cases":cases,"passed":sum(cases.values()),"total":len(cases),"production_modified":False}
    print(json.dumps(output,sort_keys=True))
    if not cases or not all(cases.values()):
        raise SystemExit(1)

if __name__=="__main__":
    main()
