# Refund completion v3: independent synthetic validation

**19/19 test methods passed, zero failures and zero verifier errors** on both the historical staging dependencies and current tracked submission dependencies. Production ready: **false**. The successful official function calls do not establish an integrated operating refund flow.

The four unchanged genuine generated files are in `generated/refund_complete_legacy/`. Original forge hashes are verified. Logic SHA-256: `6d2c0f9a8237216ff2fa43b7f4bf45739a1779f13eee505115578e1715b0f0e6`. Derived provenance records one exact private official model response `forge_tool.args.logic` hash match. Raw model inference, ReAct and private console logs remain private; provider metadata is not independent upstream model attestation.

The independent external host/test verifier checks actual legacy sale/refund/lot/allocation/ticket/promotion/stock contracts, all five reached rollback write phases, two-thread once-only completion, idempotence, wrong case/snapshot/transaction identity and caller fields, derived debt offsets, and unrelated customer rights. Trusted host confirmation rows were injected synthetically. Integrated prior model approval, wallet send, successful canonical outgoing receipt verification, and the permission-controlled host confirmation publisher remain incomplete. No production state or funds were changed.

The initial verifier run passed 18/19 methods: its sole failure incorrectly required an already successful official completion to leave the DB unchanged. The before-correction verifier and original failure log are preserved. Only that verifier assertion was corrected to check expected refunded statuses, one completion row and idempotent repeat. The generated candidate bytes were unchanged.

The generated selftest passed using the unmodified official Toolbox standard `test` mode. Its normal kit-provided testing state was not spoofed or manually set. All operational-call fixtures use fakeKit without a manually added testing flag and without signer/payment capabilities. Actual states not yet dispatched (`requested`), absent confirmation, rebound wrong payee, original incoming hash reused as outgoing, and a confirmation WAL sidecar all fail closed. Caller success/receipt/amount/payee/approved/verified flags are invalid arguments. These gates do not replace a real prior-approval/receipt publisher.

Run `python qa/reproduce.py` with this full repository and its installed requirements. This explicitly labeled external host/test adapter uses existing tracked sources under `submissions/26510122/round-4/codex-r4/`, shared `r4-operator/evidence/20261125-self-forge/qa/legacy_refund_fixture.py`, and tracked `r4-operator/kit/`. It writes only disposable synthetic ledgers and a new temporary result directory. The package alone needs those tracked dependencies; source hashes and paths are in `qa/dependency-sha256.json`.

Historical staging dispatcher/procurement source bytes differ from current tracked source bytes. All 25 literal-source-derived tables, CHECK DDL, columns, foreign keys and indices are identical, proven in `results/schema-staged-vs-tracked.json`; no production rows were read. Staged and tracked results are preserved separately. The tested private adapter is retained separately from the portable public adapter so their distinct source hashes are explicit.

All candidate public files were scanned before copying and rehashed afterward against four credential files (production wallet keys, worker token, owner code) and JWT/API/private-key/rights patterns without printing credentials. Only synthetic fixture assertions appear in failure logs. This package adds no commit, push or deployment.

Exact historical staging dependency hashes:

- `legacy_refund_fixture.py`: `3f765fc9201b325accbc1a7ed92d9b2fc71cfb6df4183c0f2238a015ba7be386`
- `fixture.py`: `3583926d5154ede9bbc6330103930967b452c04546a19a6078864abfe931b012`
- `dispatcher.py`: `8fe390ab5b8f68cbde3a06b942843aeaa2cdd592338932baa765460dda7e990b`
- `price_policy.py`: `6e101702c38d47b3f2c68c860dc0198fd1d7557e311c2753dc4a71fed127118f`
- `procurement.py`: `43e928c2f72cb8ec0f9c77d570f29936c5d9e0171324918b459819dd4b9f1db0`

Exact current tracked dependency hashes:

- `dispatcher.py`: `84e0eca3a0211e80772ed78f2ba3c166902ba0125577e7153b06cc5bb13de0cd`
- `price_policy.py`: `6e101702c38d47b3f2c68c860dc0198fd1d7557e311c2753dc4a71fed127118f`
- `procurement.py`: `675bdaa2942f7bdf3d119d10c6e1176f790ae0bacbb22a32cf77ae82de0628c6`
- `fixture.py`: `3583926d5154ede9bbc6330103930967b452c04546a19a6078864abfe931b012`
