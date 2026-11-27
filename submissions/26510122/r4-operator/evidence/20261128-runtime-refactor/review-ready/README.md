이 디렉터리는 경로를 정규화한 공개용 보기다. 원본 BUILD와 manifest는 private runtime에 바이트 그대로 보존했다. QA 결과는 원래 불변 릴리스와 receipt를 검증한 결과다. BUILD-PUBLIC.json은 실행 입력이 아니다. 재현할 때는 릴리스 명세를 builder로 빌드해 생성한 원래 BUILD.json을 하네스에 전달한다.

# 검토 준비 상태 — 운영 미적용

Architecture-only review build(native9)의 유지 ASGI suite는 정상3 + 명시적 expected failure1, unexpected success0이다. 설정·manifest·loaded_broker·격리 persistent DB·원문/groups stub 배선과 같은 요청의 genuine/SDK 문구 일치를 확인했다. 원 unsupported 혼합 문장은 그대로이고 genuine unsupported_request가 setup에서 확인됐다. 실제 모델의 의미 판단이나 실고객 해결을 검증한 결과가 아니다.

현재 metadata source unit6건은 pinned-base import-loader stub으로 검사했다. canonical BASE_SHA 정합성과 타입검사를 포함한 현재 소스를 읽어 실행했지만, 새 typed metadata가 genuine 도구에서 발행되는 실제 SDK 양성 경로는 검증하지 않았다. native9의 실제 합성 결과에는 새 필드가 없었다.

실제 Model·API·키·생산 데이터/DB·로그·서비스·금융 호출은0이다. 이 작업은 prototype 검토뿐이며 운영 전환을 수행하거나 인증하지 않았다. root 보고상 live NAT 전환은 명시적 사용자 승인이 필요해 차단됐고 공개 경로는 기존18810이며 새 로컬 pair는 maintenance closed다. 별도의 business parser 원문 지원 문제도 해결됐다고 주장하지 않는다.

현재 유지 source 경로를 MANIFEST에 기록한다. 기존 evidence/manifest·root 문서·제품 소스는 이 작업에서 수정하지 않았다. private 원응답/trace/Model thought·고객 자료는 포함하지 않는다.
