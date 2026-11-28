# semantic19 한 시간 read-only 관찰

[보고서](../../R4_REFERENCE19_ONE_HOUR_20261128.md)를 먼저 본다. 비교 두 구간은 각3600초다. 직전 구간의 점검3건을 제외했고 새 점검 SendMessage는0이다. 운영/금융/매입 코드를 바꾸지 않았다.

최종 문의 집계는 append-only trace 전체 창을 다시 읽어 만든 COMPARISON-SAFE다. 자원 표본은72개다. 초기 관측기 수정을 본체 서비스 재시작으로 세지 않는다. 관측기 첫 중지는 불필요한 source escape 의심이었고, 집계 보완은 전체 catalogue144개와 visible 매칭0개를 구분한 것이다. 원 소스·관측·실패는 private에 보존했다.

시장 expire 이벤트는 실제 매입 unit ID, 공개 이벤트 hash, 원가16837을 대조했다. 고객 원문·개인 이름·지갑 키·토큰·권리코드·개인 절대경로·모델 사유 원문은 내보내지 않았다. MANIFEST는 이 공개 파일들의 SHA256이다.
