"""Export only previously redacted mock dialogue evidence and its readable report."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import statistics


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--operator',type=Path,required=True)
    p.add_argument('--session',type=Path,required=True)
    p.add_argument('--run',default='actual-class-decisions-final')
    args=p.parse_args()
    op,s=args.operator,args.session
    run=s/args.run
    rows=json.loads((run/'summary.json').read_text())
    assert len(rows)==7 and all(r['passed'] for r in rows),'Do not publish incomplete results as passed'
    dest=op/'logs/model-decisions-20261125/final'
    dest.mkdir(parents=True,exist_ok=True)
    titles={'purchase':'첫 구매·적립','selection':'용도에 맞는 상품 선택','negotiation':'저가 협상·견적 수락','benefits':'예약 대기·할인과 마일리지','refund':'증빙 없는 환불·검증 후 검토','replay':'중복 메시지·브로커 재생성','sdk':'공식 A2A HTTP 전달'}
    shutil.copy2(run/'summary.json',dest/'summary.json')
    shutil.copy2(run/'source-hashes.json',dest/'source-hashes.json')
    shutil.copy2(s/'offline-final-validation.log',dest/'offline-validation.log')
    for name in ('installed-validation.log','services-final.json','preservation-final.json','source-normalization.json'):
        shutil.copy2(s/name,dest/name)
    for name in ('forge-decision-v7-offline.log',):
        shutil.copy2(s/'agent-work/codex-r4'/name,dest/name)
    trace_rows={}
    for r in rows:
        case=r['case']
        root=run/case
        src=root/('.kit/decision-trace-review.jsonl' if case=='sdk' else 'review.jsonl')
        shutil.copy2(src,dest/(case+'-review.jsonl'))
        trace_rows[case]=[json.loads(l) for l in src.read_text().splitlines()]
    times=[d['seconds'] for r in rows for d in r['dialogue']]
    checks=sum(len(r['checks']) for r in rows)
    text=[
        '# R4: 모델 판단·툴 집행 모의 대화 검증',
        '',
        '2026-11-25 · 구현: Codex GPT-6.2 Sol · 판단: 실제 수업 모델(`market` API)',
        '',
        '최종 일곱 시나리오가 모두 통과했다. 고객 발언은 사람이 작성한 모의 입력이며, 아래 모델의 행동 선택은 실제 수업 모델 응답이다. 툴의 계산·서명·정산은 격리된 가상 재고, 임시 서명키와 모의 원장에서 수행했다. 실제 고객 거래나 실제 송금으로 해석하면 안 된다.',
        '',
        'R3·R4 매매 서비스는 계속 중지한다. 실제 DB·기존 지갑·재고를 테스트에 사용하지 않았다. 수업 모델 접속을 위해 승인된 구매 불가 점검 URL만 잠시 사용한 뒤 닫았다. 원본 상세 추론과 인증값은 공개하지 않으며, 여기는 도구 행동과 고객에게 설명 가능한 짧은 요약만 담는다.',
        '',
        '## 역할 분담',
        '',
        '| 담당 | 하는 일 |',
        '|---|---|',
        '| 코드가 먼저 하는 조회 | 현재 재고·예약 상태·가격 범위·권리·기존 견적·혜택을 검증해 모델에 제공 |',
        '| 수업 모델 | 상품 선택, 제안 가격, 협상 후 재제안, 구매 응대, 환불 검토 요청, 일반 답변 결정 |',
        '| 툴 | 재고·원가 하한·구매 동의·고객 권리·중복을 검사하고 할인·마일리지 계산, 서명, 원 고객에게 원문 전달 |',
        '| 운영자 | 검증된 환불의 실제 송금 승인 |',
        '',
        '이 경로는 공식 forge 도구와 Python 브로커를 연결한 것이다. 별도 MCP 서버를 새로 만든 것은 아니다. 모델은 결제 JWT·권리코드·임의 목적지를 전달하거나 고쳐 쓰지 않는다.',
        '',
        '## 최종 결과',
        '',
        '| 시나리오 | 결과 | 모델 호출 | 고객 응답 시간(초) |',
        '|---|---|---:|---|',
    ]
    for r in rows:
        text.append(f"| {titles[r['case']]} | 통과 | {len(r['model_calls'])} | {', '.join(str(d['seconds']) for d in r['dialogue'])} |")
    text.extend([
        '',
        f'자동 검증 조건 {checks}개 통과. 로컬 회귀 테스트 48개와 공식 고객 코드의 모의 구매·정산·환불 흐름도 통과했다. 최종 대화 {len(times)}건의 응답 중앙값은 {statistics.median(times):.1f}초, 범위는 {min(times):.1f}~{max(times):.1f}초였다. 단일 모의 실행의 실측이며 일반적인 운영 성능을 보장하지 않는다.',
        '',
        '첫 구매 4,500 크레딧을 모의 정산·인도하면 45 마일리지를 1회 적립했다. 다음 거래에서 실제 예약 지연으로 받은 할인 45와 기존 마일리지 45를 함께 적용해 4,410 크레딧이 됐다. 환불은 증빙 없이는 접수하지 않았고, 확인된 고장·원 결제·권리 증빙이 있는 경우 검토만 접수했다. 실제 환불 송금은 0건이다.',
        '',
        '## 어떤 대화가 오갔나',
        '',
        '아래의 고객 문장은 작성한 테스트 입력이다. 모델 행은 실제 API가 선택한 행동이고, 고객 수신 행은 툴이 만든 응답을 비밀값만 가려 옮긴 것이다. 자동 조회와 모델이 선택한 조회를 구분했다.',
    ])
    for r in rows:
        case=r['case'];text.extend(['',f"### {titles[case]}",''])
        for e in trace_rows[case]:
            role,payload=e['role'],e['payload']
            if role=='customer':
                text.extend(['**고객 · 모의 입력**', '', '> '+payload['text'].replace('\n','\n> '),''])
            elif role=='model':
                if payload.get('invalid_output'):
                    text.append('- 수업 모델: 형식이 맞지 않아 실행하지 않고 재요청했다.')
                else:
                    action=payload.get('action');arguments=json.dumps(payload.get('args',{}),ensure_ascii=False)
                    text.append(f"- 수업 모델: `{action}` `{arguments}`. {payload.get('decision_summary','')}")
            elif role=='tool':
                action=payload.get('action');result=payload.get('result')
                origin='코드의 자동 조회' if payload.get('source')=='broker_prefetch' else '툴'
                if isinstance(result,dict) and result.get('outcome')=='context':
                    items=[{k:i[k] for k in ('sku','name','reference_price','stock_status','wait_eligible') if k in i} for i in result['inventory']]
                    text.append(f"- {origin} `{action}`: 재고 `{json.dumps(items,ensure_ascii=False)}`; 마일리지 {result['redeemable_mileage']}; 대기할인 {result['wait_discount']}; 기존 견적 `{json.dumps(result['prior_offer'],ensure_ascii=False)}`.")
                else:
                    status=(result or {}).get('outcome') if isinstance(result,dict) else payload.get('validation')
                    text.append(f'- {origin} `{action}`: `{status}`.')
            elif role=='customer_received':
                text.extend(['','**고객 수신 · 툴 원문(비밀값 마스킹)**','','> '+payload['reply'].replace('\n','\n> '),''])
                if payload.get('data'):
                    text.extend(['```json',json.dumps(payload['data'],ensure_ascii=False,indent=2),'```',''])
        text.extend(['**검증 항목**',''])
        for k,v in r['checks'].items():text.append(f'- `{k}`: {v}')
    text.extend([
        '',
        '## 실패를 통해 바꾼 부분',
        '',
        '| 관측된 실패 | 바꾼 부분 |',
        '|---|---|',
        '| 모델이 내부 요청 참조를 잘못 복사해 재제안이 거절됨 | 참조와 응답 목적지는 코드의 현재 요청에 묶고 모델 인자에서 제거 |',
        '| 이전 개발 지시 때문에 고객 응대 중 forge_tool을 시도함 | 공식 WORLD와 고객 응대용 판매 방침만 주입하고 개발 지시·기존 notes는 제외 |',
        '| 예약 중인 재고를 품절로 오해해 대기권이 누락됨 | 판매 가능·예약 중·대조 중을 구분하고 툴이 실제 활성 예약을 확인 |',
        '| 기존 견적 수락에 조회를 생략하고 SKU·가격을 다시 질문함 | 재고·혜택·기존 견적 조회를 코드가 먼저 수행 |',
        '| HTTP 평가기가 평평한 Task 응답만 가정해 실패함(툴 서명은 정상) | 공식 고객 코드와 같이 result.task 래퍼도 읽도록 평가기 수정 후 재검증 |',
        '',
        '실패 리뷰 로그는 [failures](logs/model-decisions-20261125/failures)에 보존했다. 실패를 실제 성공 거래처럼 집계하지 않았다.',
        '',
        '## 확인 범위와 다음 확인',
        '',
        '서명은 공개된 공식 고객 검증 함수로 확인했다. HTTP 시나리오는 공식 A2A ASGI, 보호된 ManagedMind/ManagedToolbox, 실제 수업 모델, 가상 시장을 함께 연결했고 고객에게 간 JWT가 툴 원문과 동일함을 검사했다. 재전송 시 새 결제권을 발급하지 않았고, 권리와 JWT가 모델 입력에 포함되지 않았음을 검사했다.',
        '',
        '모델 판단은 매번 달라질 수 있다. 이번 결과는 정해진 모의 입력의 관측이다. 실제 트래픽의 재구매율·수익·순위 효과나 장시간 운영 안정성은 아직 검증하지 않았다. 원가 하한은 이익 극대화 목표가 아니며, 협상 마진은 실거래 재개 후 별도 관측이 필요하다.',
        '',
        '사용자가 확인할 것: 상품·가격의 선택이 원하는 가게 방향인지, 협상 할인 폭이 적절한지, 환불 검토까지만 자동으로 진행하는 경계가 맞는지. 실제 서버 재가동은 이번 작업에 포함하지 않았다.',
        '',
        '## 재현과 증거',
        '',
        '- [최종 검증 조건·대화·시간](logs/model-decisions-20261125/final/summary.json)',
        '- [회귀 검증 원본 출력](logs/model-decisions-20261125/final/offline-validation.log)',
        '- [공식 로컬 forge 검증 출력](logs/model-decisions-20261125/final/forge-decision-v7-offline.log)',
        '- [검증한 소스 해시](logs/model-decisions-20261125/final/source-hashes.json)',
        '- [배포 시 파일 끝 빈줄만 제거한 AST 동일성 기록](logs/model-decisions-20261125/final/source-normalization.json)',
        '- [서비스 중지 확인](logs/model-decisions-20261125/final/services-final.json) · [기존 지갑·재고·원장 관측](logs/model-decisions-20261125/final/preservation-final.json)',
        '- 평가 실행기: `deploy/evaluate_model_decisions.py`; 실제 수업 모델 접속 조건이 필요하며 인증 토큰은 Git에 포함하지 않는다.',
        '',
    ])
    (op/'R4_MODEL_DECISIONS_20261125.md').write_text('\n'.join(text),encoding='utf-8')
    print(json.dumps({'scenarios':len(rows),'conditions':checks,'dialogues':len(times),'median_seconds':statistics.median(times),'report':str(op/'R4_MODEL_DECISIONS_20261125.md')},ensure_ascii=False))


if __name__=='__main__':main()
