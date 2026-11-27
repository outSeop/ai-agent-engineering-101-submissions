# semantic19 + 고정 라우터 적용안 — 승인 전 실행 금지

현재 외부18810/native9와 기존 DB·두 지갑·장부·매입8·가격 정책·worker·CF는 그대로다. 이 적용안은 검증한 d48415/native19를 기존에 만든 loopback engine/router 두 unit에 연결하고, 기존18805의 정확한 NAT 목적지 하나를18810→18811로 바꾸는 작업이다. 기존 main·worker·legacy fronts·CF는 재시작하지 않는다.

승인 후 먼저 maintenance=true/current0을 확인한다. source pin과 실제 새 PID/cmdline·DB 경로 일치를 검사하고 legacy 소유권과 기존 task 조회를 갱신한다. 현재 등록명·지갑·URL·대기 결제 URL을 확인한 뒤 idle 구간에서 정확한 원 NAT 규칙만 바꾼다. 공개 카드/marker postcheck와 기존 프로세스 보존을 확인해야 새 요청을 연다.

새 작업이 저장된 뒤에는 예전 listener로 되돌리지 않는다. 같은18811/router·18812/engine·private HOST DB를 유지해 고친다. 금융 DB migration이나 새 지갑/상점 등록, 별도 매입·홍보 정책 변경은 없다.

자동 승인 검토가 이 외부 전환을 거절했으므로 명시적 사용자 승인 없이는 적용하지 않는다. PLAN.json은 검토용 명세이며 자체 실행 기능이 없다.
