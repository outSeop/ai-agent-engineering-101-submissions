# 공통 HOST와 고정 작업 라우터

이 디렉터리는 전송·실행 한도·검증된 코드 조립을 담당한다. 상품 해석과 사업 도구는 수업 모델이 만들고 공식 SDK로 forge한다. 금융 실행은 기존 dispatcher·Signer·장부 경로를 유지한다.

## 두 가지 실행 방식

과거 front 방식은 이전 프로세스로 모르는 task를 전달한다. 이미 가동 중인 프로세스와 메모리 작업을 보존하기 위한 호환 방식이며, 신규 릴리스에 이 체인을 추가하지 않는다.

새 방식은 고정 router18811 → engine18812다. 신규 작업은 engine의 SQLiteTaskStore가 원 SDK protobuf와 논리 소유자 `current`를 한 트랜잭션에 저장한다. 기존 task는 별도 HOST DB에 기록한 원래 port로 직접 전달한다. 중간 릴리스를 경유하지 않는다. 카드 조회는 원래18805로 직접 전달한다. 이후 배포는 같은 engine port·unit·DB를 이어 쓴다.

- `flat_router.py`, `run_flat_router.py`: 고정 peer와 task 소유자 연결. 고객이 목적지나 파일 경로를 지정할 수 없다.
- `flat_transition.py`: 최초18810→18811 전환 보호. 이전 프로세스와 tunnel을 재시작하지 않는다.
- `run_front_edge.py`, `front_edge_app.py`: 공식 SDK 앱 조립, 한 번의 모델 결정 한도, 선택적 영속 저장소 연결.
- `config.py`: manifest가 보증하는 설정. `--operator`를 기준으로 상대 artifact 경로를 해석한다.
- `admission_gate.py`, `transition_guard.py`: 과거 전환 방식과의 호환. 새 engine은 별도 HOST DB maintenance를 쓴다.

materializer는 공통 소스와 원본 forge 자산을 `runtime/releases/<명세 SHA>/`에 복사한다. 생성물은 불변이다. Git 명세의 artifact 경로는 operator 상대경로이며, 실제 절대경로는 생성한 private RUNTIME-BINDING/HOST-CONTEXT에만 들어간다. 이식 시 `--operator`를 새 위치로 지정해 다시 빌드한다. 같은 소스 명세의 SHA는 유지되지만 runtime/front manifest는 생성한 절대경로를 포함하므로 머신마다 달라질 수 있다. 해당 위치에서 생성한 BUILD의 SHA로 검증한다. 과거 증거와 배포 자산의 절대경로는 역사 기록으로 남아 있으며, 이 변경이 기존 금융 장부와 과거 프로세스를 다른 머신으로 자동 이식하지는 않는다.

## 권한과 실패 처리

라우터는 metadata.from을 인증으로 취급하지 않는다. Authorization/Cookie를 원 backend에 그대로 전달하고, SDK가 context.user의 원 owner_resolver로 읽기 권한을 결정한다. taskId의 라우팅 정보는 목적지만 결정한다. 서로 다른 scope의 목적지가 충돌하면 거부한다.

모르는 legacy task는 각 고정 peer의 **자체 ListTasks**에서 소유자를 확인한다. proxy GetTask 성공으로 추정하지 않는다. lock 대기를 포함한8초 한도, 분당12회 discovery, 짧은 부정 cache를 사용한다. 네트워크 장애는 TaskNotFound로 바꾸지 않는다. SendMessage를 새 작업으로 다시 보내지 않는다. 중간 peer가 죽어도 다른 peer의 자체 소유권 증거가 있으면 그 원래 소유자에게 직접 연결한다.

HOST DB는 금융 DB와 분리된 `runtime/a2a-host/state.sqlite3`다. 운영 engine의 CLI와 전환 검사는 router와 정확히 같은 DB 경로를 쓰는지도 확인한다. 디렉터리0700·파일0600·별도 application_id로 보호한다. task 원문과 snapshot은 private runtime에만 둔다. snapshot은 보관용이며 죽은 legacy 프로세스를 대신해 송금·주문을 재실행하거나 다른 사용자에게 돌려주는 근거가 아니다.

공개상품 힌트는 원 PublicContinuity validator로 검사한 최대3개 SKU·등급·가격만300초 저장한다. 복구 후에도 현재 재고·가격·지갑·결제권을 새로 검증한다. SDK Task protobuf의 history는 영속화하지만 원 SDK agent_app의 별도 대화 closure 전체를 복구한다고 주장하지 않는다. public 관리 경로의 명시적 상품 힌트만 별도로 복구한다.

maintenance는 현재 engine의 Send/stream/Cancel을 막고 Get/List와 기존 legacy 접근은 유지한다. 최초 전환은 maintenance=true이며 새 current task가0건인 상태에서만 수행한다. 공개 카드의 원 이름·지갑·URL과 router marker를 확인한 후에만 연다. 실패 시에도 current task가 없고 계속 닫혀 있을 때만 정확히 원래 규칙으로 되돌린다. 한 건이라도 새 task가 저장된 후에는 DB와 router를 유지하고 engine을 고친다.

## 실행과 다음 배포

명세와 BUILD의 SHA를 검토한 뒤:

```sh
"$PYTHON" -B "$FRONT/run_front_edge.py" --operator "$OPERATOR" \
  --edge-manifest-sha "$FRONT_SHA" --sources-only
"$PYTHON" -B "$FRONT/run_flat_router.py" --operator "$OPERATOR" \
  --edge-manifest-sha "$FRONT_SHA" --sources-only
```

실제 engine은 `--serve --persistent-engine --host-state-db "$OPERATOR/runtime/a2a-host/state.sqlite3"`를 명시한다. 라우터는 `--serve`로18811만 연다. 새 listener는 join·Mind.loop·매입·홍보 루프를 시작하지 않는다. 기존 worker가 해당 운영을 이어 한다.

향후 engine 갱신 전 HOST maintenance를 먼저 켜고 router-status의 active_current=0 및 처리 중 task가 없음을 확인한다. 같은18812 unit만 교체하고, 원 DB와 task 조회·공개 힌트 복구를 검증한 후 연다. 미완료 작업을 임의로 재실행하지 않는다. 원래 main·worker·legacy fronts·cloudflared는 이 절차의 재시작 대상이 아니다.

## 검사

`tests/host_task_state`는 원 SDK protobuf 저장·재개, owner scope, 원 ListTasks 필터, 공개 힌트 TTL, 직접 라우팅, 장애·오류 JSON·8초 한도·최초 전환 보호를 검사한다. 임시 HOST DB와 fake peer를 쓴다. `tests/host_front`의 공식 ASGI 배선 검사는 별도 네트워크 격리 namespace에서 실행한다. 실제 모델의 의미 해석과 실고객 정산은 별도 근거로 보고한다.
