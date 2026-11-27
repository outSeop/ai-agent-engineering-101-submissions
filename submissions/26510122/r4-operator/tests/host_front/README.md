# 공통 front 회귀검사

현재 유지보수 코드는 `catalogue_asgi_support.py`와 `test_catalogue_asgi_replay.py`다. 과거 runtime/evidence의 실행기·결과·manifest는 당시 기록으로 보존하며 수정하지 않는다. 과거 baseline6의 “final8 대기”는 그 시점의 상태다. 이후 final9 결합 경로에서 지원 범위 두 사례의 SDK ASGI 전달이 확인됐고, 현재 테스트는 그 검증을 유지 경로로 추출한다.

## 무엇을 검증하는가

이 테스트는 **미리 정한 Model stub 출력의 배선과 genuine 도구·SDK 최종 응답**을 검증한다. 모델이 자연어에서 올바른 상품군·검색어를 해석하는지는 검증하지 않는다. 실제 모델 호출·인증 토큰·지갑·생산 DB·생산 로그·고객 원문을 사용하지 않는다.

- 기본 복합 문의: 상품군 두 개를 한 번씩 언급하고 stub이 두 그룹을 반환한다.
- 지원되는 반복 긍정: 상품군 하나와 지원되는 후행 완전절을 사용하고 stub이 한 그룹을 반환한다.
- 원래의 지원 밖 혼합 문장: 두 그룹과 별도의 반복 표현을 섞었던 최초 fixture를 글자 그대로 `unittest.expectedFailure`에 남긴다. 나중에 지원되어 성공하면 `unexpected success`가 전체 검사를 실패시켜 범위 문서를 다시 검토하게 한다.
- fixture 시각 검사: 같은 명시 시각으로 생성한 snapshot 직렬화가 같고 시각을 바꾸면 expiry·snapshot이 달라지는지 확인한다.

성공 사례는 stub의 그룹과 **완전한 원문**이 실제 native 호출에 그대로 전달됐는지, persistent engine의 합성 maintenance가 닫힌 때 모델 호출 없이503인지, 연 뒤 한 번만 호출했는지, genuine 최종 문구와 SDK 응답이 같은지 검사한다. `loaded_broker`는 검증된 assemble 결과에서 명시적으로 읽으며 이전 `sys.modules` 검색으로 돌아가지 않는다. Python의 동적 모듈 로더 등록은 import 기능에만 쓰고 사업 객체를 찾는 수단으로 쓰지 않는다.

실제 모델 의미·provider 지연은 별도의 운영자 검증 근거다. stub 성공을 실제 모델의 문장 해석·실고객 해결·전환율 개선으로 보고하지 않는다. 처음의 혼합 fixture 실패도 genuine source 오류로 바꾸어 기록하지 않는다.

## 실행

`OPERATOR`는 이 체크아웃의 `r4-operator` 디렉터리다. 개인 사용자명이나 고정 저장소 절대경로를 코드에 넣지 않는다. 검토한 materialized release의 BUILD.json과 그 SHA를 명시한다.

```sh
unshare -Urn "$OPERATOR/.venv/bin/python" -B \
  "$OPERATOR/tests/host_front/test_catalogue_asgi_replay.py" \
  --operator "$OPERATOR" \
  --output "$QA_OUTPUT" \
  --build-receipt "$BUILD_RECEIPT" \
  --build-sha256 "$BUILD_SHA256" \
  --expected-semantic-version 9
```

`--operator`와 `--output`은 필수다. 출력은 기존 결과를 덮지 않는 새 경로여야 하며 production·source·immutable release·과거 evidence 안에는 만들 수 없다. 이전처럼 특정 runtime 폴더의 직속 자식만 허용하지는 않는다. 실제 app fixture는 공통 `isolated_root`의 보안 계약에 맞춰 `operator/runtime` 아래의 별도 소유0700 임시 디렉터리에 만들고 경로를 결과에 기록한다. 실패 fixture는 자동 삭제하지 않는다.

새 `persistent_engine`도 fixture 안의 tasks.sqlite3만 사용하며 합성 상태의 maintenance만 연다. 이 모드에서는 이전 admission gate를 쓰지 않으며, 생성된 task의 durable owner가 current인지 확인한다. XFAIL의 공통 setup 검사는 decorated test 밖에서 수행하므로 setup 오류는 expected failure로 숨겨지지 않는다. 실제 DB는 읽거나 열지 않는다. 원래 금융 소스와 SDK7은 바이트 pin 확인만 한다. 로더는 BUILD/runtime/front manifest, config binding과 원 forge를 검증한 뒤 실행하며 경로 검증을 우회하지 않는다. 필요한 `loaded_broker` hook이 없는 옛 release에 조용히 fallback하지 않는다. `unittest discover`만 실행해 명시 인자가 없으면 integration 부분은 skip된다.

## 시각과 hash

하나의 실행은 snapshot의 `fixture_now`와 expiry를 공유한다. `--fixture-now`로 시각을 지정할 수 있지만 원래 TTL150 안에서 신선해야 한다. SDK나 genuine 도구의 실제 wall clock은 바꾸지 않는다.

따라서 **실행 간 reply SHA가 같다고 약속하지 않는다.** 과거 두 합성 compound 응답의 차이는 남은 기한 `86398초`와 `86397초` 한 자리뿐이었다. 입력 관측시각도 달랐다. 현재 결과에는 fixture 관측시각·expiry·snapshot SHA와 이 제한을 남기며, 최종 문구는 같은 요청 안에서 genuine 출력과 비교한다. 고정 fixture 직렬화의 재현성과 실제 시각을 읽는 사업 응답의 재현성을 구분한다.

기대 결과는 지원 사례 성공과 한 개의 명시적 expected failure다. 전체 반복 문장, 복합 반복 조합, 원래 지원하지 않던 조건이 모두 해결됐다는 뜻은 아니다.

## 현재 유지 suite 검증 상태

검토용 prototype에서 4개 중 정상 성공 3개와 명시적 expected failure 1개를 확인했다. unexpected success는0이다. 첫 유지 실행은 persistent engine을 이전 admission 방식으로 여는 fixture 오류가 있었고 새 출력 경로에 그대로 보존했다. setup을 실제 maintenance 계약으로 고친 뒤, 지원 밖 사례의 native `unavailable/unsupported_request`를 setup에서 확인했다. 이전 evidence·manifest를 수정하지 않았다.

추가 router 리뷰 3건은 전체 ASGI의 잘못된 method가400으로 끝나는지, 전역 transport 위치와 backend의 사용자별 읽기 권한이 분리되는지, owner 탐색의8초 제한에 lock 대기가 포함되는지 검사한다. 모두 실제 임시 SQLite·fake peer만 쓴다. 테스트 timeout만25ms로 줄이고 소스의8초 인자를 확인하며 실제 운영 시간제한은 바꾸지 않는다.

Persistent engine 검증에서 이전 admission counter는0인 채 유지되고, 각 합성 요청의 새 current route는1개다. 둘은 같은 지표가 아니다. 이 증거는 prototype/local 검사이며 새 router·engine의 운영 전환을 뜻하지 않는다. 실제 공개 경로가 바뀌었다는 주장은 별도 승인·운영 증거가 있어야 한다.
