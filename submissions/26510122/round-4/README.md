# outseop-r4 — 검증된 코드와 수업 모델 운영

현재 공개 서비스는 사용자 요청으로 중지돼 있다. 기존 DB·지갑·재고·로그를 초기화하지 않는다.

구현은 Codex GPT-6.2 Sol, 운영 언어 모델은 수업 모델이다. 공개 A2A가 구매·대기할인1%·마일리지1%·프로필·환불 접수를 직접 처리하며, 모델은 읽기 전용 shop_info로 재고와 정책을 안내한다. 환불 이체는 운영자 승인 경로다.

먼저 [현재 서버 인계](../r4-operator/SERVER_CODEX_HANDOFF.md), [내부 검증 결과](../r4-operator/R4_INTERNAL_VALIDATION_20261125.md), [운영 명령](codex-r4/OPERATIONS.md)을 읽는다. 재가동을 허가받기 전에는 서비스·터널을 시작하지 않는다.

실제 고객/금융 DB state/r4-benefits, .kit와 키는 비공개다. logs와 tools의 실제 forge 기록은 그대로 보존한다. 모의 테스트를 실제 정산 실적으로 세지 않는다.
