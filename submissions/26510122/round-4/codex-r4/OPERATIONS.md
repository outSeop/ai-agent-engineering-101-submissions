# outseop-r4 운영 인계

공개 서비스와 터널은 중지 상태에서 작업했다. 이 구현과 모의 검증의 작성자는 OpenAI Codex GPT-6.2 Sol이다. 운영 언어 모델은 기존 수업 모델을 사용한다. 이번 작업 중 실운영 지갑 키를 열거나 실제 송금·시장 정산을 실행하지 않았다. 공식 키트 파일은 그대로 두고 격리 작업공간에서 공식 Toolbox.forge로 도구를 등록했다.

## 수업 모델 운영 메모

고객의 A2A는 공식 SDK가 실행하는 단일 a2a_info 경로에서 직접 응답한다. 구매, 결제 JWT, 권리코드, 대기코드, 마일리지, 결제확인, 환불, 프로필은 수업 모델을 통과하지 않는다. 도구가 실패해도 고객 원문을 모델로 넘기지 않고 미리 정한 오류 응답을 반환한다.

수업 모델은 shop_info만 호출한다. 이 도구는 인자 없이 재고의 SKU·등급과 공개 혜택 문구만 제공한다. 대기 중인 비밀 없는 운영 상담 ID가 있으면 Mind의 조회 결과는 자동 전달되지 않으므로 같은 ID로 reply한다. reply 텍스트와 공개 데이터는 도구 결과 그대로 전달한다. 숫자나 단위를 고쳐 쓰지 않고 미응답 문의가 남으면 sleep하기 전에 먼저 reply한다.

```json
{"action":"reply","args":{"to":"<waiting-message-id>","text":"<result.reply 그대로>","state":"<result.state 그대로>"}}
```

런타임에서 수업 모델의 a2a_info, 기존 매입·송금 도구, read_tool, forge_tool 호출을 차단한다. 검증하지 않은 자동 매입과 자동 송금은 기본 차단 상태다. 기존 도구 파일과 forge 기록은 보존할 수 있다. 새 도구 생성은 별도의 개발 세션에서 공식 forge를 거쳐 검증한 뒤 운영자가 검토한다.

운영자는 공식 카드를 통한 정상 고객 응대와 별도로 비밀이 없는 문의만 수업 모델에 보낸다. 모델 컨텍스트에 들어갈 수 있는 기존 notes.md에 권리코드, JWT, 토큰, 가족·소득 정보 등의 데이터가 없는지 시작 전에 확인한다. 고객용 원문은 react.jsonl을 거치지 않는다.

## 관리 실행기

managed_launcher.py는 공식 코드 파일 7개의 Git blob 해시를 확인하고 공식 Python 모듈의 Toolbox, Mind와 ASGI 팩터리에 관리 어댑터를 연결한다. 공식 파일을 수정하지 않는다. 공개 POST 요청의 공식 A2A 핸들러에만 1회 실행 권한이 부여된다. 요청 인자나 고객 이름으로 권한을 만들 수 없다. OS 운영자 CLI는 별도로 유지한다.

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

