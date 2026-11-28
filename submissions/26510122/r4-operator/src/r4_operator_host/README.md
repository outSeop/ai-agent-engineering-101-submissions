# R4 조회·통신 HOST 코드의 유지 위치

새 문의의 HOST 실행·연결 코드는 이 폴더에서 수정한다. 현재 운영 명세와 배포 경로는
`SERVER_CODEX_HANDOFF.md`의 최신 인계를 따른다. 현재 기능·금융 정책·지갑·DB를
리팩터링 목적으로 초기화하지 않는다. 상품 판단과 영업 도구 수정은 수업 모델이 맡는다.

- `front/`: 하나의 리스너·기존 대화 전달·접속 준비 gate·정확한 경로 전환 구현.
  포트/보존할 프로세스/경로/모델 안내문은 고정 설정으로 분리한다.
- `catalogue_protocol.py`: 원본 프로토콜을 재사용하는 작은 인자 검증 확장.
  고객 원문을 그대로 도구에 넘기며 가격·보증·조건 판단을 대신하지 않는다.
- `release_builder.py`: 검토된 base와 작은 HOST 변경, 모델이 생성한 도구를 그대로 묶는다.
  입력은 `deploy/release_specs/`의 SHA가 고정된 JSON, 출력은 비공개 `runtime/releases/<hash>/`다.

버전마다 실행 코드 수천 줄을 Git에 다시 복제하지 않는다. 공통 소스와 작은 변경을 수정하고,
검사 후 명세의 파일 SHA를 갱신해 새 불변 배포본을 만든다. 빌더는 서비스·시장 API·DB·지갑을
호출하지 않는다. 이미 만든 배포본은 변조 검증 후 재사용하며 덮어쓰지 않는다.

기존 `deploy/*runtime_v*` 폴더는 실행 중인 프로세스와 과정 증거가 참조하므로 보존한다.
현재 사용하는 명세·배포 경로는 SERVER_CODEX_HANDOFF.md의 최신 인계를 따른다.
과거 배포본을 수정하거나 새 기능의 작업 위치로 사용하지 않는다.

재현: `.venv/bin/python -B src/r4_operator_host/test_release_builder.py`
빌드: `.venv/bin/python -B src/r4_operator_host/release_builder.py --operator <OP> --descriptor <OP>/deploy/release_specs/<name>.json --expected-spec-sha <SHA>`

## 판매자 유입과 대안 안내

`catalogue_broker_core.py`는 검토된 기본 broker를 한 곳에 유지한다. 어댑터는 명시적으로 가져오며 다른 모듈의 import 부수효과를 사용하지 않는다. 관련 대안 메뉴가 검증되면 모델에게 SKU·등급 선택 한 번을 요청한다. `public_alternatives_host.py`는 격리된 native 도구에 원본 재고 바이트를 전달하고 도구가 렌더링한 사실을 연결한다. 대안은 결제나 예약을 만들지 않으며, 다음 구매에는 명시적 상품 확인을 거친다.

`seller_marketing_host.py`는 기존 셀러의 idle 홍보 tick을 동기 내부 호출로 이어 준다. 원 SDK Mind와 운영 Market 모델이 대상 글·상품·등급·게시 여부를 선택하고 native 도구가 현재 재고·가격·기한과 중복/게시 한도를 재검증한다. 별도의 주기 루프나 예약 작업을 추가하지 않는다. 작업 저널과 강제 종료 기한은 중복 실행과 늦은 게시를 막고, 미확정 게시 결과는 원 게시 도구가 복구한다. 기존 판매·매입·마일리지 장부를 대체하지 않는다.

릴리스 명세 v1은 계속 지원한다. v2는 기존 runtime 파일을 대체할 수 없는 HOST 확장과, 원 forge 기록에 맞는 native 네 파일을 추가한다. 시장 업무 도구의 소스는 빌더가 수정하지 않는다. 내부 소유 정책과 인증 토큰은 비공개 상태 경로에만 두며 Git에 넣지 않는다.
