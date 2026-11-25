# Refund completion v1: failed independent validation

Production ready: **false**. This package preserves one model-generated candidate and independent external verifier evidence. It does not contain production ledger rows, keys, raw model inference, ReAct traces, or private console logs.

The unchanged candidate logic SHA-256 is `6b11e5e3cf16bdbf1e3a178669861017368d8169513de57098904dd35b3c3233`. All four files in `generated/refund_complete_legacy/` are byte-identical to the versioned immutable QA snapshot and match its original forge manifest. Derived origin records match the private official model response's `forge_tool.args.logic` hash. They identify the recorded provider, not an independent upstream model attestation.

The final independent run used 19 test methods: **14 passed, 5 failed**, with no final verifier errors. The five failures concern official confirmation transport, held allocations, debt offsets, held tickets, and promotion lifecycle. The generated selftest also passed through the official Toolbox. That result does not establish compatibility with the actual legacy schema.

The first v1 verifier attempt had one synthetic stock fixture setup error (missing retry_at), preserved in attempt-1 artifacts. Only test fixture setup was corrected. Original attempt logs and final logs are preserved separately. Their assertion values come only from disposable synthetic fixtures, not market forecasts or production records.

The host and QA code are external verification scaffolding authored by Codex. Synthetic host confirmation rows were injected by that scaffold. A trusted prior-approval and exact successful canonical outgoing-receipt publication path remains incomplete. No `kit.testing` bypass was used to claim an operational completion path. The generated selftest uses the official runner's test mode only as its ordinary selftest interface.

The complete independent QA source is in `qa/`; it retains its original historical staging layout and imports the historical fixture dependencies listed by hash in `qa/dependency-sha256.json`. Those dependency sources are not included in this package, so the package alone is not a standalone full-suite reproduction bundle. The original candidate selftest requires the official `kit/agent_kit.py` and `kit/forge_runner.py`; use a disposable root, synthetic identity, no signer capability, and no network permissions. Do not point this verifier at an operating agent directory.

Detailed observed failures and limits are in results/feedback.json.

A pre-copy exact-value scan compared all candidate public bytes against four sealed credential files (two production wallet keys, worker token, owner code) and checked JWT/API/private-key/rights patterns without printing values. Copied bytes were rehashed and scanned again. No commit, push, deployment, real transfer, or production database change is part of this package.

## Reproducing with tracked submission sources

Run `python qa/reproduce.py` from this package using an environment containing the submission requirements. This explicit external host/test adapter resolves the four existing tracked sources under `submissions/26510122/round-4/codex-r4/`, the existing shared fixture helper, and the tracked `r4-operator/kit/`. It writes only to a fresh temporary output directory and disposable synthetic ledgers. Exit code 1 is expected because this candidate fails the contract tests.

The original independent QA source remains unchanged. Adapter provenance records its exact source hash and the adapter hash. The adapter changes import/snapshot/output locations only; it adds no refund business answers, schema migration, approval, receipt verification, or testing bypass.

The historical staging baseline and current tracked baseline have different dispatcher/procurement source bytes. `results/schema-staged-vs-tracked.json` proves exact equality of all 25 literal-source-derived tables, columns, CHECK DDL, foreign keys, and indices, with no production rows read. Exact historical and tracked dependency hashes and paths are in `qa/dependency-sha256.json`. Current tracked reproduction results are separate from preserved historical results.

Historical QA baseline source SHA-256:

- `legacy_refund_fixture.py`: `3f765fc9201b325accbc1a7ed92d9b2fc71cfb6df4183c0f2238a015ba7be386`
- `fixture.py`: `3583926d5154ede9bbc6330103930967b452c04546a19a6078864abfe931b012`
- `dispatcher.py`: `8fe390ab5b8f68cbde3a06b942843aeaa2cdd592338932baa765460dda7e990b`
- `price_policy.py`: `6e101702c38d47b3f2c68c860dc0198fd1d7557e311c2753dc4a71fed127118f`
- `procurement.py`: `43e928c2f72cb8ec0f9c77d570f29936c5d9e0171324918b459819dd4b9f1db0`

Tracked reproduction source SHA-256:

- `dispatcher.py`: `84e0eca3a0211e80772ed78f2ba3c166902ba0125577e7153b06cc5bb13de0cd`
- `price_policy.py`: `6e101702c38d47b3f2c68c860dc0198fd1d7557e311c2753dc4a71fed127118f`
- `procurement.py`: `675bdaa2942f7bdf3d119d10c6e1176f790ae0bacbb22a32cf77ae82de0628c6`
- `fixture.py`: `3583926d5154ede9bbc6330103930967b452c04546a19a6078864abfe931b012`

The adapter was independently executed against the tracked dependencies: v1 again produced 14 passing methods and 5 failing methods, with zero verifier errors. Its original output, schema export, and log are preserved separately under `results/tracked-reproduction/`.
