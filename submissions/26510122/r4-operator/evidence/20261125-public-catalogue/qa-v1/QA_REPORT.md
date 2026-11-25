# Independent public_catalogue v1 QA

Genuine source logic SHA256: 8862e9907f17ecd8fb019d1406a33b57268fd4566618e0757a4c8786160ff005.

- Standard SDK selftest: PASS. Original actual forge history has one failed proposal then one successful version-1 forge. The first failed proposal is not a forged or approved source.
- Independent ordinary SDK calls: 108 substantive checks PASS, 2 goal checks FAIL. Separate output-size invariants: 955/955 PASS. Calls:955, total153.717s, max0.262s.
- Extra lifetime/privacy checks:6 PASS. Total substantive114 PASS,2 FAIL.
- Capacity:117/200/500/1000/5000 synthetic rows, all pages consumed through original next_args, no omission or duplication. Each synthetic snapshot had TTL149 seconds and was traversed within its own validity window. The 153.717-second aggregate spans multiple independently created synthetic snapshots.
- Failures: a literal SKU at row117 or500 still yields the first8 unrelated rows in initial context. Search for that SKU succeeds, but incurs a further model query. Exclusion/alternative context intentionally remains neutral.
- Cursor checks preserve all filters; changed/omitted filters, source hash, timestamp or query ID are refused. Duplicate pair render is ambiguous, unavailable/expired/reserved members produce no partial reply. Original source is unchanged.
- Minimum remaining time boundaries0/59/60/61 and expiry between pages pass under natural time. No clock patch, source edit or manual testing flag.
- Fallback closed request cases:33 PASS. It provides a fixed factual partial list, not a purchase/financial decision. Existing Broker state-based gating still requires host integration verification.
- Sensitive query text is not echoed. A sensitive query producing no matches is accepted as ready/empty; rejection is not uniform. Unsafe query text is refused when it would be returned in next_args. This is distinct from blanket input rejection.
- All data synthetic. Model/market/production DB/wallet calls:0. No real HTTP Broker/class-model E2E, host IPC integration or live installation is established by this QA.

Private evidence: exact four source files; first-failed-proposal; actual response/permission/hash-derived origin; original forge records; standard selftest; ordinary-toolbox and independent-lifetime result JSON. Raw model thoughts/messages are not exported.
