# Independent customer-offers QA

Externally authored QA infrastructure, separate from genuine agent-created market source in ../sources. Source v1 is unchanged. Original official selftest passes; independent ordinary official Toolbox.call tests57/57 pass. One protocol goal FAILS and is preserved: long filters can be removed from next_args; following its description as-is broadens SKU selection. Conditional carry_filters merging is a TEST CONTROL, not a source repair or hidden pass. See filter-loss-reproduction.json for exact synthetic args and logic.py lines215–218.

Actual tests use temporary Fake-only local cache files with empty tokens/addresses/Signer keys. No real market/model calls, DB/card changes or credential use in QA. Static publication hygiene separately compares four designated credentials in memory only; no secret values or hashes are exported. This does not authenticate the cache's market truth, price authority, signing, grading, checkout or financial results.

Reproduce on Linux/WSL using the existing operator virtualenv:

    <operator>/.venv/bin/python run_portable.py --operator <operator> --sources ../sources --output /tmp/customer-offers-qa-NEW

--output must not already exist. The adapter uses existing op/kit only and copies the pinned source into a fresh temporary root; it never invokes tools on the real production cache. It executes ordinary Toolbox.call without manually setting kit.testing. --sources contains tools/read_customer_offers/{logic.py,test.py,permission.yml,forge.json}. Source and manifest hashes are checked. The observed pagination protocol failure remains a failure in output.

The original harness before correction is retained for provenance: an OS UNIX socket pathname-length error was fixed using a relative temporary-root bind. That QA infrastructure error is not a generated-tool failure. Malicious names/categories remain JSON data; downstream models must not follow instructions inside them. reserved/sold_out units remain visible; consumers must check state. Unknown expiry is explicit null and excluded when a minimum lifetime filter is requested.
