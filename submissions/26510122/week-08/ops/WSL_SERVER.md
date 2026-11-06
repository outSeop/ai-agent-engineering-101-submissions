# Windows WSL2로 기존 시장 에이전트 이전

이전 대상은 Windows 사용자의 Ubuntu WSL2다. 코드와 DB는 `/home/<사용자>/Documents/projects/` 등 Linux 파일시스템에 둔다. `/mnt/c` 위에서 DB를 운영하지 않는다. Windows 쪽 Tailscale와 OpenSSH를 통해 접근하고, SSH 명령에서 `wsl.exe -d Ubuntu -u <Linux사용자> -- ...`로 Linux 명령을 실행한다. Windows 사용자와 Linux 사용자는 다를 수 있다.

## 준비

- `wsl -l -v`에서 배포판 VERSION 2, Ubuntu에서 PID 1이 systemd인지 확인한다.
- 현재 배포 브랜치 `seller-market-share`를 clone하고 `requirements.txt`로 새 `.venv`를 만든다. 이전 컴퓨터의 가상환경은 복사하지 않는다.
- Ubuntu 사용자로 Codex CLI를 설치·로그인하고, `harness.py`가 쓰는 CLI 플래그를 확인한다. 기존 모델을 그대로 쓰는 JSON 응답 점검 1회와 전체 테스트를 수행한다.
- Windows SSH 방화벽과 공개키의 `from=`은 관리용 컴퓨터의 Tailscale IP로 제한한다. 실제 IP·개인키·인증 캐시는 이 문서나 Git에 넣지 않는다.

## WSL과 사용자 서비스 유지

systemd 서비스가 실행 중인 것만으로 WSL 인스턴스가 계속 유지된다고 가정하지 않는다. Ubuntu에서 `sudo loginctl enable-linger "$USER"`를 설정하고, 관리자 Windows PowerShell에서 `ops/wsl_keepalive.ps1 -LinuxUser <Linux사용자>`를 실행한다. 스크립트는 실행한 Windows 계정에 부팅·로그인 트리거를 가진 전용 작업을 만들고 `sleep infinity`를 통해 WSL을 유지한다. 다른 작업은 변경하지 않는다.

Windows에서 `Get-ScheduledTask -TaskName OutseopMarketWSL`이 `Running`인지, Ubuntu에서 `/usr/bin/sleep infinity`가 실제로 있는지 확인한다. S4U 등록은 Windows 암호를 저장하지 않는다. Windows 계정·학교 정책에 따라 작업 실행에 제약이 있을 수 있으므로, 작업 등록 성공과 실제 WSL 실행을 각각 검사한다. Windows의 네트워크 인증이 필요한 공유 드라이브 대신 WSL 내부의 로컬 경로를 사용한다.

전원 연결 시 자동 절전이 꺼져 있는지도 확인한다. Windows 업데이트·재부팅 후 무인 복구 여부는 별도로 검사하며, 작업 등록만으로 재부팅 검증이 끝났다고 기록하지 않는다.

## 최종 상태 이전

대상 환경과 모델 호출이 준비된 뒤 기존 Linux에서 세 `outseop-r3-*` 서비스를 중단한다. 이전 중 다시 시작되지 않도록 mask하고, 별도 작업자까지 종료됐는지 `ops/home_server.py`의 검사로 확인한다. 재부팅 뒤에도 구 서버를 은퇴시킬 때는 runtime mask에만 의존하지 말고 기존 서비스의 영구 비활성화도 확인한다.

`ops/home_server.py export`로 기존 지갑·owner code·SQLite DB·미확정 매입·정책·원본 로그·검증된 release를 ignored `state/migration/`에 내보낸다. 최신 도구는 매입 작업자 PID와 상태 파일도 검사하고 `procurement-console.log`도 보존한다. 비공개 묶음은 SSH로만 전달하고 양끝 SHA-256을 대조한다. 채팅이나 Git에 묶음을 올리지 않는다.

Ubuntu에서 `restore`와 `render`를 실행한 뒤 [Linux 이전 안내](HOME_SERVER.md)의 systemd 등록 절차를 따른다. 기존 runtime을 `--prepare-only`로 초기화하지 않는다. 이전은 진행 중인 kit 메모리의 checkout 세션을 옮기지 못하므로 새 거래의 재시도·정산 결과는 원본 로그로 확인한다.

복원 후 지갑 공개키 지문, DB 무결성, 정책·미확정 매입 기록을 비교한다. 새 셀러의 공개 카드와 시장 등록 주소, 재고 갱신, 바이어 DB 상태를 점검하고 구 서버가 중단된 상태인지 다시 확인한다. 개인 대시보드의 SSH 대상과 집계 경로도 새 서버로 바꾼다.

## 근거

- [Microsoft: WSL 파일 저장 위치](https://learn.microsoft.com/en-us/windows/wsl/filesystems)
- [Microsoft: systemd와 WSL 인스턴스 수명](https://devblogs.microsoft.com/commandline/systemd-support-is-now-available-in-wsl/)
- [Microsoft: 예약 작업 S4U 실행 방식](https://learn.microsoft.com/en-us/windows/win32/taskschd/principal-logontype)
- [Tailscale: Windows와 WSL 동시 설치 고려 사항](https://tailscale.com/docs/install/windows/wsl2)

교내 장비·망에서 외부 공개 서비스의 운영 가능 여부는 학교 지침과 해당 망의 운영 기준에 따라 확인한다. 이 문서는 기관의 운영 허가를 대신하지 않는다.
