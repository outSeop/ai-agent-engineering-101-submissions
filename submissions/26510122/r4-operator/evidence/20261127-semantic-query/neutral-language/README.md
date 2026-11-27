# 중립 결제 언급을 포함한 유사어 조회 검증

공식 Mind가 개발 CLI에서 작성한 semantic_candidates v4와 동일한 R4 카탈로그 v8 소스로 테스트합니다. v3은 공식 자체 검증을 통과했으나 목표 문구와 새로운 상품 어형을 지원하지 않아 배포 대상에서 제외했습니다. v4의 첫 공식 자체 시험이 실패한 원인과 실제 재제출 결과는 각 증빙 JSON에 있습니다.

운영자 디렉터리에서 아래 명령으로 일반 SDK 검증을 실행할 수 있습니다. 운영자와 배포 후보의 경로를 지정하거나 저장소 기본 경로를 사용합니다. 공개 재고 데이터는 합성하고, 임시 SDK는 지갑을 가질 수 없습니다.

    .venv/bin/python -B evidence/20261127-semantic-query/neutral-language/test_semantic_v4_sdk.py --operator . --bundle deploy/public_catalogue_runtime_semantic_v4

모의 호스트 검증에는 같은 운영자 디렉터리에서 아래 명령을 사용합니다.

    .venv/bin/python -B evidence/20261127-semantic-query/neutral-language/test_prepared_host.py

이 자료는 고객 원문이나 내부 대화 기록을 재생하지 않습니다. 개발 모델은 요청된 GPT-6.2 Sol CLI였고, 운영 연결은 공식 SDK의 market 모델 설정을 사용합니다. 실제 수업 모델에서의 응답과 운영 배포는 별도 검증입니다.
