# 서버 Codex: 이 R4 브랜치를 실제로 가동한다

사용자는 랩실 서버에서 이 전략으로 R4를 운영하도록 요청했다. Mac에서 SSH 키를 풀 필요 없이, 지금 실행 중인 서버 Codex가 여기서 이어서 배포한다. 실제 가동은 아직 시작하지 않았다.

## 1. 기존 서버와 가게 상태 확인

저장소 루트 `AGENTS.md`를 읽는다. 변경은 `submissions/26510122/` 안에서 한다. 운영 정책의 정본은 `../round-4/agent.json`이다.

현재 서버 사용자·HOME·Python·여유 자원·cloudflared·사용자 systemd·Linger 상태를 확인한다. `deploy/server_probe.py`는 읽기 전용 조회에 쓸 수 있다. 기존 R4 서비스·가게 이름·지갑·장부가 있다면 그 정체와 실행 위치부터 대조한다. 실제 시장의 `/api/agents`와 `/.well-known/agent-card.json`으로 R4와 기존 owner 가게를 확인한다.

완료 기준: 기존 실행 여부, 보존해야 할 상태, 사용할 별도 경로·포트·사용자 서비스가 명확하다. 기존 웹서비스나 R3 실행을 R4와 혼동하지 않는다. 데이터가 있는 체크아웃을 덮어쓰지 않는다.

## 2. 별도 체크아웃과 환경 준비

신규 배포라면 아래 전용 경로에 브랜치를 받는다. 같은 경로가 이미 있으면 remote·브랜치·변경 파일·지갑 상태를 먼저 확인해 이어서 쓴다.

```bash
git clone --branch round-4-26510122 --single-branch \
  https://github.com/outSeop/ai-agent-engineering-101-submissions.git \
  "$HOME/.local/share/ourolabs-r4-checkout"
cd "$HOME/.local/share/ourolabs-r4-checkout/submissions/26510122/r4-operator"
```

이미 설치된 Python3.12+를 찾아 전용 `.venv`를 만들고 `requirements.lock.txt`를 설치한다. 기존 웹서비스의 가상환경에 패키지를 추가하지 않는다. cloudflared는 기존 설치를 우선 사용하고 새로 필요하면 공식 배포본과 게시된 SHA256을 확인한다.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
.venv/bin/python run_r4.py check
```

완료 기준: 공식 키트7개 파일의 원본 Git blob 해시가 모두 일치하고, 사람의 agent.json 변경은 persona·goal·llm뿐이며, A2A 라우트가 만들어진다. 초기 tools에는 `.gitkeep`만 있다. 공식 bare card의 빈 skills 경고는 실제 시장 기능 검증을 통과했다는 뜻이 아니다.

## 3. 인증과 지속 실행

서버의 기존 market claim code 파일을 사용한다. 기본 경로는 `~/.config/ourolabs-market/owner-code`, 권한은600으로 둔다. 실제 값은 출력·Git·채팅에 넣지 않는다. 파일이 없으면 사용자가 join 페이지에서 발급받아 서버 터미널에 직접 입력하게 한다. 이 브랜치에는 인증값·지갑·Mac 로그인 캐시가 없다.

수업 모델 데스크를 사용한다. 개인 OpenAI 키나 Codex 로그인으로 자동 대체하지 않는다. 초기 가게명은 `outseop-r4`, 역할은 공식 키트 기본 shop이다. 이미 같은 owner의 가게가 있다면 새 가게를 추가하지 말고 기존 지갑·경로와 연결한다.

`deploy/ourolabs-market-r4.service`를 현재 사용자 서비스로 설치하기 전에 경로와18804포트의 사용 여부를 확인한다. 템플릿이 실제 체크아웃 위치를 가리키도록 맞추고 `systemd-analyze --user verify`로 검사한다. 새 서비스명은 `ourolabs-market-r4.service`다.

```bash
mkdir -p "$HOME/.config/systemd/user"
cp deploy/ourolabs-market-r4.service "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now ourolabs-market-r4.service
systemctl --user status ourolabs-market-r4.service --no-pager
```

기존 동명 서비스 파일이 다르면 먼저 차이를 검토한다. Linger=yes와 활성 사용자 manager를 확인해 로그아웃 뒤의 가동을 보장한다. 관리자 권한이 필요한 단계는 준비된 변경과 필요한 명령을 명시하고 사용자가 서버에서 직접 수행하게 한다.

완료 기준: 서비스 active, 예상 경로의 프로세스, 외부에서 응답하는 가게 카드, 시장에 같은 가게·같은 지갑 등록, 실제 수업 모델 호출 성공이 확인된다. 서비스가 active인 것만으로 영업 기능 완성을 보고하지 않는다.

## 4. R4 에이전트가 도구를 만들도록 운영

여기서 작업하는 서버 Codex는 환경과 persona·goal·모델 설정을 다룬다. 시장 읽기·조달·견적·정산·A2A 응대·대기열·마일리지·환불 도구는 실행 중인 **R4 에이전트가 forge_tool로 직접 생성하고 테스트**한다. `logs/forge.jsonl`, `logs/react.jsonl`, 각 도구의 `forge.json`을 증거로 확인한다. 도구 오류는 해당 에이전트가 read_tool·forge_tool로 수정하도록 유도한다. 사람이 영업 logic.py를 넣거나 forge 기록을 대신 만들면 과제의 과정 증거가 사라진다.

최소 판매 경로를 먼저 확인한 뒤 두 혜택을 공개한다. 실제 구현 판단은 현재 entity card와 고객 도구의 제약을 기준으로 한다. 다음은 검증 기준이며 미리 작성된 시장 도구가 아니다.

- 현재 재고 unit·등급·가격·수수료를 대조한 유효 checkout_jwt를 제공하고 중복 판매를 막는다.
- 즉시 응답하는 A2A handler가 번호표를 주면 문의가 영속 큐에 남아 실제로 처리된다. `defer:true`가 즉시 응답과 inbox 전달을 동시에 한다고 가정하지 않는다.
- 대기할인은 실제 바쁨과 발급 권리를 확인해 이번 거래에1회 적용한다. 예상 시간은 실측하며 번호표와 재고 예약을 구분한다.
- 마일리지는 정상 정산·인도 후1회 적립한다. 새 적립은 그 결제에 사용하지 않고 다음 거래부터 쓴다. 기존 잔액과 이번 대기할인을 함께 차감할 수 있다.
- 방문이 바뀌면 taskId도 바뀔 수 있다. 이름·metadata.from·공개 tx만으로 타인의 잔액을 차감하지 않는다. 실제 고객이 수행 가능한 권리 확인 경로가 검증되기 전에는 자동 사용 가능하다고 광고하지 않는다.
- paid-not-settled, pending, 정상 정산, 초기 문제, 환불을 구분한다. 원 송금인·실지출·기존 환불을 확인하고 미확정 송금을 반복하지 않는다. 시장에 환불 API가 있다고 가정하지 않는다.

완료 기준: 실제 생성·테스트 기록과 현재 기능 상태가 연결된다. 모의 실험 수치나 만들어진 함수 이름을 실거래 성공으로 보고하지 않는다. 인위적인 거래로 실적을 꾸미지 않는다.

## 5. 사용자에게 인계할 결과

가게명·시장 카드 URL·사용자 서비스·실행 경로와 함께 다음 상태를 각각 보고한다: 시장 등록, 수업 모델 호출, 생성 도구/테스트, 정상 판매, 대기표 처리, 구매 후 적립, 다음 거래 차감, 환불 검증. 확인되지 않은 것은 미확인으로 남긴다. 직접 관찰한 실제 고객 거래만 실거래로 센다.

운영 중 생긴 notes·장부·지갑·도구를 재시작에도 보존한다. 필수 로그는 제외하거나 다듬지 않는다. 공개 전 비밀값이 없는지 확인하고, 발견되면 원본을 비공개로 보존하며 공개 업로드를 멈춘다. 작업 단위별 커밋으로 시도와 수정 기록을 남기고, 최종 제출 PR은 실제 실행 증거와 함께 별도로 준비한다.
