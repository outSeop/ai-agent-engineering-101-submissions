# Native public customer context · controlled enablement

This is host infrastructure. The builder is genuine official Mind / Codex CLI
v5. No business logic, identity, key, ledger, or official kit is changed.

Artifacts:
- `deploy/native_customer_context_runtime_v1` mirrors the audited 16-file
  private freeze. The launcher embeds its exact manifest SHA.
- Review the staged `managed_runtime_customer_context_candidate.py` and
  `managed_launcher_native_customer_context_candidate.py`, then install them
  at the current names only as part of the authorized controlled cutover.
- The default invocation remains legacy. Enable the add-on with unit environment
  `R4_ENABLE_NATIVE_CUSTOMER_CONTEXT=1` (or launcher flag
  `--enable-native-customer-context`).

Preparation while the current main is healthy:
```sh
.venv/bin/python deploy/native_customer_context_runtime_v1/native_context_snapshot_entry.py \
  --operator "$operator" \
  --manifest-sha256 f8339743e858a52a0b0e0888d0fe598ee1e4052b4cdf09e7bc3c78e712eac596 \
  --publish-cache
```

Use an independent, nonoverlapping one-shot every 60s with a bounded service
timeout. This producer only observes the registered inventory and public
catalog, uses the existing pinned read-only stock offer calculation, and
atomically writes `runtime/native-customer-context/latest.json`. It keeps
the original observation time and 150s lifetime. The keeper card cache cannot
substitute for it because that cache lacks unit references and has a different
SKU representation. If source or cache is unavailable, requests continue via
the original checked legacy context. Scope the producer to the expected main
service and run it as the existing operator, without a wallet key.

Before main change: save protected original launcher/runtime source bytes and
hashes. Drain checkout, settlement, procurement and refund activity, confirm
no unresolved or outstanding signed checkout that depends on the old URL, and
record wallet file hashes plus the retained DB/WAL baseline and logical state.
The current main owns its quick tunnel and has no supported reload. The
dependent worker follows its restart. A new quick URL is expected. If URL
stability is mandatory, defer until a separately provisioned persistent proxy
can be supplied with `--public-url`; it cannot preserve this existing quick URL.

After explicit main restart: verify same registered shop and wallet, worker
token handoff, local and current public card, card keeper plus cache producer,
ledger identity/integrity and preserved source hashes. Assert an added native
context on a non-buying synthetic query before making a live adoption claim.
Use the aggregate status/count/latency file only for observation. Restore the
old launcher/runtime and disable the opt-in if the boundary fails; don't
restore ledger or wallet snapshot files over live state.

This runbook was prepared without installing or restarting a service. The
read-only timing probe measured one sample and did not invoke the customer
dispatcher or model. It is not a production response latency measurement.

