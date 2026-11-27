# R4 상품 조회의 결제 표현 오차단 수정

확인 시각: 2026-11-27 13:45:59 KST. 실제 운영은 같은 로컬 Ubuntu WSL, outseop-r4, 같은 지갑·DB·공개 주소를 이어 쓴다.

## 결과

“소이밀크 재고와 가격 보여 주세요. 결제는 나중에 할게요.”라는 운영자 정보 조회에서 실제 수업 모델이 `두유·콩음료`를 골랐다. genuine semantic_candidates4가 현재 재고 후보 3개의 SKU·상품명·등급·가격을 검증해 공개 주소에서 10.9978초에 응답했다. 모델 1회, semantic 도구 1회, 금융 실행 0이다. 이전 운영자 task의 GetTask 응답 SHA도 전환 전과 같았다. 이 조회는 health-probes에 등록했으며 실제 구매자·정산으로 세지 않는다.

누적 실제 정산 2건·issued 1건, 마일리지 lot2·첫 구매 적립2·차감할당0·환불0이다. 이번 작업에서 신규 결제권·정산 증가는 확인되지 않았다. 기능 검증과 매출 효과는 별개다.

## 무엇을 수정했나

기존 semantic2는 원문에 결제 단어가 들어가면 공개 상품 조회도 막았다. 과거 비점검표시 4건이 이 첫 검사에서 거절됐고, 단어만 지워도 부정/연결 표현2·숫자/문장부호1·미지원속성1 때문에 계속 실패했다. 단어 일괄 삭제는 채택하지 않았다. 과거 snapshot과 현재 snapshot이 같은 건은 0/4이므로 현재 재고 검색을 과거 성공 재현으로 해석하지 않는다.

모델은 원문에 정확히 한 번 나오는 긍정 상품 구절 `product_phrase`와 유사 검색어 최대2개를 고른다. 도구는 원문 전체를 그대로 받아 그 구절이 실제 부분 문자열인지, 속성·가격·등급·수량·기한·제외·권한을 삼키지 않는지 확인한다. 좁게 정의한 완전한 결제 유보/절차 문의 문장만 별도로 처리하고 원문 조건 필터를 유지한다. 사전에 등록된 동의어 목록으로 모델 판단을 대체하지 않는다.

후보는 최신 공개 snapshot의 실제 상품명·카테고리와 검색어를 대조해서만 나온다. 정확한 동일상품/모든 조건 충족을 보장하지 않으며 후보 고지와 SKU 재문의 안내를 붙인다. semantic 답변으로 구매 대상이나 권리를 자동 기억하지 않는다. 실제 구매·발급·증빙·환불·개인정보 요청은 기존 보호 경로를 유지한다. 미해석 조건이나 복잡한 부정 표현은 여전히 보류될 수 있다.

모델 호출은 요청당 최대1회, 로컬 대기30초/요청 예산40초/800token, format repair0을 유지한다. 로컬 timeout은 원격 제공자 취소를 뜻하지 않는다. 늦은 결과로 금융 도구를 실행하지 않는다.

## 검증과 실패 기록

| 구분 | 결과 |
|---|---|
| genuine4 공식 Mind→forge_tool→SDK 자체 검사 | 통과 |
| 일반 dual SDK 합성 검사 | 25/25 (허용7·차단18) |
| 호스트 모의 검사 | 12/12 |
| 독립 SDK 검사 | 9/9 그룹·59 native 호출, 현재 공개146행 원시각 그대로 대조 |
| 실제 수업 모델 격리 canary | 10.3223초, 모델1·semantic1, 343자 genuine 응답과 동일 |
| 공개 접속 운영자 조회 | 10.9978초, 모델1·semantic1, 실제후보3·금융0 |
| listener/task/원 전환 검사 | 19/19 모의 검사 |
| 별도 전환 guard 회귀 | 18/18 모의 검사 |

개발 모델 요청은 사용자 지정 Sol, 실제 운영은 classroom `market`이다. 원 SDK7·원 public_catalogue8 exact4·원 dispatcher/worker/refund/가격 정책과 금융 source는 그대로다. business logic은 사람이 직접 수정하지 않고 원 Mind/forge 경로를 썼다. 외부 호스트 연결·안전검사·독립 테스트는 이와 구분한다.

첫 genuine3는 자체 검사만 통과한 채 고정 명사 목록/세 가지 문장에 묶여 실제 목표 문장에 실패해 배포하지 않았다. genuine4 첫 시도도 잘못된 합성 unit_ref 기대값으로 자체 검사에서 거절됐다. 원 실패 로그/출처 hash와 생성 파일을 별도 커밋으로 보존하고 모델이 수정했다. 공식 SDK가 삭제한 실패 staging은 복원했다고 주장하지 않는다.

첫 운영 전환도 public marker/card/pending 대조 실패로 자동 rollback됐다. 그 원 exception은 어느 필드가 달랐는지 보존하지 않아 원인은 확정하지 않는다. 기존 guard가 idle 이전 description을 계속 비교하는 소스 버그는 확인해 별도 transition-only v2로 고쳤다. idle 뒤 기준을 다시 읽고 현재 카드 설명을 제한적으로 재검사한다. 지갑·이름·역할·URL·미정산·프로세스·exact rule 검사는 유지하고 이전 marker를 성공으로 인정하지 않는다. 첫 rollback 구간의 신규 요청/Model은 0이었고, 최종 전환은 postcheck 첫 시도에 성공했다.

비공개 고객 원문을 새 fixture로 복제하는 요청은 자동 승인 검토에서 불필요한 민감정보 사본이라는 이유로 거절됐다. 수행하거나 우회하지 않았다. 원문 과거 재현 대신 익명 집계·합성 질문·현재 공개 재고로 검증했다. 원 고객/Model 사고 과정·JWT·지갑키는 공개 자료에 복사하지 않았다.

## 현재 실행 및 이어받기

- 공개 주소: https://stable-leu-below-the.trycloudflare.com, 등록/카드 이름 outseop-r4, 기존 지갑 동일.
- 원 main1192914·worker1192976·18806 front1213796·18807 front1218994: PID와 재시작 수 동일.
- 새 `ourolabs-market-r4-semantic3-front.service`: PID1240765, NRestarts0, 127.0.0.1:18808. 별도 등록·매입/홍보 루프 없음.
- 기존 task fallback: 18808→18807→18806→18805. source127.0.0.2로 기존 task/card를 전달한다. 기존 task store를 위해 이 프로세스들을 무심코 재시작하지 않는다.
- 단일 own OUTPUT rule: source/dest127.0.0.1, UID1000, dport18805, comment codex-r4-front-edge-v1, REDIRECT18808. 다른 rule/conntrack를 정리하지 않는다.
- 기존 캐시 producer8a와 카드 keeper timer active. 조회 당시 representative146행, 물리 unit 수와 혼동하지 않는다. 새 지표는 public-catalogue-semantic3-metrics.json으로 기존 프로세스 파일과 분리한다.
- Codex 예약 r4/r4-2/r4-3은 PAUSED 유지. 기존 DB/두지갑 inode·내용, 원가/혜택/환불 정책·매입·미정산 모든 필드 보존, quick_check ok·중복 active unit0.

현재 runtime manifest는 `b7a4e344bbfcaa989444bad93f7166fd404ee36e52018128511d542331e7f5ed`, listener manifest는 `25d099830f88215ffebc37c41fd9cef8c3a28d0206f411ab9488c646a62980d9`, 별도 transition-only v2 manifest는 `3221558aba91145edc9e13f5e6421520dc6eef1ba89fe9f5814e0b3964147f8f`다.

전환/원복은 root에서 아래 별도 guard를 쓴다. PID와 URL은 그때 다시 확인한다. 기본은 읽기 전용, `--apply`는18807→18808, `--rollback`은18808→18807의 정확한 own rule만 바꾼다. 원복 뒤18808에서 새로 만든 active task가 자동으로 역방향 전달되는 것은 아니므로 먼저 신규 task 상태를 확인하고 모든 store를 보존한다. NAT 영속화·부팅 enable 변경은 하지 않았다.

```text
.venv/bin/python -B deploy/semantic3_transition_guard_v2/transition_guard.py --package-manifest-sha 3221558aba91145edc9e13f5e6421520dc6eef1ba89fe9f5814e0b3964147f8f --expected-main-pid 1192914 --expected-old-edge-pid 1218994 --expected-legacy-edge-pid 1213796 --expected-public-url https://stable-leu-below-the.trycloudflare.com
```

근거: evidence/20261127-semantic-intent, evidence/20261127-semantic-query/neutral-language, evidence/20261127-semantic4-actual-class. 기존 NoWallet17건 정확 ref 제외 규칙과 원로그 보존은 유지한다. 이번 격리 class 세션의 PROD decision/transport 교집합은0이며 공개 점검1건은 별도 operator 등록이다.
