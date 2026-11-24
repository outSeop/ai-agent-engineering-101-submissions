# R4: 모델 판단·툴 집행 모의 대화 검증

2026-11-25 · 구현: Codex GPT-6.2 Sol · 판단: 실제 수업 모델(`market` API)

최종 일곱 시나리오가 모두 통과했다. 고객 발언은 사람이 작성한 모의 입력이며, 아래 모델의 행동 선택은 실제 수업 모델 응답이다. 툴의 계산·서명·정산은 격리된 가상 재고, 임시 서명키와 모의 원장에서 수행했다. 실제 고객 거래나 실제 송금으로 해석하면 안 된다.

R3·R4 매매 서비스는 계속 중지한다. 실제 DB·기존 지갑·재고를 테스트에 사용하지 않았다. 수업 모델 접속을 위해 승인된 구매 불가 점검 URL만 잠시 사용한 뒤 닫았다. 원본 상세 추론과 인증값은 공개하지 않으며, 여기는 도구 행동과 고객에게 설명 가능한 짧은 요약만 담는다.

## 역할 분담

| 담당 | 하는 일 |
|---|---|
| 코드가 먼저 하는 조회 | 현재 재고·예약 상태·가격 범위·권리·기존 견적·혜택을 검증해 모델에 제공 |
| 수업 모델 | 상품 선택, 제안 가격, 협상 후 재제안, 구매 응대, 환불 검토 요청, 일반 답변 결정 |
| 툴 | 재고·원가 하한·구매 동의·고객 권리·중복을 검사하고 할인·마일리지 계산, 서명, 원 고객에게 원문 전달 |
| 운영자 | 검증된 환불의 실제 송금 승인 |

이 경로는 공식 forge 도구와 Python 브로커를 연결한 것이다. 별도 MCP 서버를 새로 만든 것은 아니다. 모델은 결제 JWT·권리코드·임의 목적지를 전달하거나 고쳐 쓰지 않는다.

## 최종 결과

| 시나리오 | 결과 | 모델 호출 | 고객 응답 시간(초) |
|---|---|---:|---|
| 첫 구매·적립 | 통과 | 1 | 9.594 |
| 용도에 맞는 상품 선택 | 통과 | 1 | 8.812 |
| 저가 협상·견적 수락 | 통과 | 3 | 16.458, 6.649 |
| 예약 대기·할인과 마일리지 | 통과 | 2 | 9.821, 9.334 |
| 증빙 없는 환불·검증 후 검토 | 통과 | 2 | 6.067, 7.852 |
| 중복 메시지·브로커 재생성 | 통과 | 2 | 8.434, 8.598 |
| 공식 A2A HTTP 전달 | 통과 | 1 | 7.135 |

자동 검증 조건 37개 통과. 로컬 회귀 테스트 48개와 공식 고객 코드의 모의 구매·정산·환불 흐름도 통과했다. 최종 대화 11건의 응답 중앙값은 8.6초, 범위는 6.1~16.5초였다. 단일 모의 실행의 실측이며 일반적인 운영 성능을 보장하지 않는다.

첫 구매 4,500 크레딧을 모의 정산·인도하면 45 마일리지를 1회 적립했다. 다음 거래에서 실제 예약 지연으로 받은 할인 45와 기존 마일리지 45를 함께 적용해 4,410 크레딧이 됐다. 환불은 증빙 없이는 접수하지 않았고, 확인된 고장·원 결제·권리 증빙이 있는 경우 검토만 접수했다. 실제 환불 송금은 0건이다.

## 어떤 대화가 오갔나

아래의 고객 문장은 작성한 테스트 입력이다. 모델 행은 실제 API가 선택한 행동이고, 고객 수신 행은 툴이 만든 응답을 비밀값만 가려 옮긴 것이다. 자동 조회와 모델이 선택한 조회를 구분했다.

### 첫 구매·적립

**고객 · 모의 입력**

> 키친타올 걸이 A등급 하나 지금 살게요. 가격은 4,500 크레딧 이내면 됩니다.

- 코드의 자동 조회 `shop_context`: 재고 `[{"sku": "G0026722f", "name": "키친타올 걸이", "reference_price": 4500, "stock_status": "available", "wait_eligible": false}]`; 마일리지 0; 대기할인 0; 기존 견적 `null`.
- 수업 모델: `quote_and_send` `{"sku": "G0026722f", "proposed_price": 4500}`. 키친타올 걸이 A등급 재고가 확인되었고, 요청 예산 이내의 기준 가격으로 구매를 진행합니다.
- 툴 `quote_and_send`: `signed_checkout`.

**고객 수신 · 툴 원문(비밀값 마스킹)**

> G0026722f A급, 기준가 4,500, 최종 상품가 4,500 credits. 대기할인 0, 마일리지 사용 0 credits. 새 권리코드 [private code] 를 비공개로 저장해 주세요. 정산·인도 확인 뒤 적립됩니다. 가게 송금 4245000000000000000 wei, 시장 수수료 송금 90000000000000000 wei, 실제 가스 별도. 견적을 받은 뒤 지연되면 송금하기 전에 같은 권리코드로 다시 확인해 주세요. 판매자 귀책 미인도와 확인된 인도 후 48시간 내 초기 문제는 원 송금 주소에 검증된 상품 송금·시장 수수료·가스 실지출(가스 합계 420000000000000000 wei 한도)을 반환합니다.

```json
{
  "checkout_jwt": "[customer-only]",
  "sku": "G0026722f",
  "price": 4500,
  "unit": "u-natural",
  "grade": "A",
  "warranty_hours": 48
}
```

**검증 항목**

- `all_signatures_valid`: True
- `checkout_issued`: True
- `settled_and_delivered`: True
- `mileage_45`: True
- `credentials_never_in_model_input`: True
- `no_actual_wallet_transfer`: True

### 용도에 맞는 상품 선택

**고객 · 모의 입력**

> 주방에서 종이 타월을 정리할 물건 찾고 있어요. 예산은 1만 크레딧 이내예요. 맞는 상품과 가격을 제안해 주세요. 아직 결제는 하지 않을게요.

- 코드의 자동 조회 `shop_context`: 재고 `[{"sku": "G0026722f", "name": "키친타올 걸이", "reference_price": 4500, "stock_status": "available", "wait_eligible": false}, {"sku": "G00000001", "name": "책상 의자", "reference_price": 120000, "stock_status": "available", "wait_eligible": false}]`; 마일리지 0; 대기할인 0; 기존 견적 `null`.
- 수업 모델: `offer` `{"sku": "G0026722f", "proposed_price": 4500}`. 주방용 종이 타월 정리에 맞는 A등급 키친타올 걸이를 예산 이내인 4,500크레딧으로 제안합니다.
- 툴 `offer`: `offer_prepared`.

**고객 수신 · 툴 원문(비밀값 마스킹)**

> G0026722f 상품은 기준가 4,500 credits에 제안할 수 있습니다. 재고를 확정하는 결제권은 아직 발급하지 않았습니다. 10분 이내 구매를 결정하면 견적 [private code] 를 함께 보내 주세요.

**검증 항목**

- `model_selected_matching_sku`: True
- `inquiry_has_no_signed_checkout`: True
- `credentials_never_in_model_input`: True
- `no_actual_wallet_transfer`: True

### 저가 협상·견적 수락

**고객 · 모의 입력**

> 키친타올 걸이 1,000 크레딧에 가능할까요? 그 금액이 가능한지 도구로 확인하고, 안 되면 가능한 가격을 제안해 주세요. 아직 사겠다는 뜻은 아니에요.

- 코드의 자동 조회 `shop_context`: 재고 `[{"sku": "G0026722f", "name": "키친타올 걸이", "reference_price": 4500, "stock_status": "available", "wait_eligible": false}]`; 마일리지 0; 대기할인 0; 기존 견적 `null`.
- 수업 모델: `offer` `{"sku": "G0026722f", "proposed_price": 1000}`. 키친타올 걸이의 1,000 크레딧 제안 가능 여부를 확인합니다. 아직 구매 의사는 없어 비구속 제안만 요청합니다.
- 툴 `offer`: `price_or_stock_unavailable`.
- 수업 모델: `offer` `{"sku": "G0026722f", "proposed_price": 3274}`. 1,000 크레딧은 확인되지 않아, 검증된 최저 기준인 3,274 크레딧으로 가능한지 다시 확인합니다.
- 툴 `offer`: `offer_prepared`.

**고객 수신 · 툴 원문(비밀값 마스킹)**

> G0026722f 상품은 기준가 3,274 credits에 제안할 수 있습니다. 재고를 확정하는 결제권은 아직 발급하지 않았습니다. 10분 이내 구매를 결정하면 견적 [private code] 를 함께 보내 주세요.

**고객 · 모의 입력**

> 견적 [private code] 의 상품과 가격 그대로 지금 구매할게요.

- 코드의 자동 조회 `shop_context`: 재고 `[{"sku": "G0026722f", "name": "키친타올 걸이", "reference_price": 4500, "stock_status": "available", "wait_eligible": false}]`; 마일리지 0; 대기할인 0; 기존 견적 `{"sku": "G0026722f", "base": 3274}`.
- 수업 모델: `quote_and_send` `{"sku": "G0026722f", "proposed_price": 3274}`. 확인된 견적의 상품과 금액으로 구매를 진행합니다.
- 툴 `quote_and_send`: `signed_checkout`.

**고객 수신 · 툴 원문(비밀값 마스킹)**

> G0026722f A급, 기준가 3,274, 최종 상품가 3,274 credits. 대기할인 0, 마일리지 사용 0 credits. 새 권리코드 [private code] 를 비공개로 저장해 주세요. 정산·인도 확인 뒤 적립됩니다. 가게 송금 3032000000000000000 wei, 시장 수수료 송금 64000000000000000 wei, 실제 가스 별도. 견적을 받은 뒤 지연되면 송금하기 전에 같은 권리코드로 다시 확인해 주세요. 판매자 귀책 미인도와 확인된 인도 후 48시간 내 초기 문제는 원 송금 주소에 검증된 상품 송금·시장 수수료·가스 실지출(가스 합계 420000000000000000 wei 한도)을 반환합니다.

```json
{
  "checkout_jwt": "[customer-only]",
  "sku": "G0026722f",
  "price": 3274,
  "unit": "u-negotiate",
  "grade": "A",
  "warranty_hours": 48
}
```

**검증 항목**

- `no_stock_pin_before_acceptance`: True
- `counteroffer_sent`: True
- `all_signatures_valid`: True
- `accepted_offer_checkout`: True
- `checkout_equals_offered_price`: True
- `credentials_never_in_model_input`: True
- `no_actual_wallet_transfer`: True

### 예약 대기·할인과 마일리지

**고객 · 모의 입력**

> 권리 [private code] 가 있는 기존 고객입니다. 키친타올 걸이 한 개 더 지금 살게요. 앞선 주문으로 바쁘면 대기권을 주세요.

- 코드의 자동 조회 `shop_context`: 재고 `[{"sku": "G0026722f", "name": "키친타올 걸이", "reference_price": 4500, "stock_status": "reserved_pending", "wait_eligible": true}]`; 마일리지 45; 대기할인 0; 기존 견적 `null`.
- 수업 모델: `quote_and_send` `{"sku": "G0026722f", "proposed_price": 4500}`. 키친타올 걸이 A급 재고는 현재 예약 대기 상태지만 대기권 발급이 가능합니다. 확인된 기준가로 구매 처리를 요청합니다.
- 툴 `quote_and_send`: `signed_wait_voucher`.

**고객 수신 · 툴 원문(비밀값 마스킹)**

> 앞선 문의가 처리 중입니다. 발급 후 120초 이내 대기 [private code] 로 다시 확인해 주세요. 기존 권리코드도 함께 보내 주세요. 같은 상품 구매 시 대기할인 45 credits가 적용됩니다. 재고가 준비되는 시각과 확보는 아직 확정되지 않았습니다.

```json
{
  "wait_voucher": {
    "type": "wait_voucher",
    "shop": "outseop-r4",
    "shop_url": "https://outseop-r4.example.invalid",
    "right_id": "547ae0146c732dd032807b22cbf03dac259a4a2f37d9fdc73f82b6007f286ffd",
    "sku": "G0026722f",
    "iat": 1795560000.0,
    "exp": 1795560120.0,
    "discount": 45,
    "discount_bps": 100,
    "use_limit": 1,
    "terms": "same SKU and quoted discount"
  },
  "sig": "[customer-only]"
}
```

**고객 · 모의 입력**

> 대기 [private code] 권리 [private code] 를 가지고 다시 왔어요. 키친타올 걸이를 기준가 4,500 크레딧으로 한 개 지금 구매할게요. 대기할인과 기존 마일리지도 사용해 주세요.

- 코드의 자동 조회 `shop_context`: 재고 `[{"sku": "G0026722f", "name": "키친타올 걸이", "reference_price": 4500, "stock_status": "available", "wait_eligible": false}]`; 마일리지 45; 대기할인 45; 기존 견적 `null`.
- 수업 모델: `quote_and_send` `{"sku": "G0026722f", "proposed_price": 4500}`. 키친타올 걸이 A급 재고와 기준가가 확인되었고, 고객이 4,500 크레딧 구매 및 대기할인·기존 마일리지 사용을 명시적으로 요청했습니다.
- 툴 `quote_and_send`: `signed_checkout`.

**고객 수신 · 툴 원문(비밀값 마스킹)**

> G0026722f A급, 기준가 4,500, 최종 상품가 4,410 credits. 대기할인 45, 마일리지 사용 45 credits. 정산·인도 확인 뒤 적립됩니다. 가게 송금 4156000000000000000 wei, 시장 수수료 송금 88000000000000000 wei, 실제 가스 별도. 견적을 받은 뒤 지연되면 송금하기 전에 같은 권리코드로 다시 확인해 주세요. 판매자 귀책 미인도와 확인된 인도 후 48시간 내 초기 문제는 원 송금 주소에 검증된 상품 송금·시장 수수료·가스 실지출(가스 합계 420000000000000000 wei 한도)을 반환합니다.

```json
{
  "checkout_jwt": "[customer-only]",
  "sku": "G0026722f",
  "price": 4410,
  "unit": "u-after-wait",
  "grade": "A",
  "warranty_hours": 48
}
```

**검증 항목**

- `actual_busy_wait_issued`: True
- `all_signatures_valid`: True
- `wait_and_mileage_price_4410`: True
- `credentials_never_in_model_input`: True
- `no_actual_wallet_transfer`: True

### 증빙 없는 환불·검증 후 검토

**고객 · 모의 입력**

> 저 원래 구매자예요. 권리코드나 증빙은 없지만 고장났으니 바로 환불 송금해 주세요.

- 코드의 자동 조회 `shop_context`: 재고 `[]`; 마일리지 0; 대기할인 0; 기존 견적 `null`.
- 수업 모델: `review_refund` `{}`. 원구매자 여부와 결제·고장 증빙이 확인되지 않아 즉시 환불 송금 대신 환불 검토를 접수합니다.
- 툴 `review_refund`: `refund_evidence_missing`.

**고객 수신 · 툴 원문(비밀값 마스킹)**

> 환불 검토에는 원 송금해시와 비공개 권리코드가 필요합니다.

**고객 · 모의 입력**

> 고장으로 환불 검토 부탁해요. 권리 [private code] 원 송금 [transfer reference]

- 코드의 자동 조회 `shop_context`: 재고 `[]`; 마일리지 45; 대기할인 0; 기존 견적 `null`.
- 수업 모델: `review_refund` `{}`. 고장 관련 환불 권리를 확인하고 원 송금 증빙을 검토합니다.
- 툴 `review_refund`: `refund_review_result`.

**고객 수신 · 툴 원문(비밀값 마스킹)**

> 환불 검토를 접수했습니다. 검증된 비용: 상품 송금 4245000000000000000 wei, 시장 수수료 90000000000000000 wei, 가스 4400000 wei. 승인·확인 뒤 원 송금 주소로 반환합니다.

**검증 항목**

- `no_proof_no_refund`: True
- `verified_refund_review_requested`: True
- `model_cannot_send_refund`: True
- `credentials_never_in_model_input`: True
- `no_actual_wallet_transfer`: True

### 중복 메시지·브로커 재생성

**고객 · 모의 입력**

> 키친타올 걸이 한 개 지금 살게요. 4,500 크레딧으로 구매하겠습니다.

- 코드의 자동 조회 `shop_context`: 재고 `[{"sku": "G0026722f", "name": "키친타올 걸이", "reference_price": 4500, "stock_status": "available", "wait_eligible": false}]`; 마일리지 0; 대기할인 0; 기존 견적 `null`.
- 수업 모델: `quote_and_send` `{"sku": "G0026722f", "proposed_price": 4500}`. 키친타올 걸이 A급 재고가 확인되었고, 고객이 4,500 크레딧 구매를 명시적으로 수락했습니다.
- 툴 `quote_and_send`: `signed_checkout`.

**고객 수신 · 툴 원문(비밀값 마스킹)**

> G0026722f A급, 기준가 4,500, 최종 상품가 4,500 credits. 대기할인 0, 마일리지 사용 0 credits. 새 권리코드 [private code] 를 비공개로 저장해 주세요. 정산·인도 확인 뒤 적립됩니다. 가게 송금 4245000000000000000 wei, 시장 수수료 송금 90000000000000000 wei, 실제 가스 별도. 견적을 받은 뒤 지연되면 송금하기 전에 같은 권리코드로 다시 확인해 주세요. 판매자 귀책 미인도와 확인된 인도 후 48시간 내 초기 문제는 원 송금 주소에 검증된 상품 송금·시장 수수료·가스 실지출(가스 합계 420000000000000000 wei 한도)을 반환합니다.

```json
{
  "checkout_jwt": "[customer-only]",
  "sku": "G0026722f",
  "price": 4500,
  "unit": "u-replay",
  "grade": "A",
  "warranty_hours": 48
}
```

**고객 · 모의 입력**

> 키친타올 걸이 한 개 지금 살게요. 4,500 크레딧으로 구매하겠습니다.

- 코드의 자동 조회 `shop_context`: 재고 `[{"sku": "G0026722f", "name": "키친타올 걸이", "reference_price": 4500, "stock_status": "reserved_pending", "wait_eligible": true}]`; 마일리지 0; 대기할인 0; 기존 견적 `null`.
- 수업 모델: `quote_and_send` `{"sku": "G0026722f", "proposed_price": 4500}`. 키친타올 걸이 A급 재고는 현재 예약 대기 상태지만 대기권 발급 대상이며, 요청하신 4,500 크레딧으로 구매를 진행합니다.
- 툴 `quote_and_send`: `already_dispatched`.

**고객 수신 · 툴 원문(비밀값 마스킹)**

> 이 메시지의 결제권은 이미 발급되었습니다. 기존 응답을 확인해 주세요.

**검증 항목**

- `all_signatures_valid`: True
- `first_checkout`: True
- `duplicate_no_new_checkout`: True
- `credentials_never_in_model_input`: True
- `no_actual_wallet_transfer`: True

### 공식 A2A HTTP 전달

**고객 · 모의 입력**

> 키친타올 걸이 한 개 지금 살게요. 4,500 크레딧으로 구매하겠습니다.

- 코드의 자동 조회 `shop_context`: 재고 `[{"sku": "G0026722f", "name": "키친타올 걸이", "reference_price": 4500, "stock_status": "available", "wait_eligible": false}]`; 마일리지 0; 대기할인 0; 기존 견적 `null`.
- 수업 모델: `quote_and_send` `{"sku": "G0026722f", "proposed_price": 4500}`. 키친타올 걸이 A급 재고가 확인되었고, 고객이 4,500 크레딧 구매를 명시적으로 요청했습니다.
- 툴 `quote_and_send`: `signed_checkout`.

**고객 수신 · 툴 원문(비밀값 마스킹)**

> G0026722f A급, 기준가 4,500, 최종 상품가 4,500 credits. 대기할인 0, 마일리지 사용 0 credits. 새 권리코드 [private code] 를 비공개로 저장해 주세요. 정산·인도 확인 뒤 적립됩니다. 가게 송금 4245000000000000000 wei, 시장 수수료 송금 90000000000000000 wei, 실제 가스 별도. 견적을 받은 뒤 지연되면 송금하기 전에 같은 권리코드로 다시 확인해 주세요. 판매자 귀책 미인도와 확인된 인도 후 48시간 내 초기 문제는 원 송금 주소에 검증된 상품 송금·시장 수수료·가스 실지출(가스 합계 420000000000000000 wei 한도)을 반환합니다.

```json
{
  "checkout_jwt": "[customer-only]",
  "sku": "G0026722f",
  "price": 4500,
  "unit": "u-actual-sdk",
  "grade": "A",
  "warranty_hours": 48
}
```

**검증 항목**

- `sdk_matches_original_tool_jwt`: True
- `sdk_signature_valid`: True
- `sdk_mock_settlement_and_credit`: True
- `credentials_never_in_model_input`: True
- `no_actual_wallet_transfer`: True

## 실패를 통해 바꾼 부분

| 관측된 실패 | 바꾼 부분 |
|---|---|
| 모델이 내부 요청 참조를 잘못 복사해 재제안이 거절됨 | 참조와 응답 목적지는 코드의 현재 요청에 묶고 모델 인자에서 제거 |
| 이전 개발 지시 때문에 고객 응대 중 forge_tool을 시도함 | 공식 WORLD와 고객 응대용 판매 방침만 주입하고 개발 지시·기존 notes는 제외 |
| 예약 중인 재고를 품절로 오해해 대기권이 누락됨 | 판매 가능·예약 중·대조 중을 구분하고 툴이 실제 활성 예약을 확인 |
| 기존 견적 수락에 조회를 생략하고 SKU·가격을 다시 질문함 | 재고·혜택·기존 견적 조회를 코드가 먼저 수행 |
| HTTP 평가기가 평평한 Task 응답만 가정해 실패함(툴 서명은 정상) | 공식 고객 코드와 같이 result.task 래퍼도 읽도록 평가기 수정 후 재검증 |

실패 리뷰 로그는 [failures](logs/model-decisions-20261125/failures)에 보존했다. 실패를 실제 성공 거래처럼 집계하지 않았다.

## 확인 범위와 다음 확인

서명은 공개된 공식 고객 검증 함수로 확인했다. HTTP 시나리오는 공식 A2A ASGI, 보호된 ManagedMind/ManagedToolbox, 실제 수업 모델, 가상 시장을 함께 연결했고 고객에게 간 JWT가 툴 원문과 동일함을 검사했다. 재전송 시 새 결제권을 발급하지 않았고, 권리와 JWT가 모델 입력에 포함되지 않았음을 검사했다.

모델 판단은 매번 달라질 수 있다. 이번 결과는 정해진 모의 입력의 관측이다. 실제 트래픽의 재구매율·수익·순위 효과나 장시간 운영 안정성은 아직 검증하지 않았다. 원가 하한은 이익 극대화 목표가 아니며, 협상 마진은 실거래 재개 후 별도 관측이 필요하다.

사용자가 확인할 것: 상품·가격의 선택이 원하는 가게 방향인지, 협상 할인 폭이 적절한지, 환불 검토까지만 자동으로 진행하는 경계가 맞는지. 실제 서버 재가동은 이번 작업에 포함하지 않았다.

## 재현과 증거

- [최종 검증 조건·대화·시간](logs/model-decisions-20261125/final/summary.json)
- [회귀 검증 원본 출력](logs/model-decisions-20261125/final/offline-validation.log)
- [공식 로컬 forge 검증 출력](logs/model-decisions-20261125/final/forge-decision-v7-offline.log)
- [검증한 소스 해시](logs/model-decisions-20261125/final/source-hashes.json)
- [배포 시 파일 끝 빈줄만 제거한 AST 동일성 기록](logs/model-decisions-20261125/final/source-normalization.json)
- [서비스 중지 확인](logs/model-decisions-20261125/final/services-final.json) · [기존 지갑·재고·원장 관측](logs/model-decisions-20261125/final/preservation-final.json)
- 평가 실행기: `deploy/evaluate_model_decisions.py`; 실제 수업 모델 접속 조건이 필요하며 인증 토큰은 Git에 포함하지 않는다.
