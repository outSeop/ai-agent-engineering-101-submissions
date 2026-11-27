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
OP=WORK.parents[1]

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
