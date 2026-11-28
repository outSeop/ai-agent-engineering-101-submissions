# semantic19 공개 적용 결과 — 2026-11-28 12:29:41 KST

**사용자의 명시적 승인 후 새 버전을 공개 운영에 적용했다.** 공개18805 연결의 정확한 기존 NAT 규칙 하나를18810→18811로 전환했다. 현재 고정 router18811 → persistent engine18812 / semantic19이며 운영 모델은 market이다. 기존 outseop-r4 이름·URL·지갑과 금융 경로는 그대로다.

## 적용과 보존

- release ID: `d48415b401447f26df06354b273129db719e425409e8a9c670d762f6cb5d047c`
- front manifest: `5b0a9de94105b1376b1d4941ef7b936d35daf2cb3d2e4964895b23a69ac6d22c`
- 새 후보용 기존 prototype engine/router 두 unit만 갱신하고 재시작했다. engine PID1308994·router PID1308995, 적용 후 비정상 재시작0이다.
- 원 main·worker·기존5front·CF는 같은 PID다. DB device/inode 동일·quick_check=ok, 두 지갑·가격 정책·매입8·publisher9 파일 동일, 핵심 장부8개의 행 해시가 적용 전과 같다.
- 공개 Agent Card HTTP200·r4-flat-router-v1·outseop-r4·동일 지갑/URL을 확인했다. 카드 description은 기존 원본에서 직접 받으며 자연 갱신될 수 있다.
- task 목적지45개·원 protobuf 사본45개를 보존했다. 최초 전환 후 maintenance=false다. 점검 대화1개가 current에 영속 저장돼 이제 legacy 경로로 역전환하지 않는다.

## 기존 대화와 실제 공개 경로 점검

전환 직전 각 프로세스의 자체 ListTasks에서45개 원 소유자를 갱신했다. 전환 전 direct GetTask45/45, 전환 후 공개 GetTask45/45 성공이다. 이후 공개 result 전체를 원 소유자 direct result와 다시 대조해45/45 일치했다.

공개 주소로 점검자가 보낸 조회3개는 실제 수업 모델을 사용했다. 고객 문의나 정산 실적으로 세지 않는다.

| 조회 | 전체 응답 시간 | 결과 |
|---|---:|---|
| 쌀 재고와 가격 | 11.0222초 | HTTP200·SKU2개·가격 안내 |
| 방금 안내한 쌀의 등급 | 13.7612초 | 같은 task/context·해당 상품/등급 안내 |
| 쌀 재고와 쌀 가격 | 13.8186초 | 짧은 반복 명칭도 SKU·가격 응답, action_rejected 없음 |

모델은 각 문의1회, 총3회였다. 첫 조회와 후속 조회의 상품명·SKU·등급·가격은 조회 직후 fresh cache와 같은 행에서 일치했고 남은 시간은 응답 시각으로3초 이내였다. 이 비교 캐시는 요청 시점 동결본이 아니므로 요청 순간 snapshot 비교라고 주장하지 않는다. 결제 요청·결제권·송금은 없었다.

마지막 task는 공개 GetTask와 반환 내용 전체가 같고, 별도 Python 프로세스에서 읽은 HOST DB protobuf와도 같았다. 확인을 위해 엔진을 다시 시작하지 않았다. SDK의 별도 대화 closure 전체 복구를 검증한 것은 아니다.

점검기의 첫 artifact-only 응답 추출은 status.message의 문구를 놓쳤고, 첫 가격 검사는 크레딧 앞 공백을 잘못 가정했다. 실패 기록을 보존한 뒤 실제 응답 위치와 표기 형식에 맞춰 검사를 고쳤다. 사업 응답·원문·재고를 수정하지 않았다.

## 실제 문의·정산 관찰

전환 12:19:17부터 2026-11-28 12:29:41 KST까지 약10.4분 관찰했다. 점검3개를 제외한 자연 SendMessage는0건, 자연 신규 current task는0건, 신규 정산은0건이다. 누적 정산2·missing1 유지다. 따라서 실제 고객 문의→결제→정산 성공이나 전환율 증가를 확인했다고 말할 수 없다.

원 정산 worker는 같은 PID로 실행 중이다. read-only 시장 ledger 조회에서 로컬 cursor 이후 미처리 행0을 확인했다. 임의 정산 실행이나 시험 구매·송금은 하지 않았다. 이는 정산 대기 처리가 최신임을 보여주지만 새 거래의 종단 성공 증거는 아니다. 재고 캐시는144행이고 마지막 표본의 유효 잔여 시간은146.4초다.

## 다음 운영의 경계

다음 릴리스도 같은 router/engine port·unit·private HOST DB를 이어 쓴다. current task가 생겼으므로 legacy로 역전환하지 않는다. 교체 시 maintenance를 켜고 처리 중 요청을 배출한 뒤 같은 엔진을 고친다. 기존 금융 DB를 rollback하거나 미완료 금융 작업을 재송신하지 않는다.

이번에는 기존 부팅 enable·NAT 영속화 정책을 변경하지 않았다. WSL 전체 재부팅 시에는 공개 연결과 원 legacy 프로세스 복구를 별도로 확인해야 한다. legacy 메모리 작업의 snapshot은 보관용이며 죽은 프로세스의 금융 실행을 대신하지 않는다. R3·예약 홍보·매입15·cold-start 정책 변경은 포함하지 않았다.

[적용/보존 결과](evidence/20261128-reference19-activation/ACTIVATION-SAFE.json) · [공개 대화 전체 대조](evidence/20261128-reference19-activation/legacy-and-facts-final-safe.json) · [실제 공개 모델 조회](evidence/20261128-reference19-activation/operator-probe-status-message-safe.json) · [반복 조회](evidence/20261128-reference19-activation/operator-repeat-safe.json)
