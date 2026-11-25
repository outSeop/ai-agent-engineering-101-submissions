# Independent customer-offers v2 QA

Externally authored test infrastructure; genuine agent-created source is separately published under ../sources-v2/tools/read_customer_offers. Source logic SHA a122aed15c9462dfb6ed2c77665e6fbb82de7720633adb03ccf0ec7b1b4e45ff is unchanged. Original official selftest passes. Ordinary official Toolbox.call regression57/57 plus original v1 protocol failure1/1 and added continuation14/14 pass:72 checks. V1 evidence in ../qa remains untouched.

The one obsolete expectation that v1 carry_filters must occur is explicitly replaced with exact ordered100 selected refs through next_args alone, without repair; harness-adaptation.json records this. New long-filter+large-Unicode-fragment queries retrieve100 exact units through35 pages, and detect filter changes, file changes and expiry during continuation. All are synthetic Fake-only source files in temporary roots, with empty tokens/addresses/Signer keys. No actual production cache, DB, card, service, customer, model or market is tested or changed.

Reproduce on Linux/WSL with existing operator virtualenv:

    <operator>/.venv/bin/python run_portable.py --operator <operator> --sources ../sources-v2 --output /tmp/customer-offers-v2-qa-NEW

--output must not exist. The wrapper copies exact source and original test scripts to a temporary Fake-only root and uses existing op/kit. It invokes ordinary Toolbox.call, never manually sets kit.testing, copies no credentials, and never calls tools on the live cache. Manifest hashes are checked.

These72 checks concern file/argument/expiry/pagination reliability only. They do not authenticate market source truth, current authoritative price/grade, signing, checkout, settlement or finance, and do not prove production integration. They also do not measure the actual classroom model's multi-turn round-trip latency or whether a long conversation fits the150s cache TTL. A separately run synthetic classroom canary must be reported separately and must not be described as a real customer. Cursor filter_digest is a public consistency hash, not market authorization. Explicit time/filter changes require a fresh read rather than a silent continuation.

publication-proof.json records four designated credential-byte comparisons and JWT/API-pattern scans before/after copy. Secret values and hashes are never exported; static scan is separate from the credential-free QA runs.

Portable replay exposed and preserved a QA-only comparison of clocks from two independent queries. See harness-adaptation.json and portable-replay-before-harness-correction/. The corrected script compares one full query own clock; generated business source is unchanged.
