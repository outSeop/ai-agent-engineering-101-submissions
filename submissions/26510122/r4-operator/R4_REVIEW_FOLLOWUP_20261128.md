# dad207c 검토 후속 — 2026-11-28 06:46 KST

**수정과 격리 검증은 완료했으며, 외부 영업은 기존18810 / semantic9를 유지한다.** 신규 후보는 semantic19와 고정 router18811 → engine18812다. 기존 DB·지갑·매입을 보존하며 운영 전환은 명시적 승인을 기다린다.

## 실제 문의가 실패한 원인과 수정

첫 실패는 한 글자 상품명이 반복될 때의 엄격한 문법 검사였다. 그다음 조회 과정에서는 분류 배열의 원소가 `대분류/소분류` 한 문자열로 들어와 기존 라벨 안전 검사에서 빠졌다. 상품명에 검색어가 없고 분류에만 있는 재고가 검색 대상에서 누락됐다.

semantic19는 관련 참고 조회에서 원문을 보존하고, 확인한 상품명·SKU·등급·가격·잔여 유통시간만 안내한다. 전체 조건을 검증한 견적이라고 주장하지 않으며 결제서 미발행을 명시한다. 숫자 조건·제외·개인정보·브랜드·보증·알레르기 등 기존 보호를 유지한다. 확인하지 못한 조건을 참이라고 바꾸지 않는다.

분류 정규화는 **관련 참고 조회의 임시 읽기 경로에서만** 적용한다. `/` 계층을 나눌 때 모든 조각과 공백/무공백 재조합이 기존 safe_label을 통과해야 한다. 제어문자·괄호·개인 참조 등은 기존처럼 배제한다. 기존 검증기를 끄거나 상품명을 추측하지 않는다. 원 캐시 파일·가격·등급·상태·기한·관측시각은 바꾸지 않는다. 모든 조회 경로와 모든 한국어 문장을 해결했다고 주장하지 않는다.

## 모델과 도구의 역할

사용자 지시대로 **개발은6.2 Sol, 운영은 수업 모델**이다. 공식 안내는 market·개인 API·Codex CLI 모델을 허용하며 에이전트가 직접 forge할 것을 요구한다. 도구 저작까지 수업 모델로 제한했던 내부 인계 기준은 공식 요건이 아니므로 폐기했다. [공식 안내](https://market.ourolabs.ai/agent.md)

실제 R4 개발 모델을 Codex CLI의 gpt-6.2-sol 요청으로 연결해 원 Mind.run_once → forge_tool → 원 Toolbox.forge·selftest·forge 기록을 거쳤다. 소스 변경 후 forge 기록만 붙이지 않았다. 새 문법·분류 decoder는 개발 Sol이 작성했고, 기존 strict parser와 authoritative renderer는 이전 모델 작성 소스를 보존했다. HOST는 기계 조립과 응답 전달을 맡는다. upstream_reported_model은 null이므로 CLI의 요청 모델과 검증한 응답 기록을 구분한다.

실제 수업 모델 합성 canary는 콩음료의 literal 후보0에서 `콩음료/두유` 검색어를 선택했다. 도구가 genuine semantic19로 합성 재고의 실제 필드와 기한을 검증했고 최종 응답에 결제서 미발급·INPUT_REQUIRED가 반영됐다. 모델10.1381초, 전체11.8637초, 모델1회·금융 실행0이다. 이 결과는 실제 고객 정산이나 매출 증가가 아니다.

## 저장과 라우팅 구조

기존17+3+10+7+2+2=41개 task의 원 소유자를 각 프로세스의 자체 ListTasks에서 확인했다. 별도 private HOST SQLite에 목적지와 protobuf 사본을 보존했고 초기 loopback prototype에서41/41 GetTask 직접 조회가 성공했다.

새 task와 논리 목적지 current는 한 트랜잭션에 저장한다. 고정 router는 기존 task를 원래 port에 바로 보내며 새 task는 같은18812 engine으로 보낸다. 다음 릴리스마다 port·unit·체인을 늘리지 않는다. snapshot은 보관용이며 죽은 legacy 금융 작업을 재실행하지 않는다.

원 SDK owner_resolver로 권한을 판단하며 metadata.from을 신뢰하지 않는다. 공개 힌트는 원 validator·최대3개·300초다. Task protobuf history와 명시적 공개 힌트는 보존하지만 별도의 SDK 대화 closure 전체를 복구한다고 주장하지 않는다. HOST DB는 금융 DB와 분리하며 디렉터리0700·파일0600으로 보호한다.

## 검증을 구분해서 읽기

| 검사 | 결과 | 의미 |
|---|---:|---|
| SDK task 저장·라우팅·전환 보호 | 31/31 | 임시 DB·fake peer, 실제 금융 없음 |
| 기존 front·전환 회귀 | 5/5 | 과거 동작 호환, mock 전환 |
| 패키징 | 4/4 | 두 operator 경로·원 forge bytes·드리프트 거절 |
| typed metadata unit | 6/6 | base-loader stub, 모델 의미 검증 아님 |
| semantic19 독립 SDK | 39/39 | 기존28+참고 조회·안전한 분류 변환·기한 검사 |
| 기존 지원 범위 ASGI | 정상3+원형 xfail1 | 고정 모델 stub, 모델 판단 검증 아님 |
| 실제 실패 원문 로컬 SDK | PASS | 원문 그대로·같은 재고 필드·미확인 조건·결제서 미발행 |
| 실제 실패 결정 전체 ASGI | PASS | 원문/args 그대로·최종 text/artifact data/trace event 일치·재고145행 중1행 검증 |
| 실제 수업 모델 합성 ASGI | PASS,1회 | 미리 정한 completion 없음, 금융0 |

최초의 복합+반복 미지원 fixture를 글자 그대로 expectedFailure로 유지한다. 준비 오류와 native unsupported_request 확인은 expectedFailure 밖에서 검사한다. 지원되면 unexpected success가 검사를 실패시킨다. 실패한 source·SDK 성공 뒤 독립 회귀 실패·미발급 draft도 별도 보존했다.

## 재현·해시·경로

유지 소스는 src/r4_operator_host와 tests/host_front다. 새 릴리스 명세는 operator 상대경로이며 --operator·--output·검토한 BUILD SHA를 명시한다. generated BUILD의 실제 경로는 각 머신에서 만들어 private에 둔다. 공개 evidence의 BUILD-PUBLIC은 경로를 정규화한 보기이며 실행 입력이 아니다. 원본 receipt와 manifest는 private에 바이트 그대로 보존했다.

같은 명세 SHA라도 절대경로를 포함한 local binding 때문에 runtime/front manifest는 다른 머신에서 달라질 수 있다. fixture 관측시각은 명시하며 SDK 실제 시계는 바꾸지 않는다. 남은 기한86398→86397초 같은 차이로 실행 간 reply SHA는 달라질 수 있다. 같은 요청 안에서 genuine native 출력과 최종 응답이 같은지 검증한다.

현재 BUILD는 원래 descriptor로 직접 재생성한다.

```sh
"$OPERATOR/.venv/bin/python" -B "$OPERATOR/src/r4_operator_host/release_builder.py" \
  --operator "$OPERATOR" \
  --descriptor "$OPERATOR/deploy/release_specs/stable-router-reference-v19.json" \
  --expected-spec-sha d48415b401447f26df06354b273129db719e425409e8a9c670d762f6cb5d047c
```

그 BUILD.json과 생성한 SHA를 유지 ASGI 하네스에 전달하고 --expected-semantic-version 19를 명시한다. 현재 과거 호환 기본값은 verify_build/CLI 모두9이며,19를 암묵적으로9로 검증하지 않는다. 공통 launcher의 --sources-only는 키·listener·Model 호출 없이 검증한다. 유지 소스의 운영 assert는0이고 native19 logic도0이다.

## 현재 준비물과 적용 경계

최신 명세: deploy/release_specs/stable-router-reference-v19.json

- release ID: `d48415b401447f26df06354b273129db719e425409e8a9c670d762f6cb5d047c`
- runtime manifest: `0f0b53d000ecb9326b9ea1a448bbcd20580e40e51289c8212a48c28f0a88ccea`
- front manifest: `5b0a9de94105b1376b1d4941ef7b936d35daf2cb3d2e4964895b23a69ac6d22c`
- native19 manifest: `87cdd15b1e5e2ac299586f61460abea2ca2d6e36278541479d9d0e293f10ff19`

최종 패키지를 외부에 설치하지 않았다. local unit은 초기51e577/native9 prototype으로만 가동 중이며 HOST maintenance=true·current task0이다. 외부는 기존18810/native9다. 두 지갑·기존 DB inode·장부8개 행 해시·가격 정책·매입8·publisher9가 기존과 같았고 누적정산2·missing1·신규정산0이다.

자동 승인 검토가18810→18811 NAT 전환을 실행 전에 거절했다. 외부 전환 승인 시 최종 unit binding을 먼저 설치·검사하고 기존41건·현재 카드·지갑·URL을 다시 확인한 뒤 정확한 원 규칙만 전환한다. 새 current task가 생긴 뒤에는 legacy 대상으로 역전환하지 않는다. 기존 main·worker·legacy fronts·CF를 재시작하지 않는다. R3·예약 홍보·매입15·cold-start 변경은 포함하지 않는다.

두 단어의 원문 열람도 자동 검토에서 거절됐으며 실제로 출력되지 않았다. 이후에는 원문을 더 읽지 않고 조건 미확정 참고 조회와 분류 구조 정규화로 문제를 해결했으므로 그 열람 승인은 필요하지 않다. 고객 원문을 공개 보고서·Git·개발 모델에 보내지 않았다.

## 증거

- [공식 native19 발급과39개 SDK 회귀](evidence/20261128-semantic-compound/native19-sol-reference/README.md)
- [실제 실패 결정 전체 SDK 전달](evidence/20261128-runtime-refactor/reference19-integration/README.md)
- [실제 수업 모델 합성1회](evidence/20261128-runtime-refactor/reference19-class-model/README.md)
- [이전 구조 준비 검증](evidence/20261128-runtime-refactor/review-ready/final83d11/README.md)
- [운영 보존 확인](evidence/20261128-runtime-refactor/reference19-preservation-safe.json)
- [과거 자동 승인 차단 기록](evidence/20261128-runtime-refactor/review-approval-safe.json)
