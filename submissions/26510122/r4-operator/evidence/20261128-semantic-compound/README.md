# 복합 공개 상품 문의 검증

실제 수업 모델이 공식 Mind와 forge_tool로 semantic_candidates v6를 만들었다. 공개 상품 도구 v8과 유사어 도구 v4는 원본 SHA를 고정해 읽기 전용으로 재사용했다. 복합 조회는 원문에 나온 두 상품군을 각각 확인하고, 서로 다른 공개 SKU와 실제 등급·가격을 450자 안에 온전한 줄로 보여 준다. 후보는 정확한 상품 일치나 요청 조건 전체의 충족을 보장하지 않는다.

일반 SDK 합성 회귀 12개를 통과했다. v5는 첫 상품군에 후보가 많으면 두 번째를 누락하고 긴 응답을 잘랐다. 외부 장문 시험 자료의 끝 공백을 제거해 유효한 제목으로 고친 뒤에도 동일한 v5 문제를 재현했다. v6 원본은 자료 수정 전후에 변경하지 않았다. 보증을 함께 문의하는 합성 문장은 여전히 검증 불가로 보류했다. 두 상품군에 서로 다른 검증 후보를 제시할 수 없는 경우에도 보류한다.

독립 합성 ASGI 검증은 실제 수업 모델 1회와 일반 SDK semantic 도구 1회로 HTTP 200 완료 상태를 확인했다. 양쪽의 공개 SKU·등급·가격과 비구속 문구가 원 도구 응답과 일치했고, 테스트 고객·결제·DB 연결·공개 게시·리스너 시작은 없었다. 합성 상품과 응답에 대한 검증이며 실구매 또는 실고객 효과로 집계하지 않는다.

운영자 디렉터리에서 일반 SDK 회귀를 재현한다.

    .venv/bin/python -B evidence/20261128-semantic-compound/test_compound_native_sdk.py --semantic deploy/public_catalogue_runtime_compound_v1/semantic --catalogue deploy/public_catalogue_runtime_compound_v1/catalogue
