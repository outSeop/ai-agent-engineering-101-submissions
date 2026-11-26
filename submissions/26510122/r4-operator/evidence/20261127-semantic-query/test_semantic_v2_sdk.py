"""Exercise terminal model-suggested queries through the reviewed real SDK."""
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from time import time

op=Path(sys.argv[1]).resolve()
bundle=Path(sys.argv[2]).resolve()
sys.path[:0]=[str(bundle),str(op/"kit")]
import agent_kit as official
from bounded_public_catalogue_host import BoundedPublicCatalogue, instruction_from
from broker_public_catalogue_host_candidate import mask
from public_catalogue_protocol import CatalogueProtocol
from public_catalogue_request_host import ScopedPublicCatalogue
from public_catalogue_snapshot_host import CatalogueError

manifest=json.loads((bundle/"MANIFEST.json").read_bytes())
pins={key.removeprefix("catalogue/"):digest for key,digest in manifest["file_sha256"].items() if key.startswith("catalogue/")}
assert manifest["catalogue_version"]==8 and manifest["semantic_tool_version"]==2
semantic_pins={key.removeprefix("semantic/"):digest for key,digest in manifest["file_sha256"].items() if key.startswith("semantic/")}
now=int(time())


def unit(n,label,grade,price,category,expiry=None):
    return {"unit_ref":f"{n:032x}","sku":f"G{n:08x}","name":label,"category_path":[category],
            "state":"available","grade":grade,"price_credits":price,"standard_fee_credits":None,"expires_at":expiry}


document={"schema":"outseop-r4.customer-offers.v1","shop":"outseop-r4","observed_at":now,"valid_until":now+115,
          "units":[unit(1,"우유 500ml","A",3000,"유제품",now+900),
                   unit(2,"우유 1l","B",6500,"유제품",now+200),
                   unit(3,"사무의자","B",40000,"가구"),
                   unit(4,"무관한 과자","C",1700,"간식")]}
raw=json.dumps(document,ensure_ascii=False,separators=(",",":")).encode()
protocol=CatalogueProtocol(mask)
with TemporaryDirectory() as tmp:
    native=BoundedPublicCatalogue(bundle/"catalogue",op/"kit",Path(tmp),pins,
        semantic_source=bundle/"semantic",semantic_pins=semantic_pins)
    def request(text,queries):
        service=ScopedPublicCatalogue(lambda:(raw,document),native,protocol,
                instruction_from(bundle/"catalogue",pins,official),stock_state_supplier=lambda raw,doc:[])
        service.open(text,[],5)
        return service.semantic(text,{"queries":queries},5)
    milk=request("밀크 가격 알려 주세요",["우유"])
    assert milk["status"]=="rendered" and "우유" in milk["reply"] and "유사" in milk["reply"]
    chair=request("컴퓨터체어 재고 알려 주세요",["사무의자"])
    assert chair["status"]=="rendered" and "사무의자" in chair["reply"]
    strict=request("밀크 500ml A등급, 상품가 4,000크레딧 이하, 남은 시간 10분 이상 가격 알려 주세요",["우유"])
    assert "G00000001" in strict["reply"] and "G00000002" not in strict["reply"]
    assert "우유 500ml" in strict["reply"] and "3,000크레딧" in strict["reply"] and "우유 1l" not in strict["reply"]
    assert "G00000001" in milk["reply"] and "G00000002" in milk["reply"]
    assert "G00000003" in chair["reply"]
    assert all("SKU" in result["reply"] and "문의" in result["reply"] for result in (milk,chair,strict))
    denials=[
        ("없는 제품 재고 알려 주세요",["존재하지 않는 물건"]),
        ("밀크 2l 가격 알려 주세요",["우유"]),
        ("밀크 가격 알려 주세요. 대안은 필요 없어요.",["우유"]),
        ("재고 G00000099",["우유"]),
        ("밀크 알레르기 안전한 대안 알려 주세요",["우유"]),
        ("밀크 결제권 보내 주세요",["우유"]),
        ("밀크 재고 알려 주세요",["우유","우유"]),
    ]
    for text,queries in denials:
        try:
            request(text,queries)
        except CatalogueError:
            pass
        else:
            raise AssertionError("semantic guard did not deny a negative fixture")
    for result in (milk,chair,strict):
        assert set(result)=={"status","reply","observed_at","valid_until"}
        assert len(result["reply"])<=450
        assert "checkout_jwt" not in result["reply"]
print(json.dumps({"sdk_mode":"ordinary_tool_call","semantic_positive":3,"semantic_negative":len(denials),
                  "public_skus_and_followup_advice":True,"one_snapshot":True,"wallet_network_posts":0}))
