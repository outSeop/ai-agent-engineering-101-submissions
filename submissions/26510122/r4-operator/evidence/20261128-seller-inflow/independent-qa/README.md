# 판매 유입·포럼 도구 독립 검증

2026-11-28 genuine15의 읽기·선택자료 경계를 검증했습니다. 이 폴더는 실제 게시/판매 성공이나 운영 적용 증거가 아닙니다. 운영 적용과 자연 seller Model 실행은 root의 별도 기록을 따릅니다. 실제 고객 원문, API 원응답, DB, 지갑·인증 값, Model 추론은 포함하지 않습니다.

| 검증 | 결과 | 범위 |
|---|---|---|
| 실제 ordinary SDK `slate_context` | 24.1059초, 후보3/항목9 | 실제 GET+CPU 전체, `kit.testing=False`, 최소 clone DB/NoWallet |
| 추가 ordinary `context` | 24.316초, 6h complete=true | 별도 읽기 호출에서 coverage 직접 확인 |
| 독립 사후 GET | 0.9716초 | 재고/chain2GET와 원 core로 공개 facts 재대조; 위 SDK 시간과 별도 |
| 기존 비즈니스 가드 | 5/5 | 표준 SDK test mode; 부착규격·Latin7개 거절/정상규격 control/strict·reference 가상본문/grade fresh/Cepoch·unknown |
| pool helper | 3/3 | testing flag 없이 helper 직접 검사; 재사용·기한·예외복원/close |
| formatter4 + 원 scope | 후보3→3, 항목9→9, 2957자 | 저장된 원 관측시각만 fixture clock으로 유지한 재현 |

현재 유효한 urgent C(20분~6시간)는0개였습니다. 과거 고정자료의 urgent C1과 합성 epoch/unknown 검증을 현재 게시가능 C가 있다고 해석하면 안 됩니다.

## 검증 모드 구분

15는 legacy `kit.testing=True`에서 pool을 사용하지 않습니다. 따라서5/5는 비즈니스 가드 보존 증거이며 pool의 실제 경로 증거로 세지 않습니다. 실제 ordinary SDK `call`의 testing=False 두 호출이 생산 경로의 네트워크+CPU·coverage 증거입니다. helper3/3은 별도의 순수 단위 검사입니다. testing flag를 수동 지정하지 않았습니다.

실제 SDK는 source15 exact4 및12→11→10→9 hash chain을 사용했습니다. 실제 bank signer나 wallet key를 로드하지 않았고, shop credential은 child의 GET 내부에서만 사용했습니다. 고정 action은 `slate_context`/추가 `context`이며 Model·POST·송금은0입니다. 원 금융 DB는 mode=ro로 공개 identity·예약 unit·자체 게시 메타데이터만 읽어 최소 clone을 만들었습니다. 고객 account/right/실거래 행·identity 파일은 복제하지 않았습니다. source별 private 원본·실패는 runtime에 보존합니다.

slate의 clone DB 불변을 별도 측정했습니다. 추가 context의 원 initializer는 clone schema를 추가할 수 있으며, 이를 금융 원 DB 변경으로 혼동하면 안 됩니다. 실제 원 DB inode는 유지됐습니다. 원 server가 이미 수락한 POST 취소나 exactly-once 전달을 이 읽기 검사로 주장하지 않습니다.

## 재현

`OP`는 제출의 r4-operator 절대경로로 지정합니다. 모든 output은 새로운 `${OP}/runtime/...` 경로를 사용하며 기존 결과를 덮지 않습니다.

```bash
cd "$OP"
unshare -Urn .venv/bin/python -B evidence/20261128-seller-inflow/independent-qa/run_guard_sdk.py \
  --operator "$OP" --source "$OP/deploy/forum_owner_native_v15/tools/forum_marketing" \
  --dependency-dir "$OP/deploy/forum_owner_native_v15/dependencies" \
  --output "$OP/runtime/forum-guard-repro-new"
```

이 외부 test adapter는 경로바인딩·합성fixture/result 쓰기만 추가합니다. 원 source4/forge/SDK 및 추적된 `${OP}/../round-4/codex-r4/test_forum.py::ForumFixture`는 그대로 재사용합니다. public adapter의 경로 변경 후 같은5그룹이 무네트워크 재현됐습니다. 출처·변경 전후 SHA는 `source-adapter-origin.json`에 있습니다.

실제 market GET 재현은 의도적으로 별도 명시 플래그가 필요합니다. 읽기 권한이 있는 운영자만 다음을 실행합니다. 새로운 서비스/주기/게시/Model은 만들지 않습니다.

```bash
.venv/bin/python -B evidence/20261128-seller-inflow/independent-qa/run_owned_canary.py \
  --operator "$OP" --source "$OP/deploy/forum_owner_native_v15/tools/forum_marketing" \
  --dependency-dir "$OP/deploy/forum_owner_native_v15/dependencies" \
  --output "$OP/runtime/forum-live-read-repro-new" \
  --logic-sha ade6803aa1e36c5d48a744cddf59637a29b44d040d1866b0a6ed1de54a56ff22 \
  --allow-read-only-market --verify-coverage
```

이 launcher는 기존 HOST의 자기 process-group 종료만 재사용해75초 총한도를 둡니다. 각 native operation_timeout은30초입니다. 생산 데이터에 직접 native를 실행하지 않습니다. private 출력에는 실제 공개 forum 문장이 있을 수 있으므로 Git/외부 전송 대상으로 선택하지 않습니다.

추가 유지 테스트는 `tests/host_task_state/test_seller_marketing_host_independent.py`입니다. 이 공개 결과의6/6은 기록된518ea… SHA 기준이며, 후속 HOST goal 문구의 root 검증과 구분합니다. 대안 native4의18/18은 atime 비교 수정의 독립 재현이며 실제 판매·추천 적합성 증거가 아닙니다.

## 보존한 실패

11은 실제 native CPU150초 timeout,12는 성능 회복 후 후보0,13은 부착규격 우회 발견,14는 실제 GET 연결 재생성으로15초 coverage 불완전/후보0이었습니다.15의 통과가 이전 실패를 지우지 않습니다. 최초 external fixture의 `__pycache__` 복사 오류와 실행 전 경로 오타도 setup 오류로 별도 요약했습니다.

이 폴더의 정규식 패턴 검사는 별도 scan 결과에 기록합니다. 실제4credential exact-needle 검사는 QA에서 wallet key를 읽지 않는 원칙에 따라 root의 최종 공개검사에 위임했습니다.
