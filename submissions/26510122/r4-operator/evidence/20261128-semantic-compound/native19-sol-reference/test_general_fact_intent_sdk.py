"""Isolated ordinary SDK regression for the published semantic sources."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time

WORK=Path(__file__).resolve().parent
OP=WORK.parents[2]

class NoWallet:
    def grant(self,name,permission,timeout):
        if any(permission.get(k) for k in ('wallet','identity','network','write','exec','handles','pay_limit')):
            raise AssertionError('unexpected tool capability')
        return None


def source_copy(src, dst, name):
    files={leaf:(src/leaf).read_bytes() for leaf in ('logic.py','permission.yml','test.py','forge.json')}
    forge=json.loads(files['forge.json'])
    if forge['tool'] != name or forge['sha256']!={leaf:sha256(content).hexdigest()
              for leaf,content in files.items() if leaf!='forge.json'}:
        raise ValueError('native manifest mismatch')
    dst.mkdir()
    for leaf,content in files.items():
        path=dst/leaf
        path.write_bytes(content)
        path.chmod(0o400)


def fixture(now):
    def offer(number, name, category, price, grade):
        return dict(unit_ref=f'private-ref-{number}', sku=f'G{number:08X}', name=name,
            category_path=category, state='available', grade=grade, price_credits=price,
            standard_fee_credits=91, expires_at=None)
    return {'schema':'outseop-r4.customer-offers.v1','shop':'outseop-r4','observed_at':now-1,
            'valid_until':now+120,'units':[
                offer(1,'침대용 매트리스 패드',['가구','침대'],3200,'A'),
                offer(2,'침구 이불커버',['생활용품','침구'],1800,'B'),
                offer(3,'침구 장식 쿠션',['생활용품','침구'],6100,'C')]}


def invoke_suite(root,native,dependency):
    sys.path.insert(0,str(OP/'kit'))
    import agent_kit
    agent_kit.mk.LOG_FILE=None
    tools=root/'tools'
    tools.mkdir()
    source_copy(native,tools/'semantic_candidates','semantic_candidates')
    source_copy(dependency,tools/'public_catalogue','public_catalogue')
    prior=tools/'semantic_candidates_v4'
    prior.mkdir()
    baseline=(OP/'deploy/public_catalogue_runtime_semantic_v4/semantic/logic.py').read_bytes()
    if sha256(baseline).hexdigest()!='01e59f9b5e06b0402a669bfbd9c78e350c9cb32e9c65bfd111fdf5ac1a74b39c':
        raise ValueError('wrong parent')
    (prior/'logic.py').write_bytes(baseline)
    (prior/'logic.py').chmod(0o400)
    inputs=root/'host_inputs'
    inputs.mkdir(mode=0o700)
    fs=inputs/'customer_offer_context.json'
    fs.write_text(json.dumps(fixture(int(time.time())),ensure_ascii=False))
    fs.chmod(0o400)
    context={'name':'outseop-r4','market':'https://example.invalid','tokens':{},
             'addresses':{},'signer':NoWallet()}
    box=agent_kit.Toolbox(root,context)
    groups=[{'product_phrase':'침대','queries':['침대']},{'product_phrase':'침구','queries':['침구']}]
    def call(text, args, *, snapshot=None):
        if snapshot is not None:
            fs.chmod(0o600)
            fs.write_text(json.dumps(snapshot,ensure_ascii=False))
            fs.chmod(0o400)
        answer=box.run('semantic_candidates','call',{'op':'semantic_candidates','text':text,**args})
        assert answer.get('ok') is True and not answer.get('printed'), type(answer.get('error')).__name__
        return answer['result']
    compound='침대와 침구 재고와 가격을 알려주세요'
    output={'native_version':box.tools['semantic_candidates']['version'],'cases':{}}
    observations=output['cases']
    original=call('침대 재고와 가격을 알려주세요',groups[0])
    observations['legacy_single']=original['status']=='rendered' and 'G00000001' in original['reply']
    if output['native_version']<5:
        original_compound=call(compound,{'product_phrase':'침대','queries':['침대','침구']})
        observations['original_compound_denied']=original_compound.get('reason')=='unsupported_request'
        return output
    both=call(compound,{'groups':groups})
    text=both.get('reply','')
    observations['compound_two_sources']=(both['status']=='rendered' and len(text)<=450 and
        all(s in text for s in ('G00000001','G00000002','3,200','1,800','A등급','B등급')) and
        'private-ref-' not in text and '참고' in text and '확인되지' in text and
        all(text.count(f'G{n:08X}')<=1 for n in range(1,4)))
    for label,question in (
        ('negative','침대 말고 침구 재고와 가격을 알려주세요'),
        ('allergy','침대와 침구 알레르기 안전한 것만 재고와 가격을 알려주세요'),
        ('brand','침대와 침구 특정브랜드 제품만 재고와 가격을 알려주세요'),
        ('financial','침대와 침구 재고를 확인 후 결제권을 보내주세요'),
        ('same','침대와 침구 정확히 동일한 제품만 가격을 알려주세요'),
        ('group_specific','침대 A등급과 침구 B등급 가격을 알려주세요'),
        ('private','침대와 침구 private-ref-1 재고와 가격을 알려주세요'),
        ('explicit','침대와 침구 G00000001 재고와 가격을 알려주세요')):
        observations[label]=call(question,{'groups':groups}).get('status')=='unavailable'
    warranty=call(compound+'. 보증도 궁금해요.',{'groups':groups})
    output['warranty_observation']={'status':warranty.get('status'),'reason':warranty.get('reason')}
    crowded=fixture(int(time.time()))
    base=crowded['units'][0]
    for number,name in enumerate(('침대 프레임','침대 매트리스','침대 헤드보드'),start=11):
        crowded['units'].append(dict(base,unit_ref=f'crowded-{number}',sku=f'G{number:08X}',name=name))
    rich=call(compound,{'groups':groups},snapshot=crowded)
    rich_text=rich.get('reply','')
    observations['crowded_keeps_both']=(rich.get('status')=='rendered' and 'G00000002' in rich_text
        and any(f'G{n:08X}' in rich_text for n in (1,11,12,13)))
    long=fixture(int(time.time()))
    for row in long['units']:
        row['name'] = (row['name'] + ' 상품 세부 규격 '*7).strip()
    length=call(compound,{'groups':groups},snapshot=long)
    length_text=length.get('reply','')
    observations['long_title_complete']=(length.get('status')=='rendered' and len(length_text)<=450
        and length_text.endswith('원하는 SKU로 구매 조건을 다시 문의해 주세요.')
        and 'G00000001' in length_text and 'G00000002' in length_text)
    rice=fixture(int(time.time()))
    rice['units']=[
        dict(rice['units'][0],name='쌀 백미 5kg',category_path=['식품','쌀'],price_credits=6400),
        dict(rice['units'][1],name='쌀 백미 2kg',category_path=['식품','쌀'],price_credits=2800),
    ]
    rice_args={'groups':[{'product_phrase':'쌀','queries':['쌀','백미']}]}
    original_rice='쌀 재고와 가격을 알려주세요. 쌀은 어떤 상품이 있나요? 결제는 나중에 할게요.'
    repetition=call(original_rice,rice_args,snapshot=rice)
    result_text=repetition.get('reply','')
    repeated_ok=(repetition.get('status')=='rendered' and '확인되지' in result_text
        and all(value in result_text for value in ('G00000001','6,400','G00000002','2,800'))
        and len(result_text)<=450)
    if output['native_version']==6:
        observations['v6_repetition_reproduced']=repetition.get('reason')=='unsupported_request'
        return output
    observations['repeated_single_affirmative']=repeated_ok
    for label,suffix in (
        ('repeated_price_limit_not_dropped','쌀은 1,000크레딧 이하만 있나요?'),
        ('repeated_negation_not_dropped','쌀은 말고 다른 상품이 있나요?'),
        ('repeated_allergy_not_dropped','쌀은 알레르기 없는 상품이 있나요?'),
        ('repeated_exact_not_dropped','쌀은 정확히 동일한 제품만 있나요?'),
        ('repeated_finance_not_dropped','쌀은 어떤 상품이 있나요? 결제권을 보내주세요.'),
        ('repeated_other_product_not_dropped','쌀과 우유는 어떤 상품이 있나요?'),
    ):
        result=call('쌀 재고와 가격을 알려주세요. '+suffix,rice_args)
        observations[label]=result.get('status')=='unavailable'
    now = int(time.time())
    rice["units"][0]["expires_at"] = now + 86400
    fact_query = "쌀을 알아보고 있어요. 지금 쌀 재고와 가격 및 소비기한을 알려주세요."
    candidate = call(fact_query + " 재고가 있으면 그때 결제를 검토할게요.", rice_args, snapshot=rice)
    reply = candidate.get("reply", "")
    observations["facts_and_consider_later"] = (candidate.get("status") == "rendered"
        and all(value in reply for value in ("G00000001", "6,400", "A등급", "참고"))
        and "private-ref-" not in reply)
    for label, request in (
        ("actual_checkout_stays_unavailable", fact_query + " 재고가 있으면 결제권을 보내주세요."),
        ("actual_transfer_stays_unavailable", fact_query + " 가능하면 송금해 주세요."),
        ("warranty_condition_stays_unavailable", fact_query + " 보증이 확실한 경우만 보여주세요."),
        ("minimum_life_not_ignored", "쌀을 알아보고 있어요. 쌀은 최소 7일 이상 남은 상품만 보여주세요."),
        ("mixed_unknown_reference_stays_unavailable", "쌀을 알아보고 있어요. 다른 우유도 쌀 가격과 함께 알려주세요."),
    ):
        observations[label] = call(request, rice_args).get("status") == "unavailable"
    mixed = call("쌀 재고와 가격, 소비기한을 알려주세요. 재고가 있으면 결제서도 부탁해요.", rice_args)
    hold = mixed.get("payment_request") or {}
    mixed_reply = mixed.get("reply", "")
    observations["mixed_facts_document_is_not_issued"] = (mixed.get("status") == "rendered"
        and hold.get("status") == "not_issued"
        and hold.get("reason") in {"product_selection_required","financial_verification_required"}
        and all(v in mixed_reply for v in ("G00000001", "6,400", "발행하지 않았습니다"))
        and len(mixed_reply) <= 450 and "private-ref-" not in mixed_reply)
    visit = call("쌀을 보러 가게에 왔습니다. 지금 쌀이 있으면 재고와 가격, 유통기한을 알려주시고, 결제 서도 부탁드립니다.", rice_args)
    visit_hold = visit.get("payment_request") or {}
    observations["visit_intro_mixed_document_is_not_issued"] = (
        visit.get("status") == "rendered" and visit_hold.get("status") == "not_issued"
        and all(v in visit.get("reply", "") for v in ("G00000001", "6,400", "발행하지 않았습니다")))
    hidden = call("쌀 재고와 가격을 알려주세요. 결제서는 부탁하지만 알레르기 없는 상품만 보여주세요.", rice_args)
    observations["document_suffix_must_not_swallow_allergy"] = hidden.get("status") == "unavailable"
    if os.environ.get("R4_VERIFY_REFERENCE_FALLBACK")=="1":
        remainder = " 지금 쌀 재고와 정확한 상품명, 가격 및 소비기한을 알려주시고, 결제 서도 부탁드립니다."
        projected = call("잠깐 들른 참입니다." + remainder, rice_args)
        text = projected.get("reply", "")
        observations["reference_fallback_explicit_uncertainty"] = (
            projected.get("status") == "rendered" and
            (projected.get("payment_request") or {}).get("status") == "not_issued" and
            "관련" in text.splitlines()[0] and "조건" in text.splitlines()[0] and
            all(v in text for v in ("G00000001", "6,400", "발행하지 않았습니다")))
        for label, prefix in (
            ("reference_fallback_price_bound", "정한 가격은 3,200크레딧입니다."),
            ("reference_fallback_allergy", "알레르기 조건부터 확인합니다."),
            ("reference_fallback_exact_and_no_substitute", "정확히 동일한 제품만 찾습니다."),
            ("reference_fallback_refund", "먼저 환불을 해 주세요."),
        ):
            observations[label] = call(prefix + remainder, rice_args).get("status") == "unavailable"
    if os.environ.get("R4_VERIFY_CATEGORY_OVERLAY")=="1":
        context = fixture(int(time.time()))
        context["units"] = [dict(context["units"][0], name="현미 혼합곡", category_path=["식품/쌀"],
                                 price_credits=6400, expires_at=int(time.time())+86400)]
        reference = ("잠깐 들른 참입니다. 지금 쌀 재고와 정확한 상품명, 가격 및 소비기한을 "
                     "알려주시고, 결제 서도 부탁드립니다.")
        decoded = call(reference,rice_args,snapshot=context)
        notice = decoded.get("reply","")
        observations["reference_slash_category"] = (decoded.get("status")=="rendered"
            and (decoded.get("payment_request") or {}).get("status")=="not_issued"
            and all(x in notice for x in ("현미 혼합곡","G00000001","6,400","조건","발행하지 않았습니다")))
        for label, field, trust_ref in (
            ("reference_bad_delimiter_not_split","쌀/[식품]", "private-reference-1"),
            ("reference_individual_ref_not_split","쌀/ABCD", "ABCD"),
            ("reference_compact_ref_not_split","쌀/AB/CD", "ABCD"),
            ("reference_control_not_split","쌀/식품"+chr(1), "private-reference-1"),
        ):
            sample = dict(context,units=[dict(context["units"][0],category_path=[field],unit_ref=trust_ref)])
            denied = call(reference,rice_args,snapshot=sample)
            observations[label] = denied.get("status")=="unavailable"
        stale = dict(context,observed_at=int(time.time())-2,valid_until=int(time.time())-1)
        observations["reference_preserves_ttl"] = call(reference,rice_args,snapshot=stale).get("status")=="unavailable"
    return output


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--semantic',type=Path,required=True)
    ap.add_argument('--catalogue',type=Path,required=True)
    args=ap.parse_args()
    with tempfile.TemporaryDirectory(prefix='r4-compound-sdk-') as temp:
        result=invoke_suite(Path(temp),args.semantic,args.catalogue)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    if not all(result['cases'].values()):
        raise SystemExit(1)

if __name__=='__main__':
    main()
