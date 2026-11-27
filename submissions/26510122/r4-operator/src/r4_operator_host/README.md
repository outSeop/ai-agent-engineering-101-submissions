# R4 조회·통신 HOST 코드의 유지 위치

새 문의의 HOST 실행·연결 코드는 이 폴더에서 수정한다. 현재 명세는
`deploy/release_specs/compound-cleanup-active.json`이다. 현재 기능·금융 정책·지갑·DB를
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
