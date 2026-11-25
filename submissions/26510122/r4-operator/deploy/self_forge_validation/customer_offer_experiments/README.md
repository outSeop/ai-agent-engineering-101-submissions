# Customer offer experiments

The classroom model decides what to recommend and how to answer a synthetic
customer. The host adapters are external verification infrastructure. The
immutable, self-forged read_customer_offers v2 supplies observed public facts.
Legacy stock_offers supplies verified representative SKU/grade offers and
prices; it does not enumerate every physical unit. The tool has no wallet,
checkout, order, posting, or customer-contact capability.

- Baseline. Model requests each page. The recorded run read five pages and
  ended without a reply after a model timeout. The experiment cannot isolate
  the cause of that timeout.
- Automatic paging. Host follows exact native cursors, preserving filters and
  order. Its first compact layout could not fit the 67-row capacity sample.
- Indexed layout. Uses zero-based lookup lists for repeated fields. The
  67-row captured sample fit in 5,470 characters with the normal serializer.
- Factored layout. Also places constant columns outside rows. A fresh
  70-row prepare-only snapshot fit in 5,349 characters. One actual synthetic
  customer dialogue completed with one context call (seven native pages)
  and one details call. This is a paired engineering observation, not a
  customer-conversion or latency-rate estimate.

All compact variants reject overflow explicitly; there is no silent
truncation. Exact public details are preserved behind the short previews.

Run the offline tests from the operator directory:
```bash
PYTHONPATH=deploy/self_forge_validation:deploy/self_forge_validation/card_transition \
  .venv/bin/python -m unittest discover \
  -s deploy/self_forge_validation/customer_offer_experiments -p 'test_*.py'
```

Offline tests read the exact v2 source bundle in
`evidence/20261125-customer-offers/sources-v2/tools/read_customer_offers`,
with synthetic rows in the public reproduction. The actual samples and raw
model reasoning remain private. `source-metadata.json` identifies source
hashes and describes which host copies were adjusted for packaging.

Canary commands accept `--sources <tool directory>` for the pinned bundle.
The default still targets the existing isolated generation session. Preparing
a live-source representative snapshot needs read-only access to the running
registered shop. Add `--run-class` only for an explicitly reviewed synthetic
classroom dialogue. The tests do neither.

