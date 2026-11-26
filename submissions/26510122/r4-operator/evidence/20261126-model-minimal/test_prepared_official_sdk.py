"""Exercise the frozen tool through the reviewed SDK subprocess."""
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from time import time
from hashlib import sha256

op=Path(sys.argv[1]).resolve()
bundle=Path(sys.argv[2]).resolve()
sys.path[:0]=[str(bundle),str(op/"kit")]
import agent_kit as official
from bounded_public_catalogue_host import BoundedPublicCatalogue, instruction_from
from broker_public_catalogue_host_candidate import mask
from public_catalogue_protocol import CatalogueProtocol
from public_catalogue_request_host import ScopedPublicCatalogue

manifest=json.loads((bundle/"MANIFEST.json").read_bytes())
pins={name.removeprefix("catalogue/"):value for name,value in manifest["file_sha256"].items() if name.startswith("catalogue/")}
assert manifest["catalogue_version"]==6
assert all(sha256((bundle/"catalogue"/k).read_bytes()).hexdigest()==v for k,v in pins.items())
now=int(time())
def unit(n,label,path,price,grade):
    return {"unit_ref":f"{n:032x}","sku":f"G{n:08x}","name":label,"category_path":path,
            "state":"available","grade":grade,"price_credits":price,"standard_fee_credits":None,"expires_at":None}
document={"schema":"outseop-r4.customer-offers.v1","shop":"outseop-r4","observed_at":now,"valid_until":now+115,
          "units":[unit(1,"국산 쌀 5kg",["식품","곡물"],19900,"A"),
                   unit(2,"국산 쌀 10kg",["식품","곡물"],37000,"B"),
                   unit(3,"아몬드 호두 견과 200g",["식품","견과"],8010,"B")]}
raw=json.dumps(document,ensure_ascii=False,separators=(",",":")).encode()
with TemporaryDirectory() as tmp:
    native=BoundedPublicCatalogue(bundle/"catalogue",op/"kit",Path(tmp),pins)
    protocol=CatalogueProtocol(mask)
    def request():
        return ScopedPublicCatalogue(lambda:(raw,document),native,protocol,
                instruction_from(bundle/"catalogue",pins,official),stock_state_supplier=lambda raw,doc:[])
    ask=request()
    out=ask.open("백미 5kg 현재 가격 보여 주세요",[],5)
    assert protocol.page_skus(out)=={"G00000001"}
    assert out["catalogue"]["hints"]["preparation"]["fits"][0]["kind"]=="category_alternative"
    rendered=ask.render({"items":[{"sku":"G00000001","grade":"A"}]},5)
    assert "19,900" in rendered["reply"] and "G00000001" in rendered["reply"]
    nuts=request().open("견과 상품의 가격을 알려 주세요",[],5)
    assert protocol.page_skus(nuts)=={"G00000003"}
    missing=request().open("돼지고기 현재 재고 알려 주세요",[],5)
    assert not protocol.page_skus(missing)
    strict=request().open("백미 5kg B등급 재고 알려 주세요",[],5)
    assert not protocol.page_skus(strict)
    direct=request()
    direct.open("재고 G00000001",[],5)
    assert "19,900" in direct.fallback("재고 G00000001",5)["reply"]
print(json.dumps({"official_sdk_prepared":True,"rice_alias_and_pack":True,"nuts":True,"missing_meat":True,
                  "strict_grade":True,"canonical_render":True,"prepared_fallback":True,"actual_network_wallet_or_post":0}))
