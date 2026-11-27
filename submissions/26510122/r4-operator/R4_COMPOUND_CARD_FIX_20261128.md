# R4 문의·카드 수정과 HOST 코드 정리

확인 시각: 2026-11-28 04:01 KST. 개인 저장소 outSeop/ai-agent-engineering-101-submissions,
round-4-26510122 브랜치의 작업이다. 공용 원본으로 제출 PR을 열지 않았다.

## 운영에 적용한 내용

- 두 상품군 문의를 수업 모델이 한 번에 나눠 고르고, 도구가 실제 관련 SKU·등급·가격을 반환한다.
  침대 패드를 침대 본품이라고 확정하거나 모든 요청 조건을 충족했다고 보장하지 않는다.
- 단일 상품의 지원되는 긍정 반복 질문과 결제 유보 문구도 처리한다. 전체 자연어 반복을 해결한 것은 아니다.
- 카드 대표상품 선택은 비교 자료를 처음부터 제공해 모델 실제 호출을 최대1회로 줄였다.
  원 genuine stage·fresh 재검사·head/CAS·권한·apply 검사는 유지한다. 기존35초 예산과600초 재시도 간격도 유지한다.
- 기존 재고 cache의 v5 의존성은 price_context_runtime_v8b의 고정 reader로 분리된 상태를 유지한다.

새 문의는 18810의 공통 HOST 리스너를 사용한다. 기존18809→18808→18807→18806→18805의
대화 저장소는 원 프로세스를 그대로 두고, taskId를 바꾸지 않고 전달한다. 기존 두 task의 GetTask 결과가
전환 전과 동일함을 공개 URL에서 확인했다. 원 main·worker·CF·기존 front를 재시작하지 않았다.

## 코드 정리

수정할 위치를 `src/r4_operator_host/`로 모았다. 통신/이전 대화 전달/접속 준비 gate/전환 가드는
`front/` Python5개를 유지하고, 포트·경로·보존할 프로세스·모델 안내문은 고정 JSON 설정으로 분리한다.
`catalogue_protocol.py`는 고정 원본 프로토콜을 재사용하는46줄 인자 연결 코드다.

`release_builder.py`는 검토된 base·작은 HOST 변경·수업 모델이 만든 원본 도구를 그대로 묶는다.
명세는 `deploy/release_specs/compound-cleanup-active.json`, 배포 출력은 Git에 넣지 않는
`runtime/releases/<명세SHA>/`다. 매 수정마다 runtime전체와 listener전체를 Git에 복제하지 않는다.
빌더는 기존 배포본을 검증해 재사용하며 덮어쓰지 않고, DB·키·시장·서비스·방화벽을 실행하지 않는다.

기존 deploy 버전은 프로세스가 참조하고 과정 증거이므로 보존했다. 현재 작업 위치로 다시 복제하지 않는다.
카드의 기존 불변 배포본 card_one_decision_runtime_v1과 기존 cache producer는 그대로 연결된다.

현재 배포:
- 명세/배포 ID: 4602965de6150eb00d8947f3cf432a87443847bea1dbdcc44bdfdd7931ba7213
- runtime SHA: 3da162a2042b424dfbe98e7366d527169d3267ee2d5b964a1e17e2c35782d1c7
- front SHA: 05198370b8449a132db5df758d6ada3e504d8283b02cc454809e9d1c7eaaf562
- 서비스: ourolabs-market-r4-compound2-front.service, PID1282150/NRestarts0
- 공개 URL: https://stable-leu-below-the.trycloudflare.com
- marker: r4-compound2-front-v1

새 listener는 요청만 처리하며 별도 매입/홍보 루프가 없다. 원 timer 추가·Codex 예약 홍보 재개·새 가입은 없다.
접속 준비 gate를 닫은 채 원5+CF+18809와 카드/지갑/URL을 검증하고10초 idle 후 exact own rule만
18809→18810으로 바꿨다. 공개 marker 확인 뒤에만 gate를 열었다. 한 번 새 task를 받은 뒤 원복하면
메모리 대화가 끊길 수 있으므로 신규 입장 기록이 있으면 역전환을 거절한다. 기존 task는 계속 전달한다.

## 검증

- 카드 독립7/7. 실제 수업 모델로 합성145후보→정식 stage/StageOrigin, 실제 호출1회.
  notes 생성부터 안전 영수증까지 약13.412초(도구/호스트 포함; 순수 모델 시간 아님). 실제 카드·금융 변경0.
  적용 후 기존 카드 timer의 여러 자연 갱신이 applied였다. 새 선택을 운영에서 강제하지 않았다.
- genuine semantic9: 원 SDK 시험과 독립19/19 통과. 도구 원본·forge기록은 byte 그대로 배포했다.
- packaging3/3, 공통front5/5, 최종 격리 SDK ASGI2/2. ASGI의 모델은 stub1회씩이며 실제 모델 성과로 세지 않는다.
- 기준6의 공통화 build는 원 runtime29파일이 byte 동일했다. 최종9는 작은 인자 연결과 모델 생성 도구만 교체했다.
- 공개 실제 수업 모델 검증: 두 상품군 문의10.0057초/2행, 지원되는 단일 반복 문의12.1881초/3행.
  각각 모델1회, 현재 SKU·등급·가격 일치, 금융동작0/checkout0. 296자/388자 실제 상태 응답만 추출했다.
- 기존18808·18809 두 task는 새경로 GetTask에서도 원 결과와 일치했다.
- DB quick_check=ok, DB inode·두 지갑 bytes/inode/device 유지. sale/lot/allocation/refund/
  welcome_award/ticket/account/customer_profile의 행수와 데이터가 점검 전과 동일했다.
  원가 하한·원 금융5소스·매입8·publisher9·기존5서비스 PID와 재시작 수·18809를 보존했다.
- cache145행/sidecar145행, TTL150와 SHA·시각 일치. 공개 카드200, outseop-r4/원 지갑 유지.

공개 점검4건은 실제 고객/매출에서 제외한다. 같은 점검 기간 미분류 문의1건이며 신규 구매자나 광고 전환을
입증하지 않는다. 누적 정산2/missing1 유지, 신규 정산은0이다.

## 남은 한계와 시도 기록

실제 미분류 원문1건을 외부 모델·고객 연락 없이 로컬 도구에 그대로 재생했지만 unsupported_request였다.
위 지원 범위의 합성/공개 성공을 그 원문의 해결로 합치지 않는다. 두 상품군과 반복·추가 조건을 섞은 문의,
확인하지 못한 보증·결제 조건은 계속 보류할 수 있다. 조건을 지우거나 확인되지 않은 상품을 약속하지 않는다.

실패한 genuine5의 그룹편향/가격줄 잘림, genuine7·8의 반복질문 실패, 원SDK 진입 전 HOST거절과
검증기 fixture/setup 오류를 별도로 보존했다. 최종9는 수업 모델이 이미 작성한217자 삭제안을 그대로 썼다.
HOST의 함수전체 교체 강제를 실제 함수 내부 literal변경 검사로 고친 뒤, 같은 제안을 원 SDK로 재실행했다.
추가 모델 판단/사업 코드 수작업 작성/SDK 수정/forge기록 위조는 없다. SDK진입 전 거절과 SDK시험 실패를 구분한다.

새 포럼 수요 매칭/cold-start와 별도 매입15/재무캠페인/관측hook는 이번에 활성화하지 않았다.
예약 r4/r4-2/r4-3은 재개하지 않았고 R3도 재가동하지 않았다.

## 다시 확인할 위치

- 현재 코드: src/r4_operator_host/README.md
- 현재 명세: deploy/release_specs/compound-cleanup-active.json
- 원 도구/출처: deploy/semantic_candidates_native_v9/, evidence/20261128-semantic-compound/
- 통합/보존 근거: evidence/20261128-runtime-refactor/
- 카드 검증: evidence/20261128-compound-card-fix/card-qa/, card-classroom-safe.json

빌드 재현(서비스/재가입/금융 실행 없음):
`.venv/bin/python -B src/r4_operator_host/release_builder.py --operator <OP> --descriptor <OP>/deploy/release_specs/compound-cleanup-active.json --expected-spec-sha 4602965de6150eb00d8947f3cf432a87443847bea1dbdcc44bdfdd7931ba7213`

배포·원복은 이전 listener를 멈추거나 gate 이력을 지우는 명령으로 대신하지 않는다.
