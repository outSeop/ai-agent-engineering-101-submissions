# 2026-11-28 재고 캐시 장애 복구와 남은 병목

확인 시각: 2026-11-28T02:26:12.125044+09:00. 기존 서비스가 active인 것만으로 영업이 정상이라고 판단한 이전 점검은 불충분했다.

## 실제 원인

11월27일22:03 홍보 publisher를 v9로 교체했으나 기존 재고 캐시와 카드 제안 producer는
같은 mutable tools/forum_marketing 경로에서 v5를 검증했다. `reviewed forum manifest does not match`로
60초 주기 캐시 갱신이 실패했고 TTL150초를 넘긴 캐시가 약4시간 방치됐다.
이 연결을 놓친 것은 이번 운영 수정의 회귀다. 광고는 계속 게시돼도 고객 문의의 fresh catalogue가
열리지 않아 유사어 검색 도구까지 제공되지 않는 조건이 생겼다.

23:27 비점검 침대·침구 문의1건은 가격·SKU를 안내하거나 결제권을 만들지 못했다.
로그의 prefetched inventory=[] 자체는 전체 모델 문맥이 비었다는 증거가 아니다.
이 경로는 원래 빈 financial prefetch와 별도 catalogue를 결합한다. 캐시 stale와 producer 오류를
별도로 확인해 실제 장애를 특정했다. 이 한 사례가 전체 무매출의 유일한 원인이라고 단정하지 않는다.

## 적용

`deploy/price_context_runtime_v8b`: archived v5 소스4개와 forge기록을 byte 그대로 보존하고,
original catalogue v8a / native card keeper 각각의 원 helper에서 verify_source filesystem root만
고정 경로로 연결했다. 원 가격 계산·절대 정책경로·RO SQL·예약·중복판매·sidecar 로직은 불변이다.
새 forge를 만들어낸 것으로 표시하지 않는다. 기존 publisher9·매입8은 유지한다.

기존 customer-context/card-keeper 서비스의 ExecStart drop-in만 갱신한 뒤 daemon-reload했다.
기존 timer 자연 실행을 관찰했고 main/front 재시작·새 timer·새 루프·직접 live diagnostic은 없었다.
Codex 예약 홍보 r4/r4-2/r4-3 재활성화도 하지 않았다.

## 확인된 복구

- source-only catalogue/card 검사 통과, 임시 소스·manifest 변조2건 거절.
- 기존 캐시 timer 연속5회 성공(3.68~3.87초), 대표145행·sidecar145행.
- 여러 시점의 observed_at 증가, TTL150·snapshot SHA와 sidecar 시각 일치.
- 기존 서비스5개 PID/재시작수·두 지갑·DB inode·매입8·가격정책·publisher9 유지, DB quick_check=ok.
- 기존 공개 URL Agent Card HTTP200, outseop-r4·원 지갑·semantic3 edge 유지.

## 아직 해결되지 않은 부분

1. **복합 상품 문의**: 실제 serving bundle public_catalogue_runtime_semantic_v4의 원 SDK 도구를
   fresh 공개 cache로 검사했다. 단일 침대/침구 문의는 유사어 참고 SKU·등급·가격을 렌더링했다
   (각1.43초/1.44초). 정확한 침대 자체나 전체 조건 충족을 보장하는 결과가 아니다.
   `침대와 침구` 복합 문의는 `unsupported_request`로 거절됐다. 원 catalogue prepare 단계는
   단일 문의도0행이지만, serving 경로의 semantic 도구가 이를 보완한다. prepare0행만으로
   serving 전체 실패라고 평가하지 않는다. 이 테스트는 검색어를 테스트가 제공했으며 Model호출0,
   실제 고객 A2A/결제0이다. 모델이 실문의에서 그 선택을 할지는 아직 재검증되지 않았다.
2. **카드 모델 지연**: v5 의존성 오류를 넘어서 원 수업 모델의 대표 상품 선택까지 진입했으나
   `ModelBudgetExceeded: class selection budget exhausted`로 실패했다. 원600초 cooldown 유지.
   서비스 exit0을 카드 갱신 성공이라고 표시하지 않는다. 이번에 카드 갱신 완료를 주장하지 않는다.
3. **유입**: 앞선 동일1시간 비교는 광고4→4, 견적 답글0→0, 결제권0→0, 정산0→0이었다.
   조회수는 공개 API로 알 수 없고 좋아요0만으로 아무도 안 봤다고 단정하지 않는다.
4. **준비·운영 구분**: 새 broad forum 매칭·formatter3/cold-start, 새 매입15/재무캠페인/관측hook은
   이번에 활성화하지 않았다. old-main 재시작은 URL·in-memory task 연속성 문제가 있어 승인 없이 하지 않는다.

복구후 관측 약5.5분 비점검 A2A0·신규정산0. 누적정산2/missing1, 첫구매 추가적립 원장2건 유지.
복구 직후 문의가 없어 문의→정산 개선을 입증하지 못했다. 다음 작업은 복합 문의를 여러 상품군으로
나누되 모델이 판단하고 도구가 검증된 관련 후보만 반환하는 개선과 카드 선택의 모델 호출/예산 검토다.

근거: `evidence/20261128-cache-reader-repair/`의 source-only/qa/live-recovery/actual-front-semantic-tool
안전 결과. 재현 script는 qa에 있다. 운영자·모델 원문사고과정·실고객 원문·키·DB행은 제출하지 않았다.
