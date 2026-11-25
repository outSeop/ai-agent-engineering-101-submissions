from pathlib import Path
import json,time
ROOT=Path(__file__).resolve().parent
prefix=(ROOT/'ordinary_toolbox_qa.py').read_text().split('\nwith Fixture() as f:',1)[0]
ns={'__file__':str(ROOT/'ordinary_toolbox_qa.py')};exec(compile(prefix,'independent_host_fixture','exec'),ns)
F=ns['Fixture'];raw=ns['raw'];sha=ns['sha'];checks=[];observations=[]
def ck(case,passed,group='contract',observed=None):checks.append({'case':case,'passed':bool(passed),'group':group,'observed':observed})
def legacy(f):
 f.policies={'mileage':'정상 정산·인도 후 상품 기준가의 1%를 적립합니다. 마일리지는 7일 동안 다음 구매부터 사용됩니다.','wait':'실제 앞선 결제로 발급된 대기권은 120초 안에 같은 상품을 다시 문의해 구매할 때 기준가의 1%를 할인합니다.','refund':'원결제 증빙이 필요하며 승인 후 원송금 주소로 처리합니다.'}
 f.intro='처음 방문 안내입니다.\n\n';f.suffix='\n\n구매 전 실제 조건을 확인하세요.'
 f.card={'name':'outseop-r4','description':f.intro+f.old+f.suffix,'url':'https://example.invalid/agent','skills':[{'id':'a2a-checkout','description':'상품과 조건 확인'},{'id':'repeat-benefits','description':f.policies['mileage']+' '+f.policies['wait']+' 마일리지와 대기할인은 함께 쓸 수 있습니다.'},{'id':'refund-review','description':'48시간 내 증빙 검토. '+f.policies['refund']}],'x-preserve':'synthetic-public-only'}
 f.t=int(time.time());f.init()
def event(f,eventid):return json.loads((f.root/'card_publication'/(eventid+'.json')).read_text())
def handoff(f,eventid):
 e=event(f,eventid);t=max(int(time.time()),e['recorded_at']);h={'schema':'outseop-r4.card-publication-handoff.v1','shop':'outseop-r4','owner':'native','event':eventid,'card_sha256':e['after_sha256'],'issued_at':t,'valid_until':t+30};(f.root/'host_inputs/card_publication_handoff.json').write_bytes(raw(h));return h
def start(f):
 legacy(f);f.initial=f.before;f.originalskills=f.card['skills'];f.originalpolicies=dict(f.policies);f.stage();f.fresh_and_grant();o=f.apply();return o
with F() as f:
 first=start(f);ck('initial_legacy_intro_skills_only_native_apply',first['status']=='applied',observed=first)
 e1=first['event'];firstcard=(f.root/'card.json').read_bytes();j1=event(f,e1);card1=json.loads(firstcard)
 ck('initial_nonoffer_prose_exact_preserved',card1['description'].endswith(f.intro+f.suffix))
 ck('first_native_keeps_exact_three_skills',card1['name']=='outseop-r4' and card1['skills']==f.originalskills and len(card1['skills'])==3)
 ck('event_block_includes_native_policy_paragraphs',all(word in j1['block']['text'] for word in ['7일','120초','48시간','송금 연결은 개발 중']))
 handoff(f,e1);g=f.call('publish_shop_info',{});ck('first_guard_owns_and_writes_nothing',g['status']=='skipped' and (f.root/'card.json').read_bytes()==firstcard,observed=g)
 # Round2 uses exact committed whole block, current native card and NEW merch SKU.
 f.card=card1;f.before=firstcard;f.old=j1['block']['text'];f.t=int(time.time());f.init();assert f.before==firstcard
 f.stage(['G00000002']);f.fresh_and_grant();f.auth['head']=e1
 # Native paragraph anchors would overlap old merch block. Do not hide this issue.
 native_policies={'mileage':'정상 정산과 인도 후 기준가의 1% 마일리지를 지급하며, 7일 동안 다음 거래에 쓸 수 있습니다.','wait':'실제 앞선 처리로 지연된 경우 발급한 1% 대기권은 발급 후 120초 이내 같은 상품 재문의 시 기존 마일리지와 함께 쓸 수 있습니다.','refund':'환불 대상은 인도 후 48시간 내 확인된 초기 문제 또는 판매자 귀책 미인도입니다.'}
 f.auth['details']['policies']=native_policies;f.writeauth();o=f.apply();ck('description_policy_anchors_support_second_refresh',o['status']=='applied','issuer_limit',o);ck('failed_anchor_does_not_modify_first_card',(f.root/'card.json').read_bytes()==firstcard)
 f.auth['details']['policies']=f.originalpolicies;f.writeauth();second=f.apply();ck('second_native_refresh_with_preserved_skill_anchors',second['status']=='applied',observed=second)
 e2=second['event'];secondcard=(f.root/'card.json').read_bytes();j2=event(f,e2);card2=json.loads(secondcard)
 ck('second_refresh_real_merch_changed','SKU G00000002' in j2['block']['text'] and 'SKU G00000001' not in j2['block']['text'])
 ck('second_native_exact_skills_and_other_fields',card2['skills']==f.originalskills and all(card2[k]==card1[k] for k in card1 if k!='description'))
 ck('rendered_policy_clauses_unchanged_once',all(card2['description'].count(s)==1 and card1['description'].count(s)==1 for s in native_policies.values()))
 ck('second_nonoffer_intro_suffix_preserved',f.intro in card2['description'] and card2['description'].endswith(f.suffix))
 ck('event2_links_active1_and_exact_prior_block',j2['previous_active']==e1 and j2['prior_block']==j1['block'])
 handoff(f,e2);g2=f.call('publish_shop_info',{'description':'가짜 고객 변경'});ck('second_guard_bound_to_new_head',g2['status']=='skipped' and g2['event']==e2 and (f.root/'card.json').read_bytes()==secondcard,observed=g2)
 past=f.call('apply_staged_card',{'op':'apply','record_id':j1['record_id']});ck('past_record_rejected_after_refresh',past['status']=='rejected' and (f.root/'card.json').read_bytes()==secondcard,observed=past)
 rb=f.rollback(e2);ck('rollback_refresh_restores_prior_native_exact',rb['status']=='rolled_back' and (f.root/'card.json').read_bytes()==firstcard,observed=rb)
 handoff(f,rb['event']);gr=f.call('publish_shop_info',{});ck('guard_accepts_rollback_active_prior',gr['status']=='skipped' and (f.root/'card.json').read_bytes()==firstcard)
 observations.append({'initial':first,'round2':second,'rollback':rb,'original_skills_preserved':True,'two_stage_records_real_tool_calls':True,'description_policy_anchor_failure':o,'skill_policy_anchors_allowed':True})
# Deliberately wrong host grants still must not accept non-rendered blocks for actual legacy shape.
for label,edit in [('lower_price',lambda s:s.replace('상품가 100 크레딧','상품가 1 크레딧')),('lookalike_price',lambda s:s.replace('상품가 100 크레딧','상품가 １００ 크레딧')),('different_SKU',lambda s:s.replace('SKU G00000001','SKU G00000002')),('refund_completed',lambda s:s.replace('통합 승인과 실제 환불 송금 연결은 개발 중입니다.','환불은 모두 송금 완료했습니다.')),('policy_omitted',lambda s:s.replace('마일리지를 지급하며, 7일 동안 다음 거래에 쓸 수 있습니다.','')),('policy_moved',lambda s:s.replace('통합 승인과 실제 환불 송금 연결은 개발 중입니다.','')+'\n통합 승인과 실제 환불 송금 연결은 개발 중입니다.'),('intro_removed',lambda s:s.replace('처음 방문 안내입니다.',''))]:
 with F() as f:
  legacy(f);f.stage();s=f.staged;candidate=json.loads(s['after_card_json']);altered_description=edit(candidate['description']);assert altered_description!=candidate['description'];candidate['description']=altered_description;altered=raw(candidate).decode();s['after_card_json']=altered;s['after_sha256']=sha(altered.encode());data=raw(s);f.record=sha(data);f.stagepath=f.root/'card_update_stage'/(f.record+'.json');f.stagepath.write_bytes(data);f.after=altered.encode();f.fresh_and_grant()
  # Host deliberately approves exact counterfeit text including delimiter, so simple hash mismatch is not the only rejection.
  new=json.loads(f.after)['description'];retained=f.intro+f.suffix;assert new.endswith(retained) or label in ('policy_moved','intro_removed')
  prefixlen=len(new)-len(retained)-2 if new.endswith('\n\n'+retained) else len(new)
  f.auth['details']['replacement_sha256']=sha(new[:prefixlen].encode());f.writeauth();o=f.apply();ck('reject_nonrendered_'+label,o['status']=='rejected' and (f.root/'card.json').read_bytes()==f.before,observed=o)
result={'ordinary_official_Toolbox_call':True,'manual_testing_flag':False,'synthetic_Fake_only':True,'checks':checks,'totals':{g:{'passed':sum(x['passed'] for x in checks if x['group']==g),'failed':sum(not x['passed'] for x in checks if x['group']==g)} for g in sorted({x['group'] for x in checks})},'lifecycle_observations':observations,'actual_prod_card_write':False,'market_calls':0,'model_calls':0,'tokens_wallet_customer_data_loaded':False}
(ROOT/'lifecycle-qa-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'totals':result['totals'],'failed':[x for x in checks if not x['passed']]},ensure_ascii=False))
