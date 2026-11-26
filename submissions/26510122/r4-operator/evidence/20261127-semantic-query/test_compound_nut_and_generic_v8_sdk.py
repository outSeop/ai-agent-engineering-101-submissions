"""Ordinary SDK canaries for a changed native catalogue; no market writes."""
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
from public_catalogue_snapshot_host import CatalogueError

manifest=json.loads((bundle/"MANIFEST.json").read_bytes())
pins={name.removeprefix("catalogue/"):value for name,value in manifest["file_sha256"].items() if name.startswith("catalogue/")}
assert all(sha256((bundle/"catalogue"/name).read_bytes()).hexdigest()==value for name,value in pins.items())
now=int(time())

def unit(n,label,path,price,grade,expiry=None):
    return {"unit_ref":f"{n:032x}","sku":f"G{n:08x}","name":label,"category_path":path,
            "state":"available","grade":grade,"price_credits":price,"standard_fee_credits":None,"expires_at":expiry}

rice=[unit(n,f"국산 쌀 산지{n} 5kg",["식품","곡물"],19900+n,"A",now+1000) for n in range(1,11)]
nuts=[unit(20,"아몬드 호두 견과류 200g",["식품","견과"],8010,"B",now+800),
      unit(21,"아몬드 견과 100g",["식품","견과"],12000,"B",now+700)]
compound=unit(25,"하루한줌넛츠 20봉",["식품","견과"],8010,"B",now+650)
noise=[unit(30,"책상 조명품 25W",["생활","조명"],4100,"A")]
items=[*rice,*nuts,compound,*noise]
document={"schema":"outseop-r4.customer-offers.v1","shop":"outseop-r4","observed_at":now,"valid_until":now+115,"units":items}
raw=json.dumps(document,ensure_ascii=False,separators=(",",":")).encode()
both="지금 실제로 파는 쌀과 견과류가 있나요? 있으면 상품명, 등급, 가격과 소비기한을 보여 주세요."
partial="견과류와 캠핑등이 있나요? B등급, 상품가 10,000크레딧 이하, 가격을 알려 주세요."
rice_ids={row["sku"] for row in rice}
nuts_ids={row["sku"] for row in nuts}|{compound["sku"]}
safe={row["sku"]:row for row in items}
protocol=CatalogueProtocol(mask)

with TemporaryDirectory() as tmp:
    native=BoundedPublicCatalogue(bundle/"catalogue",op/"kit",Path(tmp),pins)
    def request():
        return ScopedPublicCatalogue(lambda:(raw,document),native,protocol,
                instruction_from(bundle/"catalogue",pins,official),stock_state_supplier=lambda raw,doc:[])
    primary=request()
    page=primary.open(both,[],5)
    selected=protocol.page_skus(page)
    assert 0<len(selected)<=8 and selected & rice_ids and selected & nuts_ids
    assert selected <= rice_ids | nuts_ids
    assert {fit["sku"] for fit in page["catalogue"]["hints"]["preparation"]["fits"]}==selected
    try:
        primary.fallback(both,5)
    except CatalogueError as exc:
        assert exc.code=="fallback_not_applicable"
    else:
        raise AssertionError("multi-intent fallback unexpectedly rendered")
    secondary=request().open(partial,[],5)
    rows=protocol.page_skus(secondary)
    assert "G00000014" in rows and rows<={"G00000014",compound["sku"]}, sorted(rows)
    assert all(safe[sku]["price_credits"]<=10000 and safe[sku]["grade"]=="B" for sku in rows)
    assert secondary["catalogue"]["hints"]["preparation"]["requested_sku_missing"] is False
    precise=request().open("하루한줌넛츠 20봉과 캠핑 조명도 있나요? 현재 가격 알려주세요.",[],5)
    assert protocol.page_skus(precise)=={compound["sku"]}
    assert precise["catalogue"]["hints"]["preparation"]["constraints_unverified"]
    incorrect=request().open("하루한줌넛츠 30봉 가격 알려주세요.",[],5)
    assert not protocol.page_skus(incorrect)
    generic=request().open("현재 판매 상품 목록",[],5)
    generic_rows=protocol.page_skus(generic)
    assert 0<len(generic_rows)<=8 and generic_rows<=set(safe)
    unknown=request().open("정밀 광학 필터 모듈 재고 있나요?",[],5)
    assert not protocol.page_skus(unknown)
    exact=request().open("재고 G00000014",[],5)
    fits=exact["catalogue"]["hints"]["preparation"]["fits"]
    assert len(fits)==1 and fits[0]["kind"]=="exact_sku"
    missing=request().open("G00000042만 재고를 알려주세요. 대안 필요 없어요.",[],5)
    assert not protocol.page_skus(missing)
print(json.dumps({"sdk_mode":"ordinary_tool_call","both_groups_under_cap":True,"partial_primary_retained":True,
                  "strict_primary_grade_price_preserved":True,"exact_sku_and_no_alternatives":True,
                  "mixed_fallback_denied":True,"compound_pack_exact":True,"wrong_pack_rejected":True,
                  "bounded_generic":True,"unknown_specific_empty":True,"actual_model_apis_wallet_posts":0}))
