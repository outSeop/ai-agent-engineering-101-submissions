# 유지 QA 검토 결과

현재 재현 코드는 tests/host_front의 support·unittest·한국어 README와 tests/host_task_state/test_flat_router_review.py다. 이 증거에는 현재 코드를 다시 복제하지 않고 source SHA와 경로를 기록한다. 네 파일은 미리 정한 Model stub의 배선과 original SDK/genuine tool 전달을 검사하며 실제 모델의 자연어 판단은 검사하지 않는다.

고정 prototype에서 유지 suite는 정상3 + 명시적 expected failure1, unexpected success0이다. XFAIL의 HTTP/권한/배선/maintenance setup은 decorator 밖에서 정상 통과해야 하며, 실패하는 경우에만 genuine unavailable/unsupported_request 사유를 확인한다. 원래 지원 밖 compound+repeat 문장은 글자 그대로 유지했다. 미래에 이 문장이 지원되면 unexpected success로 전체검사가 실패해 문서/범위를 다시 검토한다.

첫 유지 시도는 persistent engine을 이전 admission 방식으로 여는 fixture 오류였다. 당시2실패와 의미 없는 setup XFAIL1은 source/harness와 함께 이 디렉터리에 별도 보존한다. 최종 검증에서 이를 genuine 기능 오류나 유효 XFAIL 증거로 사용하지 않았다. 새 fixture는 합성 tasks.sqlite3의 maintenance true→503/Model0, false→stub1 흐름이다. 이전 admission counter는0이고 각 요청 current route는1이다.

router 검토는 malformed RPC400, 사용자별 native backend 권한과 전역 전송 위치의 분리, lock 대기를 포함한 전체 owner 탐색 deadline을 실제 temp DB/fake peer로 검증했다. 시간상한은 소스8초를 확인하면서 테스트만25ms로 가속했다. 원인 제보 후 router·task_state 수정은 root/method 담당이 했으며 QA는 해당 소스를 수정하지 않았다.

fixture 관측시각/expiry는 실행 안에서 공유한다. 원 SDK/genuine wall clock은 바꾸지 않으므로 다른 실행의 남은 초와 reply SHA는 달라질 수 있다. 과거 합성 hash 차이는 실제로 남은 기한1초 차이뿐이었다. 같은 요청의 최종 SDK 문구와 genuine 출력 일치를 사용한다.

과거 evidence와 manifest는 수정하지 않았다. 실제 Model·API·키·원 DB·생산 로그·서비스·금융 호출은0이다. 이 prototype은 새 router/engine 운영 활성화를 뜻하지 않는다. root가 시도한 live NAT 전환은 자동 승인 검토에서 거절됐고 공개 경로는 기존18810이다. 새 로컬 pair는 maintenance closed라고 보고받았으며 QA는 이를 변경하지 않았다.
