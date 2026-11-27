이 디렉터리는 경로를 정규화한 공개용 보기다. 원본 BUILD와 manifest는 private runtime에 바이트 그대로 보존했다. QA 결과는 원래 불변 릴리스와 receipt를 검증한 결과다. BUILD-PUBLIC.json은 실행 입력이 아니다. 재현할 때는 릴리스 명세를 builder로 빌드해 생성한 원래 BUILD.json을 하네스에 전달한다.

# 최종 architecture-only 검토

최종83d11 build에서 유지 ASGI4건은 정상3·원형 expected failure1, unexpected success0이다. 각 지원 사례는 Model stub1회와 ordinary genuine native9/SDK 전달만 확인했다. 실제 모델 의미·새 typed-native 양성·실고객 원문 지원·운영 활성화를 인증하지 않는다.

이전 metadata source unit6건은 이번 CLI-only 변경 때문에 반복하지 않았다. 그때 검사한 protocol/broker source SHA가 최종 runtime의 source bytes와 같음을 확인했다. unit은 base import-loader stub 검사라는 한계가 그대로다.

review-ready 루트의5f8 결과/시각/manifest는 그대로 보존했다. 이 하위폴더가 최종 source-only CLI 옵션을 포함한 artifact의 검증이다. root 보고상 live NAT 적용은 사용자 명시승인이 필요해 차단됐고 새 로컬 pair는 maintenance closed이며 공개 경로는 기존18810이다. 이 QA는 그 상태를 변경하지 않았다.

실제 Model·API·키·생산 데이터/DB·로그·서비스·결제 호출0, root 문서/source 변경0이다. raw 고객·Model thought·private 응답 로그를 포함하지 않는다.
