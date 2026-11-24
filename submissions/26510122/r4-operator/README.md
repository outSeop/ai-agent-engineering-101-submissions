# 생활 — R4 운영 패키지

서버의 Codex는 **[SERVER_CODEX_HANDOFF.md](SERVER_CODEX_HANDOFF.md)**부터 읽고 실제 배포와 첫 가동을 수행한다. 이 패키지는 설정과 공식 런타임을 전달하며 아직 시장에서 동작한 가게를 증명하지 않는다.

## 폴더

```text
submissions/26510122/
  round-4/                 agent.json, app/, tools/, 실제 가동 후 로그·지갑·장부
  r4-operator/
    kit/                   공식 v5.1 파일 그대로
    run_r4.py              공식 키트 실행 관리; 시장 영업 로직 없음
    requirements.lock.txt  준비 환경에서 검증한 의존성
    sources/upstream.json  원본 URL과 Git blob SHA
    deploy/                읽기 전용 서버 점검과 사용자 서비스 템플릿
```

## 서버 준비와 실행

Python3.12 이상으로 `r4-operator/`에 별도 가상환경을 만든다. 기존 웹서비스의 Python 환경이나 패키지는 그대로 둔다.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
.venv/bin/python run_r4.py check
```

`check`는 원본 키트의 해시, 사람의 설정 변경 범위, A2A 라우트 구성, 도구 provenance, 비공개 파일 제외를 확인한다. 시장 등록·모델 호출·송금·지갑 생성은 하지 않는다. cloudflared 설치와 실제 클래스 모델 접근은 별도 확인 항목이다.

실행은 다음과 같다. 기본 가게명은 사용자가 확정한 `생활`, 시장 `https://market.ourolabs.ai`, 사람용 앱은 서버 로컬18804포트로 둔다. 실행 기본값의 정본은 `run_r4.py`의 `SHOP_NAME`이다. 기존 가동 환경은 먼저 인계 문서의 이름 적용 절차를 따른다.

```bash
.venv/bin/python run_r4.py run --app-port 18804
```

실행기는 저장된 claim code를 `~/.config/ourolabs-market/owner-code`에서 환경 변수로만 읽는다. 다른 경로는 `--owner-file` 또는 `MARKET_OWNER_FILE`로 지정한다. Git·명령 인자·채팅에 인증값을 넣지 않는다. 서버에 기존 인증이 없으면 사용자가 시장 join 페이지에서 받아 서버 터미널에 직접 저장해야 한다. 비밀값은 이 패키지에 포함하지 않았다.

모델은 `{"base":"market"}`으로 고정했고 개인 API로 자동 전환하지 않는다. 클래스 명단·공개 가게 endpoint·공식 system 조건이 맞으면 수업 모델 데스크가 모델을 정한다. 실제 접근 성공은 가입 후 로그로 확인한다. 이 경로가 거절되면 원인을 보고한다.

cloudflared가 없으면 서버 OS·아키텍처에 맞는 공식 바이너리를 설치하고 게시된 SHA256을 검증한다. 기존 HTTPS 프록시가 있으면 `--public-url URL --port PORT`로 대신할 수 있다. 실제 프록시 연결을 먼저 확인한다. 사람용 앱은 기본 로컬 전용이며 `--app-tunnel`을 사용할 때 출력되는 접근코드 링크는 공개하지 않는다.

## 지속 실행

`deploy/ourolabs-market-r4.service`는 다음 독립 체크아웃 위치를 기준으로 썼다.

```text
~/.local/share/ourolabs-r4-checkout/submissions/26510122/r4-operator
```

다른 위치를 사용하면 서비스의 WorkingDirectory·ExecStart·PATH를 실제 경로로 맞춘다. 사용자 서비스는 별도 이름과 포트를 쓰고, 낮은 우선순위·CPU1코어·메모리1GB·프로세스128개 상한으로 시작한다. 서버 자원과 실제 동작을 보고 조정한다. `loginctl ... Linger=yes` 여부를 확인해야 SSH 로그아웃 뒤에도 계속 실행된다. 필요한 권한이 없으면 검증한 서비스 파일과 정확히 필요한 관리 명령을 제시한다.

## 상태 보존과 제출

가동 뒤에는 `round-4/`의 지갑·시장 상태·앱 접근키·에이전트 장부·notes·tools·로그를 같은 가게의 상태로 보존한다. 재시작 때 새 키를 만들거나 같은 계정의 두 가게를 동시에 띄우지 않는다. Git 정리는 추적 파일의 정상 변경만 다루고, 지갑·장부를 지우는 clean/reset을 사용하지 않는다.

필수 실행 로그는 Git ignore 대상이 아니다. 비밀값이 로그에 섞이면 공개 업로드를 멈추고 원본을 비공개로 보존하며 보고한다. 실제 생성 도구는 forge 해시와 함께 보존한다. 지금은 도구·정산·환불의 실전 검증이 끝난 상태가 아니다.

공식 근거: [Week12](https://wpti.dev/ai-agent-engineering-101/week-12.html), [Week13](https://wpti.dev/ai-agent-engineering-101/week-13.html), [R4 키트](https://github.com/Q00/ai-agent-engineering-101/tree/main/scripts/round4), [시장 규약](https://github.com/Q00/agent-market/blob/main/market/ROUND4.md). 배포 환경과 사람 설정을 준비한 것, R4 에이전트가 시장 도구를 만든 것, 실제 거래 성공을 서로 구분한다.
