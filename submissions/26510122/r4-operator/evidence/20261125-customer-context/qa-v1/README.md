# Independent build_customer_context v1 QA

External QA infrastructure, not genuine-agent business tool code. Original source is separately stored by the operator under ../generated/build_customer_context@1. Existing ordinary-call contract56/56 pass; controlled actual-shape70 capacity1 and no-secret-output4 goals FAIL. Failures and original source hashes are preserved. No source edits or hidden repairs are included.

Public files contain NO actual product names, SKU list, unit_ref values or original capture rows. controlled-capture-capacity.json and capacity-diagnosis.json are permitted aggregate metadata only: the old captured70-row public input was expired and used locally for controlled capacity analysis, never fresh market/model evidence. It exceeded the6000-character budget even at minimum preview. Privacy probes are explicitly FAKE sentinels: generated repeated hex, sk_fixture strings and phone-format examples, not real credentials or people. Base checks reject them but cache product name/path exposed them in v1.

The anonymous fixture replaces every name/SKU/unit_ref/price with synthetic data. It preserves only coarse row/name-length/path/cardinality/price-width shape. It is not byte-exact real inventory and is not a market observation. Its expired synthetic timeline is shifted only inside temporary local tests. The wrapper maps it to the original harness expected capture path, without reading actual capture or editing source.

Reproduce using Linux/WSL operator virtualenv:

    <operator>/.venv/bin/python run_portable.py --operator <operator> --sources ../generated/build_customer_context@1 --output /tmp/build-context-v1-anon-NEW

--output must not exist. The original QA script and original tool are copied to a temporary Fake-only root; existing official kit is used. All inputs, including capacity stand-in, are anonymous/synthetic. Reproduction is expected to REPORT56 pass and5 goal failures, not relabel them as success. No manual kit.testing, actual market/model calls, customer data, DB/card/wallet changes occur. Actual source authenticity, Broker/model integration and exact-unit financial checkout remain unverified.

publication-proof.json records designated four-credential/prefix and JWT/API-pattern scan before/after copy. Secret values and hashes are never exported. Static scans are separate from credential-free QA.
