# 포럼 수요 매칭·첫 구매 혜택 수정 — 2026-11-27 22:09:32 KST

**적용된 부분은 게시 도구9의 혜택 안내다. 새 구매자 수집·매칭 전체 경로는 아직 운영에 연결하지 않았다.** 원래 셀러의 모델·게시 주기·서버·DB·지갑·매입은 유지했다.

## 적용 완료와 실제 게시

2026-11-27 22:03:31 KST에 genuine forum_marketing9 원본4파일을 원자 교체했다. 앞서8은광고간격을600초에서3600초로늘리는회귀가있어실게시2번이막혔고,21:54:57에정확한원본5로복구했다. 복구후21:56 글20486이정상게시됐다. 원9는해당조건한곳만원래rates[0]으로수정했고회귀검증12번째를추가했다. 원본5는 tools/.deprecated에 보관했고 공유 codex-r4/forum.py는 c15424... 그대로다. 재시작·등록·지갑 재생성·수동 광고·송금은 없었다.

기존 셀러가 직접 게시한 글 **20572**에서 추가5%·최대5000·지갑당1회·7일·다음거래·정책종료시각을 확인했다. 공개 본문과 원장 일치: True. 좋아요 0.

추가 적립은 실제 가게 identity, 보호된 정책 파일, 실제 bonus-core와 동일한 원장 형태/누적사용액을 확인한 경우에만 표시한다. 첫 정상 정산·인도 송금 지갑당1회, 해당 등급 판매 기준가의5%, 최대5000크레딧, 기존 전체예산50000, 종료2026-11-28 20:32:49 KST, 정산일부터7일·다음거래 사용·환불 회수 조건이다. 정가와 협상 판매가를 혼동하지 않는다. 정책 만료·소진·검증 불가에서는 추가5%를 광고하지 않는다. 기존 일반1%·실제지연1%대기할인·환불 정책·원가 하한은 그대로다. 광고 표시를 새 적립 발생이나 새 정산으로 세지 않는다.

## 새 매칭 구현·검증 완료, 운영 연결 대기

새 producer9은 buyer 글을 별도로 읽고 ID/시간 하한을 찾은 뒤 최대30페이지/3000행/제한시간 안에서6시간 범위를 확장한다. 수집 범위가 불완전하면 이를 구분하고, 검증한 최신 개별 요청은 버리지 않는다. 실제SKU/짧은 상품명·보수적 동의어를 재고와 대조하며 명시SKU·포장량·등급·예산·기한·증빙·부정/과거/환불 표현을 다시 검사한다. 일부 원 단위 예산 표현(예:4500원 이내)은 불명확하다고 보류할 수 있다. 모든 자연어/동의어 지원을 완료했다는 의미가 아니다.

조회된 요청과 현재 상품을 모델이 고른 뒤, publisher9이 선택한 thread와 현재 재고·가격·등급·조건을 게시 직전에 재확인한다. 같은 요청의 중복 답글, 응답 불명 게시의 재전송은 막는다. 서로 다른 고객 thread에 같은 실제 재고를 견적 후보로 내는 것과 같은 독립 광고를 반복하는 것은 구분하되, 기존330초 전체간격·일96회한도·원자적 게시 잠금은 유지한다.

기존 formatter2가 'A등급 10,000크레딧 이하'처럼 조건이 섞인 요청을 다시 해석해 검증된 후보를 버렸다. 새 genuine formatter3은 producer8/9가 검증한 eligible를 재해석하지 않고, 기존16품목/5500자/명시포장/등급다양성/C연속광고 방지 레이아웃을 유지한다. 실제 사업조건과 최종 권한은 producer/publisher9이 소유한다. HOST는 원 SDK·데이터 경계·핀·기동 연결만 담당한다.

|검증|결과|실제 운영 영향|
|---|---|---|
|genuine publisher9 원 SDK 자체시험·독립 원 ForumFixture|12/12|격리 fakePOST만, 실제 송금0|
|genuine formatter3 원 SDK 자체시험|통과|네트워크·쓰기·지갑 권한0|
|원문 그대로 source8·9→formatter3|reply1→1|A등급+10000이하 문장 보존, 실제POST0|
|실제 수업 market Model/원 Mind.run_once|1회19.811초, reply 선택|합성재고·dry선택, 실제POST/pay0|
|모의 cold-start 설치|9/9|원main·stock·loop 재사용, 서비스 미변경|

실제수업모델시험은producer8→formatter3의동일혼합문장검증이며,9는광고간격조건한곳만달라추가실제모델호출없이새9→3 SDK결합을다시확인했다. 실제 모델1회 이후 종료는 명시한 synthetic scheduler sleep1회다. 두 인터페이스 호출을 모델2회로 세지 않는다. 합성 재고/요청이므로 실제 시장에서 특정 SKU를 보유하거나 고객에게 견적을 전달했다는 증거가 아니다. 실제 고객 문의·구매 증가의 인과효과는 아직 확인할 수 없다.

## 운영에 연결하려면

현재 main은 시작할 때 후보 모듈과 핀을 메모리에 고정한다. publisher 파일 교체로 새 source/formatter가 실행 중인 모델에 연결되지는 않는다. source9의슬레이트·formatter3를 원coordinator에 묶는 cold-start wrapper와 정확한 source binding/기존 service ExecStart 템플릿을 준비했다.

기존 ourolabs-market-r4.service 본체를 재시작해야 한다. 기존 상태를 보존한 hot reload/export 경로가 없으며, 현재의 quick tunnel 주소는 바뀔 수 있고 원main의 메모리 대화 연속성은 보장할 수 없다. 기존 front 프로세스가 살아 있어도 원main 대화를 보존한다고 보장하지 않는다. **DB·두지갑·재고·주문·대기표·마일리지 장부는 보존한다. 주소와 이전 대화 연결에 영향을 줄 수 있는 전환은 사용자 명시 승인 후에만 진행한다.** 새cold3는 실제행동 없이 --verify-wrapper-only를 통과했다. 현재service 환경/PATH를 그대로 상속하며 기존 mainPATH에서CF바이너리를 찾는 것도 확인했다. 실제재시작/새등록은 아직0이다.

승인 후 원서비스·원주문·unknown 게시·active 결제/고객 작업을 다시 점검하고, 기존 unit의ExecStart만 검토템플릿으로 바꾼다. PID/주소/카드/토큰/재고캐시·기존 front fallback과 새 source→모델→견적을 재검증한다. 대화 메모리/옛주소 복원을 자동 보장하지 않는다. 실패 시 새금융상태를 지우거나 unknown을 풀지 않고 원 source/기동설정으로 복구한다. 별도6시간 소액매입 정책과 요청observer는 이 광고 수정의 승인 범위에 포함하지 않으며 여전히 미적용이다.

## 보존과 한계

확인시각 2026-11-27T22:09:32+09:00: 서비스5개 PID/재시작수 동일=True, 두지갑 동일=True, 원 DB inode/device 동일=True, 공유금융코드/가격/보너스정책/기존매입8 보존. 금융8테이블의 변경 없음=True; 상태 {'missing': 1, 'settled': 2}, DB quick_check=ok. 원미입금 만료 주문1건 missing은 이전 운영에서 expired로 바뀐 그대로다. 공개 카드HTTP200, outseop-r4, 주소 https://stable-leu-below-the.trycloudflare.com. r4/r4-2/r4-3 예약홍보는 PAUSED 유지, 새서비스·타이머·예약0.

추가로 운영토큰을 사용해 실제root에 직접slate_context를 실행하려던 진단은 DB초기화/쓰기 가능성 때문에 자동승인검토에서 실행 전에 거절됐다. 실행/우회하지 않았고, 격리 FullFixture·실제class dry선택·자연발생한 셀러게시를 읽는 방식으로 대체했다. 이것은 이미 승인·완료한 publisher9 파일교체와 별개다.

## 보관된 구현·적용 자료

- deploy/forum_demand_native_v9 manifest5390d6ebaf8099bcdc2c23ebac8408e7e204dd294d27f935f1670b21cbc74385 — 현재publisher
- deploy/forum_demand_formatter_v3 manifestb1fcbc8acea1fb563e77dbab0b45613429b2d79ba0c2bb1f4c507659811a5702 — 새로운표시도구, oldcachedselector미교체
- deploy/forum_request_scope_runtime_v2 manifestdde805dbc592e7323a22e5790c1553282bdacc3741c6202c891431cf0095eb21
- deploy/forum_request_cold_start_v3 manifestd5baa3ca7ee620e8a2ffb48bdc11a2d420e1add6eb850033d46cfda7d347d366
- cold3 bindingSHAe1bdad4a5e06c197cadce5e272d394beb811813f7f287f8293d0d8cc69903afb. 현재cold3wrapper는핀검증된 runtime/marketing-request-20261127-method/scope2-formatter3를읽는다. 코드복제본은deploy/forum_request_scope_runtime_v2에공개돼있고현재runtime경로원본은삭제하지않는다. 다른머신재현시동일manifest파일을그기대경로에준비한다.
- evidence/20261127-forum-demand/native9-independent, rollout, 혼합coupling/ACTUAL-CLASS-SAFE자료(scope2). 실패한제안6/7과독립검사오류도별도commit으로보존했다. 개인키/원고객대화/비공개모델사유는Git에없다.
