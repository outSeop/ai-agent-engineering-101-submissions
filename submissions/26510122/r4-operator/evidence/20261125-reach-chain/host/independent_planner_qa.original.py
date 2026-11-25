"""Independent synthetic and cached-public-shape tests; no network or business calls."""
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parent
OP=ROOT.parents[1]
EXPECTED="77449caeecd41b4a26e249a17b38946f7f4e62f4bc451d2956ec60951bf3f393"
KIT=SimpleNamespace(testing=True)


def base():
    rows=[{"sku":"G00000001","category":"식품>가상계란>계란","count":12},{"sku":"G00000002","category":"식품>가상계란>계란","count":4},{"sku":"G00000003","category":"식품>가상계란>계란","count":4},{"sku":"G00000004","category":"식품>가상채소>신선야채","count":5},{"sku":"G00000005","category":"식품>가상반찬>반찬","count":2}]
    return {"summary":{"mode":"synthetic_test","coverage":"boundaries_observed","requested_time":{"start":6400,"end":10000},"sample_time":{"start":6399,"end":9999},"by_sku":rows,"by_category":dict(Counter({"식품>가상계란>계란":20,"식품>가상채소>신선야채":5,"식품>가상반찬>반찬":2})),"sealed_count":1,"unclassified_count":2},"existing_skus":["G00000001"]}


def categories(summary):
    counts=Counter()
    for row in summary["by_sku"]:counts[row["category"]]+=row["count"]
    summary["by_category"]=dict(counts)


def main():
    tool=ROOT/"tools/plan_public_sku_trials";manifest=json.loads((tool/"forge.json").read_text())
    for name,digest in manifest["sha256"].items():assert hashlib.sha256((tool/name).read_bytes()).hexdigest()==digest
    raw=(tool/"logic.py").read_bytes();assert hashlib.sha256(raw).hexdigest()==EXPECTED
    namespace={"__name__":"independent_planner_qa","__file__":str(tool/"logic.py")};exec(compile(raw,str(tool/"logic.py"),"exec"),namespace);run=namespace["run"]
    checks=[];scopes=[]
    def call(args):return run(args,KIT)
    def check(name,ok,group="contract",expected=None,observed=None):checks.append({"case":name,"passed":bool(ok),"group":group,"expected":expected,"observed":observed})
    args=base();s=args["summary"];out=call(args)
    expected=[("G00000004",5,1),("G00000002",4,1),("G00000005",2,1)]
    actual=[(x["sku"],x["observed_count"],x["planned_units"]) for x in out.get("candidates",[])]
    check("direct_v2_full_category_compatibility_and_trial_sort",actual==expected,"compatibility",expected,actual)
    check("planning_only_synthetic_provisional",out.get("status")=="planning_only" and out.get("provisional") is True)
    check("coverage_and_times_preserved",all(out.get(k)==s[k] for k in ["coverage","requested_time","sample_time","sealed_count","unclassified_count"]))
    check("one_unit_and_one_SKU_per_category",all(x["planned_units"]==1 for x in out["candidates"]) and len({x["category"] for x in out["candidates"]})==len(out["candidates"]))
    check("no_profit_forecast_or_purchase_approval","미확인" in out["limits"] and out["before_purchase"]==["공급가","수수료·가스","보관비·폐기 위험","유통기한","환불·혜택 비용","현금 하한"])
    for label,rows in [("reversed",list(reversed(s["by_sku"]))),("rotated",s["by_sku"][1:]+s["by_sku"][:1])]:
        c=deepcopy(args);c["summary"]["by_sku"]=rows;check("stable_tie_order_"+label,call(c)==out)
    c=deepcopy(args);c["existing_skus"]=[x["sku"] for x in s["by_sku"]];check("all_existing_excluded",call(c).get("candidates")==[])
    c=deepcopy(args);c["existing_skus"]*=2;check("duplicate_existing_filter_does_not_add_candidates",call(c).get("candidates")==out["candidates"])
    c=deepcopy(args);c["summary"].update(coverage="partial",sample_time={"start":6400,"end":9999});o=call(c);check("partial_provisional",o.get("coverage")=="partial" and o.get("provisional") is True)
    c["summary"]["coverage"]="boundaries_observed";check("inconsistent_start_boundary_rejected",call(c).get("error")=="inconsistent_coverage")
    for value in [0,True,-1,1.5,"5"]:
        c=deepcopy(args);c["summary"]["by_sku"][0]["count"]=value;check("invalid_count_"+repr(value),call(c).get("error")=="invalid_sku_observation")
    c=deepcopy(args);c["summary"]["by_sku"].append(dict(s["by_sku"][0],category="다른분류"));check("duplicate_SKU_rejected",call(c).get("error")=="duplicate_sku_observation")
    for key in ["sealed_count","unclassified_count"]:
        c=deepcopy(args);c["summary"][key]=True;check("bool_"+key+"_rejected",call(c).get("error")=="invalid_settlement_summary")
    for key in ["requested_time","sample_time"]:
        c=deepcopy(args);c["summary"][key]["start"]=True;check("bool_"+key+"_rejected","error" in call(c))
    c=deepcopy(args);c["summary"]["sample_time"]={"start":-1,"end":9999};check("negative_sample_time_rejected","error" in call(c))
    c=deepcopy(args);c["summary"]["requested_time"]={"start":6400,"end":6399};check("reversed_request_window_rejected","error" in call(c))
    c=deepcopy(args);c["summary"]["sample_time"]=None;check("positive_counts_without_sample_rejected","error" in call(c))
    c=deepcopy(args);c["summary"]["sample_time"]={"start":10001,"end":10002};check("positive_counts_outside_sample_rejected","error" in call(c))
    c=deepcopy(args);c["summary"].update(coverage="partial",sample_time=None,by_sku=[],by_category={},sealed_count=0,unclassified_count=0);check("empty_partial_has_no_candidates",call(c).get("candidates")==[])
    c=deepcopy(args);c["summary"]["by_sku"][1].update(name="SYN_PRIVATE_NAME",buyer="SYN_PRIVATE_BUYER",wallet="SYN_PRIVATE_WALLET",rank=-999,score=999999,planned_units=99);c["private_cash"]="SYN_PRIVATE_CASH";o=call(c);check("untrusted_names_cash_rank_quantity_fields_not_forwarded",o==out and "SYN_PRIVATE" not in json.dumps(o))
    c=deepcopy(args);c["summary"]["by_category"]={"임의순위조작":999999};o=call(c);check("category_totals_mismatch_rejected",o.get("error")=="inconsistent_category_totals","integrity_fix",observed=o)
    for bad in [None,{"식품>가상계란>계란":True},{"식품>가상계란>계란":0}]:
        c=deepcopy(args);c["summary"]["by_category"]=bad;check("invalid_category_totals_"+repr(bad),call(c).get("error")=="invalid_category_totals")
    c=deepcopy(args);c["summary"]["by_sku"][1]["sku"]="0x"+"ab"*20;o=call(c);check("wallet_shaped_identifier_not_forwarded","error" in o or "0x"+"ab"*20 not in json.dumps(o),"privacy_goal","reject noncatalog identifiers",o.get("status"))
    c=deepcopy(args);c["summary"]["by_sku"][1]["count"]=2001;categories(c["summary"]);o=call(c);check("impossible_four_page_count_rejected","error" in o,"sample_integrity_goal","upstream maximum2000rows",o.get("status"))
    for known_count in [1997,1998]:
        c=deepcopy(args);c["summary"]["by_sku"]=[dict(s["by_sku"][0],count=known_count)];categories(c["summary"]);o=call(c)
        check("sum_including_sealed_unknown_"+str(known_count+3),o.get("status")=="planning_only" if known_count==1997 else "error" in o,"sample_integrity_goal",observed=o.get("status"))
    c=deepcopy(args);c["summary"]["mode"]="public_market_sample";o=call(c);scopes.append({"probe":"historical_well_formed_public_summary","accepted":o.get("status")=="planning_only","provisional":o.get("provisional"),"times":o.get("requested_time"),"conclusion":"Preserves timestamps but has no now/max-age/source-auth gate. Historical plans are not current recommendations."})
    c=deepcopy(args);c["summary"]["by_sku"][1]["category"]="조작한 공개분류";categories(c["summary"]);o=call(c);scopes.append({"probe":"internally_consistent_counterfeit_category","accepted":o.get("status")=="planning_only","conclusion":"Self-consistent inputs are not authenticated catalog records. An immutable validated upstream result must be bound to input for trusted planning."})
    # Cached public aggregate: no new read of a ledger, no own/private inventory filter.
    qa=OP/"runtime/qa-public-settlements-v2-20261125";proof=json.loads((qa/"qa-proof.json").read_text());cache=qa/"real-public-call-result.json";assert hashlib.sha256(cache.read_bytes()).hexdigest()==proof["files"]["real-public-call-result.json"]
    captured=json.loads(cache.read_text());public=captured["result"]["result"];assert captured["logic_sha256"]=="5f8641150e3cb9dfc27d6d8d78e791eb02d88ad60c39ba94a8416ba22cb50846"
    assert set(public)=={"mode","requested_time","sample_time","coverage","by_sku","by_category","sealed_count","unclassified_count"}
    cached_plan=call({"summary":public,"existing_skus":[]})
    check("cached_validated_v2_public_output_schema_accepts",cached_plan.get("status")=="planning_only","cached_public_compatibility",observed=cached_plan.get("status"))
    check("cached_plan_selects_one_unit_per_full_category",len({x["category"] for x in cached_plan.get("candidates",[])})==len(cached_plan.get("candidates",[])) and all(x["planned_units"]==1 for x in cached_plan.get("candidates",[])),"cached_public_compatibility")
    cached_artifact={"offline_cached_public_aggregate_only":True,"new_API_calls":0,"source_summary_logic_sha256":captured["logic_sha256"],"source_artifact_sha256":hashlib.sha256(cache.read_bytes()).hexdigest(),"source_requested_time":public["requested_time"],"source_public_settlement_count":sum(x["count"] for x in public["by_sku"]),"existing_skus_input":[],"existing_filter_is_test_assumption_not_actual_stock":True,"newness_for_outseop_r4_verified":False,"plan":cached_plan}
    (ROOT/"cached-public-shape-compatibility.json").write_text(json.dumps(cached_artifact,ensure_ascii=False,indent=2)+"\n")
    result={"version":2,"source_logic_sha256":EXPECTED,"source_unchanged":True,"checks":checks,"scope_probes":scopes,"totals":{g:{"passed":sum(x["passed"] for x in checks if x["group"]==g),"failed":sum(not x["passed"] for x in checks if x["group"]==g)} for g in sorted({x["group"] for x in checks})},"source_authenticity_verified_by_function":False,"held_SKU_list_fetched_from_any_server":False,"private_cash_or_customer_data_used":False,"general_Toolbox_calls":0,"market_API_calls":0,"model_calls":0,"production_ready":False}
    (ROOT/"independent-qa-results.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    assert hashlib.sha256((tool/"logic.py").read_bytes()).hexdigest()==EXPECTED
    print(json.dumps({"totals":result["totals"],"source_unchanged":True,"cached_public_candidate_count":len(cached_plan.get("candidates",[])),"general_calls":0,"market_API_calls":0,"production_ready":False}))

if __name__=="__main__":main()
