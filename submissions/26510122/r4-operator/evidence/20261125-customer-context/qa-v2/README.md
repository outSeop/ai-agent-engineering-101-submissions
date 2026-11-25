# Independent build_customer_context v2 QA

Externally authored QA infrastructure. Genuine source4files are separate under ../generated/build_customer_context@2 and unchanged. Original selftest passes; ordinary baseline56contracts+4priorprivacy goals pass;15details/codec contracts pass. Original70 controlled replay fails unsafe_public_text, and2benign synthetic date/specification strings fail. The public evidence preserves those3failures and does not claim v2 complete. V3 is a separate version.

NO actual captured product names, SKU list, unit_ref, prices or raw inventory rows are included. Historical70 artifacts contribute only labelled aggregate counts/hash/regex match-shape metadata. The anonymous default fixture uses fictional names/IDs/prices and two fictional date/spec strings to reproduce v2's whole-context hold, not actual capture. The separate control fixture has no such probes and demonstrates successful varied-shape compression. This is coarse anonymous shape, not byte-exact market data.

Reproduce on Linux/WSL:

    <operator>/.venv/bin/python run_portable.py --operator <operator> --sources ../generated/build_customer_context@2 --output /tmp/builder-v2-anon-NEW

--output must not exist. Original QA/tool bytes are copied into a temporary Fake-only root; the original expected capture path contains ONLY the anonymous synthetic stand-in. No actual expired capture, real customer, live DB/card/wallet or market/model is read/called by this public replay. No manual kit.testing. All source/manifest hashes are checked. It should REPORT56+4+15passes and3goal failures; those are not hidden or repaired.

Lookup decoder and compact Unicode budget are explicit v2 codec adaptations, not generated source changes. Details contract is separately documented; the actual v2 tool listing was truncated before all required details arguments, so model usability/Broker production prefetch are not proven. Privacy literals are FAKE sentinels and fictional numeric specifications, not actual keys or personal data. Source truth, price/customer authority and financial checkout remain unverified.

publication-proof.json records four designated credential-byte/prefix comparisons and JWT/API-pattern scans before/after copy. Values and secret hashes are not exported. Only this new QA folder is written; v1 evidence and generated sources remain unchanged.
