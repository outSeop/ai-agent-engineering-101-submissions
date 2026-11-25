# Public-product renderer v2 independent QA

Original4files: ../generated/render_public_product_reply@2. Exact logic d6c78d2b... has only one textual change fromv1: unknown expiry no longer asserts nonfood. Tests update the line and add food/null regression; permission version/replaces only. Actual Model response/source and permission-args hashes plus original v2forge record are preserved separately. V1 first failed proposal and45pass/semantic1fail are untouched.

Original SDK selftest passes; same ordinary Toolbox.call45contracts+nullfood1 all46pass. QA source changes only expected source SHA. No generated source edit, no real data/model/market/DB/wallet calls. This is tool-only validation, not a new v2 actual Broker/classModel/finalHTTP or production test. Root's prior v1 known-expiry canary must stay separately scoped. Original respond guard remains protected; the exact trusted toolreply route needs its own final delivery test.

Reproduce: <operator>/.venv/bin/python run_portable.py --operator <operator> --sources ../generated/render_public_product_reply@2 --output /tmp/public-reply-v2-NEW. Output must be new. Original tool/harness run in a temporary root with only synthetic readonly snapshots and empty capabilities, no manual testing flag. publication-proof-v2.json records exact fourcredential and JWT/API/PEM scans, zero exceptions.
