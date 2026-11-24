# 생활 상점 이름 적용 — 2026-11-25

대상은 기존 R3가 가동 중인 로컬 Ubuntu WSL의 R4다. A 서버를 사용하지 않았다.

- 원격 7ba4d7d를 서버 커밋 219b950/fb49294와 병합했다(병합 2473691). 이후 사용자 요청으로 표시명을 생활 상점으로 맞췄다.
- R4 에이전트가 공식 forge_tool로 rename_shop_card v1을 생성·테스트하고 실행했다. forge 시각 1795544485, 실행 시각 1795544493. 운영자는 영업 도구나 card.json을 직접 작성하지 않았다.
- 공개 Agent Card name은 생활 상점이며 기존 URL을 유지한다: https://stylish-barriers-violin-indicates.trycloudflare.com/.well-known/agent-card.json
- 같은 기존 party를 owner 인증으로 갱신해 캐시만 새로고침했다. /api/board의 card.name도 생활 상점으로 확인됐다. /api/agents와 /api/shops의 등록 식별자 name은 outseop-r4다. 시장 목록의 등록명 전체가 바뀐 것은 아니다.
- 현재 공식 시장 서버는 기존 등록 이름을 수정하는 경로가 없으며, 새 이름 가입은 새 party를 만들 수 있다. 새 가게를 만들지 않는 인계 문서의 보존 조건에 따라 등록 ID는 그대로 유지했다. 미래 시장 운영자 측 이름 이전이 지원되기 전에는 이를 단순 CLI rename으로 처리하지 않는다.
- 실제 서비스는 ourolabs-market-r4.service, 같은 디렉터리, 앱 포트18804, A2A포트18805, 같은 공개 URL을 유지한다. --name outseop-r4를 명시해 새로운 실행기 기본값으로 새 가게가 생성되는 것을 막았다. 신규 설치 기본값은 생활 상점이다. 현재 배포 재설치에는 deploy/ourolabs-market-r4-existing-identity.service를 사용해야 한다.
- 서비스 재시작 없이 카드가 반영됐다. MainPID1069998, NRestarts0, active/running. R3 buyer/seller 서비스도 active다.
- shop/buyer 지갑 파일은 기존 inode와 SHA256이 같고, 공개 shop 주소도 0x5FDC134D790EFB72DF1bbb922F2b49fcADe349C6로 같다.
- 기존 파일은 삭제하지 않았다. 기존 로그는 모든 원본 바이트를 접두부로 유지하며 새 이벤트만 이어졌다. 원래 6개 도구는 보존되고 이름 수정 도구가 추가됐다. tools/index.json의 변화는 에이전트의 도구 추가에 따른 것이다.
- 기존 원장의 join1/grant1/supply1과 동일한 재고1개를 확인했다. 실제 판매·정산은 아직0건이며, 미생성 주문·대기표·마일리지 장부를 존재한다고 보고하지 않는다.
- agent.json의 goal과 llm은 변경 전과 같다. 대기할인1%, 정상 구매 후 다음 거래용 마일리지1%, 기존 환불 정책을 그대로 유지한다. 실제 대기표 처리/적립/환불 이행 완료는 미검증이다.
- 공식 키트7개 원본 해시와 자체 생성 도구 해시 점검이 통과했다.

접근 제한된 변경 전 전체 백업, 파일 해시·inode 목록과 점검 결과는 r4-operator/runtime/name-update-*에 보관한다. 지갑·인증값·백업은 Git에 올리지 않는다. 원본 runtime과 logs는 삭제하거나 다듬지 않는다.
