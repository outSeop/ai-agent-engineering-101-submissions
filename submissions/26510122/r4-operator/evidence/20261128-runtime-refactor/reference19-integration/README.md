# semantic19 실제 실패 결정의 격리 재생

실제 실패 문의의 원문과 도구 인자를 바꾸지 않고, 당시 모델 결정을 캐시해 전체 SDK ASGI 경로로 재생했다. 새 모델 추론이나 실제 고객 거래는 아니다. 네트워크 격리·NoWallet·금융 실행0이다.

[공개 검증 JSON](../native19-asgi-public-view/cached-actual-public-view.json)은 HTTP200, genuine 도구 문구와 최종 text 일치, artifact data의 payment_request.not_issued, INPUT_REQUIRED, customer_received 이벤트의 text/data/state 일치를 기록한다. 같은 원 재고145행에서 출력1행의 SKU·이름·등급·가격·유통기한을 대조했다. 이벤트는 메모리에서 관측했으며 디스크 trace 영속성 검증은 아니다.

[유지 회귀](../native19-asgi-public-view/maintained4-public-view.json)는 고정 모델 stub 정상3건과 최초 미지원 원형 expected failure1건이다. [어댑터 수정 기록](../native19-asgi-public-view/adapter-corrections-public-view.json)은 재생기 수정 전 실패를 보존한다. 고객 문장을 지원 문법으로 줄이지 않았다.

공개 파일은 경로를 정규화한 검토용 보기다. 원문·실제 상품 식별자·사용자 절대경로는 공개하지 않았다. private 원본 BUILD·원문·재생 결과는 그대로 보존한다. 공개 MANIFEST는 공개 보기의 무결성만 검증하며 원 실행 receipt를 대체하지 않는다.

실제 수업 모델의 별도 합성1회 검증은 [해당 기록](../reference19-class-model/README.md)을 본다. 두 검증 모두 실제 문의 증가·매출·정산 개선을 증명하지 않는다.
