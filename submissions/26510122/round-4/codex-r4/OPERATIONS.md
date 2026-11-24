# outseop-r4 운영 인계

공개 서비스와 터널은 중지 상태에서 작업했다. 이 구현과 모의 검증의 작성자는 OpenAI Codex GPT-6.2 Sol이다. 운영 언어 모델은 기존 수업 모델을 사용한다. 이번 작업 중 실운영 지갑으로 서명하거나 실제 송금·시장 정산을 실행하지 않았다. 공식 키트 파일은 그대로 두고 격리 작업공간에서 공식 Toolbox.forge로 도구를 등록했다.

## 수업 모델 운영 메모

공개 A2A는 기존 공식 SDK를 사용한다. 수업 모델은 현재 문의에서 상품 선택, 가격 문의와 흥정, 명시적 구매, 환불 검토 여부, 일반 답변을 판단한다. 모델이 요청할 수 있는 작업은 shop_context, offer, quote_and_send, review_refund, respond다. 백그라운드 Mind는 별도 공개 조회인 shop_info를 사용할 수 있다.

신뢰 브로커는 HTTP에서 받은 원래 문의의 내부 참조를 발급한다. 코드가 먼저 재고·예약 상태·기존 견적·권리·혜택을 조회하고, 모델에는 비밀을 제거한 고객 메시지와 검증된 현재 계정 정보 및 직접 신고한 선호의 요약을 제공한다. 닉네임과 외부 taskId는 고객 권한을 증명하지 않는다. 모델 인자에는 목적지나 권리코드를 받을 필드가 없다. 현재 요청의 범위는 코드가 직접 보관하며 모델이 참조나 목적지를 제출할 수 없다. 도구 인자 형식을 검증한 뒤에만 실행한다. 서명 JWT·대기증·권리코드는 도구 결과에서 원래 고객의 A2A 응답으로 직접 전달한다.

가격 문의·흥정에서 offer는 재고를 예약하지 않는 검증된 참고 견적이다. 고객에게 전달된 견적코드는 10분 동안 유효하다. 명시적으로 구매를 수락한 고객이 그 코드를 제시하면 quote_and_send는 같은 SKU와 가격을 확인한 뒤에만 서명한다. 고객이 제시한 크레딧 금액을 초과하는 결제권이나 원가 하한을 밑도는 견적은 발급하지 않는다. 합의 기준가는 대기할인·마일리지 차감 전 가격이며 기존 비율을 적용한다. 같은 메시지 재전송에는 이미 전송했다는 안내만 반환한다. 고객의 비밀 코드는 다시 노출하지 않는다.

마일리지 조회·대기권 사용·송금 확인·구매 취소·프로필 갱신의 정확한 명령은 브로커가 기존 도구에 바로 전달한다. 환불 요청은 모델이 검토 판단을 하고 도구가 해당 고객의 영수증 및 시장 증거를 확인한다. 근거가 확인돼도 운영자 검토 상태까지만 바뀐다. 기존 매입·송금 도구와 read_tool·forge_tool의 런타임 호출은 차단한다.

격리 모의 실행은 고객 원문, 모델의 실제 구조화 출력, 도구의 판단, 고객에게 간 원문 응답을 개인 JSONL로 기록한다. 비교용 review JSONL은 권리코드·결제 JWT·지갑·거래 식별자를 마스킹하고 모델의 도구 결정과 짧은 이유만 표시한다. 로그는 비공개 .kit 폴더와 0600 권한을 사용한다. 실제 고객이 자유롭게 적은 텍스트는 공개하기 전에 별도로 검토해야 한다. 기존 notes.md에도 금융 비밀과 고객 민감정보가 없어야 한다.

## 관리 실행기

managed_launcher.py는 공식 코드 파일 7개의 Git blob 해시를 확인하고 공식 Python 모듈의 Toolbox, Mind와 ASGI 팩터리에 관리 어댑터를 연결한다. 공식 파일을 수정하지 않는다. 공개 POST 요청의 공식 A2A 핸들러에만 1회 브로커 진입 권한이 부여된다. 요청 인자나 고객 이름으로 권한을 만들 수 없다. OS 운영자 CLI는 별도로 유지한다.

```bash
python managed_launcher.py check --operator-dir "$operator_dir" --agent-root "$agent_dir"
```

check는 파일과 도구 권한만 확인한다. 서비스·터널·시장 등록·지갑 열기는 승인 후 run에서만 수행한다. 기존 서비스 ExecStart는 공식 키트를 직접 부르지 않고 아래 관리 실행기를 사용하도록 준비한다. 승인하지 않은 상태에서는 활성화하거나 시작하지 않는다.

```bash
python managed_launcher.py run --operator-dir "$operator_dir" --agent-root "$agent_dir" \
  --owner-file "$private_owner_file" --public-url "$existing_https_shop_url" --port "$existing_a2a_port"
```

선택한 환경에 고정 공개 URL이 없으면 별도 승인 뒤 --public-url 대신 --tunnel을 사용할 수 있다. 관리 실행기에서는 미니앱과 구매자 역할을 시작하지 않는다. 고객의 공개 A2A와 별도 운영자 CLI를 사용한다. ASGI 프로세스에 Python 코드를 설치할 수 있는 OS 운영자는 배포 신뢰 경계 안에 있다. 시장 거래 환경과 권한을 바꾸는 도구는 검토한 운영자 업무다.

## 정산·대기열 작업의 서비스 연결

관리 실행기는 공식 R4 시장의 /api/agents에서 기존 outseop-r4 상점을 확인한 뒤 실행을 진행한다. 공식 키트가 POST를 호출하기 직전에 기존 등록을 다시 확인하고 기존 지갑 주소를 대조한다. 시장 API는 기존 계정만 대상으로 하는 원자적 재가입을 제공하지 않는다. 등록 대조와 실제 POST 사이에 시장 장부가 초기화되는 예외는 운영에서 확인해야 한다. 관리 어댑터는 대조 없는 POST 재시도를 방지한다.

성공한 공식 메인 프로세스의 정산용 shop 토큰을 .kit/worker-token에 원자적으로 저장한다. 파일은 0600, .kit은 0700이다. 메인의 정상 재등록 주기가 성공할 때 토큰도 갱신된다. 수업 모델과 워커는 같은 기존 시장 상점의 토큰 발급 흐름을 쓰며 모델 프롬프트에 토큰이 들어가지 않는다. 마켓 소유 코드와 토큰을 로그·환경변수·셸 인자·Git에 남기지 않는다.

워커는 메인 서비스가 active인 경우에만 검사한다. 포트 18805의 로컬 카드를 읽고 공개 주소·상점명·기존 지갑을 시장의 유효 등록과 대조한다. 보호된 토큰으로 인증한 재고 응답도 대조한다. 유효한 조건을 확인한 뒤에만 10초 간격으로 대기열과 정산 기록을 처리한다. 워커는 별도 시장 가입, 지갑 키 로드, 소유 코드 읽기, 환불 승인과 송금을 수행하지 않는다. 시장이 준비되지 않았으면 제한된 횟수로 기다린 뒤 실패한다.

ourolabs-market-r4-worker.service는 Requisite, PartOf, After로 설치된 ourolabs-market-r4.service에 묶인다. 사용자 서비스 디렉터리에 파일을 설치하고 worker만 메인의 .wants에 연결한다. 이때 --now는 사용하지 않는다. 메인과 함께 시작하도록 구성한 뒤에도 사용자가 승인할 때까지 메인은 시작하지 않는다.

## 고객 명령

- 재고 확인은 '재고', 재고의 구매는 '구매 G0026722f'를 사용한다. SKU는 재고 응답에서 확인한다.
- 새 구매에서 받은 권리코드를 비공개로 보관한다. '잔액 권리 <코드>'로 조회하고 다음 구매에 '구매 <SKU> 권리 <코드>'를 보내 사용한다. 유효 잔액은 원가와 수수료 하한을 지키는 범위에서 적용된다.
- 실제 앞선 문의 때문에 처리가 밀렸을 때만 120초 유효한 대기권을 발급한다. '대기 <대기코드>'로 진행을 확인한다. 기존 권리계정에 연결해 발급했으면 '대기 <대기코드> 권리 <코드>'를 사용한다. 서명된 wait_voucher는 대상 상품, 적용 할인과 1회 조건을 확인할 수 있다.
- 결제권을 받고 처리가 지연되면 먼저 문의한다. '결제확인 <송금해시> 권리 <코드>'로 송금과 시장 정산을 확인한다.
- '취소 <SKU> 권리 <코드>'는 결제 중단 의사를 기록한다. 시장에서 이미 발급한 checkout JWT를 회수할 수 없다. 입금 여부 또는 시간을 추정해 같은 재고를 재판매하지 않는다. 원래 확인한 market ledger 증거로 재고가 영구 소진된 경우 미결제 차감을 복원한다.
- '환불 <송금해시> 권리 <코드> [수수료 <수수료송금해시>]'는 환불 검토를 접수한다. 시장 정산 기록 및 양쪽 송금을 대조할 수 있는 경우 확인된 상품 입금, 시장 수수료, 두 성공 영수증의 가스를 원 송금인에게 반환한다. 가스는 발급 시 안내한 시장 표준 네트워크 크레딧 한도가 적용된다. 미인도 수수료는 동일 지갑·결제 해시·시장 수취 주소로 확인되는 수수료 송금해시가 있어야 포함한다.

권리코드는 이를 가진 사람의 권한이다. 지갑 본인 인증이 필요 없는 고객 텍스트 인터페이스에서 작동한다. 송금 자체는 체인에서 검증하고 환불은 원 송금 주소만 사용한다. 닉네임, taskId, 공개 송금해시는 권리 인증에 사용하지 않는다. 새 고객이 받은 코드를 분실하면 이 인터페이스로 복구할 수 없다.

## 운영자 전용 명령

초기 활성화 전에 동일 등록 이름과 지갑을 확인한다. 기존 상태와 지갑을 그대로 보존하고 별도 새 장부인 state/r4-benefits/benefits.sqlite3를 사용한다. 모든 경로는 신뢰된 운영 계정 소유여야 한다. 수동 동기화 명령에도 관리 실행기가 내보낸 .kit/worker-token을 사용한다. 동기화 작업은 공식 모델이나 공개 API로 환불 권한을 위임하지 않는다.

```bash
python refund_admin.py --agent-root "$agent_dir" --url "$shop_url" --address "$shop_address" \
  --token-file "$private_shop_token_file" sync
# 동기화, 대기 준비 확인을 반복하는 작업
python refund_admin.py --agent-root "$agent_dir" --url "$shop_url" --address "$shop_address" \
  --token-file "$private_shop_token_file" worker --every 10
# 보류 환불 조회
python refund_admin.py --agent-root "$agent_dir" --url "$shop_url" --address "$shop_address" \
  --token-file "$private_shop_token_file" refunds
```

승인 전에 주문, 실제 초기 문제나 판매자 귀책 여부, 비용 항목, 수신 주소와 기존 시도를 대조한다. 실제 환불 승인 명령은 운영자만 실행한다. 기존 키를 생성 또는 변경하지 않는다. 문서의 어떤 예시도 이 유지보수 세션에서 실운영 키나 실거래로 실행하지 않았다.

```bash
python refund_admin.py --agent-root "$agent_dir" --url "$shop_url" --address "$shop_address" \
  --token-file "$private_shop_token_file" --operator-kit "$official_kit" \
  approve-and-send <refund-id> --wallet-file "$existing_shop_wallet" \
  --confirm-original-hash <incoming-hash>
python refund_admin.py --agent-root "$agent_dir" --url "$shop_url" --address "$shop_address" \
  --token-file "$private_shop_token_file" recover <refund-id> [--outgoing <refund-tx-hash>]
```

송금이 불확실하면 같은 승인 명령을 다시 실행하지 않는다. recover로 거래 해시를 확인하거나 송금 시도 직전 블록부터 유일한 송금 마커를 찾는다. 탐색 결과의 next_block을 --start-block에 전달해 이어서 조회할 수 있다. 확인된 체인 영수증이 없으면 보류를 유지하고 수동 조사한다. 시장 자동 환불을 사용하지 않는다.

소비자가 새 결제권을 받은 뒤 결제하지 않으면 시장에 회수 기능이 없어 동일 unit은 보수적으로 계속 보류된다. 누구나 문의할 수 있는 시장에서 이 제약이 가용 재고 부족으로 이어질 수 있다. 운영 전 해소 조건과 위험을 검토한다. 이미 발급된 JWT가 있는 동안 공개 주소를 바꾸면 고객이 새 URL로 기존 결제권을 사용하지 못할 수 있으므로 변경 전에 미결제 상태를 대조한다. 새 결제권은 새 등록 주소를 쓰며 기존 주문은 발급 시점 주소로 대조한다.

## 고객 프로필

프로필은 내부 account에 연계한다. 운영자 목록의 r4p- 식별자는 공개 권리코드로 사용할 수 없다. 방문 수는 실제 방문 대신 인증된 접촉 세션의 추정치다. 직전 인증 접촉과 30분 이상 떨어진 문의는 같은 task ID를 쓰더라도 새 세션이다. 30분 안에 들어온 새 task는 같은 세션이다. 같은 세션에서 동일 task ID로 재전송하면 계수와 마지막 접촉 시간을 변경하지 않는다.

잔액·예약·부채·만료는 금융 원장에서 계산한다. SKU 및 카테고리의 횟수는 정산이 있는 구매에서 계산하며 고장·환불·유지 건수를 따로 기록한다. 선택한 선호와 구매 기록은 출처가 다르다. 확인된 시장 매수자 이름과 원 송금 주소는 해당 정산의 관측 관계로만 기록한다. 동일 시장 계정이나 동일 지갑으로 결제해도 별도 권리계정은 병합되지 않는다.

고객이 직접 제공한 구조화 항목만 선택적으로 사용한다. 예를 들어 '프로필 가족 자녀 2 권리 <코드>', '프로필 가구 4 권리 <코드>', '프로필 소득 quintile 3 권리 <코드>', '프로필 선호 category 주방용품 좋아함 권리 <코드>'다. '프로필 삭제 소득 권리 <코드>'는 현재 뷰에서 해당 항목을 지운다. 정정·삭제 이력은 내부에 남긴다. 의미 있는 소득분위 척도는 decile 또는 quintile이다. 명시되지 않은 소득은 unknown이며 가격이나 구매 빈도에서 유추하지 않는다. 가족 이름이나 텍스트 원문을 받는 필드는 없다.

```bash
python profile_admin.py --agent-root "$agent_dir" --address "$shop_address" list
python profile_admin.py --agent-root "$agent_dir" --address "$shop_address" profile <profile-id>
python profile_admin.py --agent-root "$agent_dir" --address "$shop_address" facts history <profile-id>
python profile_admin.py --agent-root "$agent_dir" --address "$shop_address" facts ingest < profile-example.json
```

예시 파일은 가상 식별자를 사용한다. 내부 ingest는 운영자가 해당 계정으로부터 직접 듣고 확인한 신고만 받는다. 조회 결과는 비공개 운영 화면과 파일에서만 다룬다.

## 검증과 승격

격리 경로의 agent-work에서 운영자 전용 .venv/bin/python으로 codex-r4/test_contract.py, codex-r4/test_profile.py, codex-r4/e2e.py와 codex-r4/forge_tools.py, codex-r4/forge_info.py와 codex-r4/test_managed_runtime.py를 실행한다. 실제 captured customer.py의 Visit.talk과 Visit.buy를 공식 A2A ASGI 경로와 연결한 모의 테스트가 포함된다. Forge 증거는 새 도구의 forge.json과 격리 logs/forge.jsonl에 남는다.

승격할 때는 통과한 세 도구 폴더의 permission.yml, logic.py, test.py, forge.json을 그대로 복사한다. 도구의 SHA-256과 단일 handles 항목을 다시 검증한다. ledger_core v1과 격리 테스트 DB는 승격에서 제외한다. 코드가 필요하면 codex-r4/dispatcher.py, refund_admin.py, profile_admin.py를 같은 내부 디렉터리에서 실행한다. 공개 카드 수정, 서비스·터널 가동, 실제 거래는 운영 승인 이후 별도로 시행한다.


## 모델 결정 모의 테스트

이번 운영 코드의 작성자는 Codex GPT-6.2 Sol이다. 공식 Toolbox는 수정된 a2a_info를 v6으로 격리 등록했다. 수업 모델의 판단을 테스트할 때는 같은 Broker와 Fixture를 쓰고, 스크립트가 도구를 미리 선택하지 않도록 모델 응답을 그대로 브로커에 전달한다. 모든 시장·체인·서명은 테스터의 격리 fixture로 대체한다.

이전 금융 코어와 공식 고객 흐름의 검사에 더해 test_broker.py는 비구속 견적, 가격 하한, 구매 동의, 요청 간 참조 재사용, 익명 재전송, 마일리지·대기할인, 다른 계정의 환불 거부, 공식 A2A JWT 전달을 검증한다. 이 파일의 결정은 테스트 대역이므로 실제 수업 모델 관측으로 집계하지 않는다. 실제 모델 검증은 별도 검증자의 실응답 JSONL을 사용한다.

공식 고객 코드의 HTTP 대기에는 한도가 있으므로 직렬 모델 호출이 길어질 때는 확인되지 않은 조건을 새로 발급하지 않고 다시 문의하도록 답한다. 시험에서 지갑·재고·공개 거래 상태는 변경하지 않는다.
