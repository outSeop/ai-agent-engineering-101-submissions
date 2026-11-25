from pathlib import Path
import json,hashlib
ROOT=Path(__file__).resolve().parent
h=(ROOT/'ordinary_toolbox_qa.py').read_text().split('\nwith Fixture() as f:',1)[0]
ns={'__file__':str(ROOT/'ordinary_toolbox_qa.py')};exec(compile(h,'unchanged_host_fixture','exec'),ns)
F=ns['Fixture'];raw=ns['raw'];sha=ns['sha'];findings=[]
for label,edit in [('incorrect_price',lambda s:s.replace('상품가 100 크레딧','상품가 1 크레딧')),('different_SKU',lambda s:s.replace('SKU G00000001','SKU G00000002')),('exaggerated_refund',lambda s:s.replace('통합 승인과 실제 환불 송금 연결은 개발 중입니다.','환불은 이미 모두 송금 완료했습니다.'))]:
 with F() as f:
  f.stage();original=f.staged['after_card_json'];altered=edit(original);assert altered!=original
  f.staged['after_card_json']=altered;f.after=altered.encode();f.staged['after_sha256']=sha(f.after)
  data=raw(f.staged);f.record=sha(data);f.stagepath=f.root/'card_update_stage'/(f.record+'.json');f.stagepath.write_bytes(data)
  f.fresh_and_grant();o=f.apply()
  findings.append({'probe':label,'host_fake_deliberately_authorized_wrong_replacement':True,'status':o['status'],'interpretation':'Apply trusts protected host authority semantic review. It does not itself prove generated stage provenance or compare rendered SKU/price/refund prose to selected source rows. No real authority or market data used.'})
(ROOT/'supplemental-authority-scope.json').write_text(json.dumps({'ordinary_Toolbox_call':True,'synthetic_only':True,'findings':findings,'market_calls':0,'model_calls':0},ensure_ascii=False,indent=2)+'\n')
print(json.dumps(findings,ensure_ascii=False))
