# plan_public_sku_trials v2 independent QA

Reviewed unchanged logic SHA `77449caeecd41b4a26e249a17b38946f7f4e62f4bc451d2956ec60951bf3f393`.

- Original official Toolbox selftest: PASS. No key or token loaded.
- Independent planner QA: 34/37 PASS. Complete upstream category paths and category-total consistency now pass. Input bool, duplicate SKU, times, exact category selection, deterministic ties, and untrusted auxiliary text handling pass.
- Three remaining general-input goals fail: wallet-shaped arbitrary SKU can be emitted; per-SKU count2001 is accepted; known+sealed+unknown total2001 is accepted despite reviewed upstream maximum2000 rows. These are not removed by the v2 source.
- A well-formed historical public summary remains accepted with provisional=false; that flag represents source coverage rather than current age or provenance. Counterfeit but self-consistent inputs are not authenticated by a pure function.
- One test harness expected no candidates after duplicating only the baseline held-SKU exclusion. That expectation was wrong: it must equal the baseline candidate list. Original failure artifact and correction note are retained; tool source was not changed.

## Cached upstream compatibility

Used only the previously reviewed public aggregate bytes, hash `ee7dc92dd2e2521802fdd606833c893ca2e2ba814111f7bce026f6b3cfc5867b`, from summarize_public_settlements v2. Window 1795560995–1795564595, 71 observations and19 public SKUs. With TEST ASSUMPTION existing_skus=[], planner returns10 distinct complete category paths, one unit each. This is schema compatibility, not an assertion that these are new to our shop. No held-SKU server, customer, wallet, cash or ledger was queried. All10 categories are food subclasses; this is not evidence for broad household assortment.

## Closed host preview audit

Read-only audit of existing host SHA `86aff2808f0ba8d5035bdad90cbc9434f3be71fc45a5fac2fd636c2d2aa4484f` and guard module SHA `a79df1dc04401d50b27a1fb14ea2e98aa6c140fccb161c152b30f475ae25e054`.

Independent SYNTHETIC host tests:34/34 PASS. Source-pinned fresh public result becomes a one-use opaque reference, valid150s; caller cannot submit summary, SKU, count, held-SKU list, cash, path or URL. Actual pure planner receives the exact host-held summary and an empty exclusion list. Invalid ref, replay, monotonic expiry, stale/future first observation, bad limits, wallet/identity and mismatched output reject in tested cases. No new API/model calls were made by this audit.

The previously completed official class run has the action chain summarize_public_settlements → plan_public_sku_trials → sleep. Only action fields and public observations were extracted; private thought fields were not exported. The host summary matches logged preview. Requested window1795564151–1795567751, observed27SKU/13categories. Preview top3: egg Gab7c8b3d count10, prepared meal G5c96ee78 count7, yogurt G5e1cf31d count6, each planned_units1. This is a separate fresh run, not the earlier71-observation cache. inventory_exclusions_applied=false is explicit.

The closed preview chain blocks the identified general-input defects by restricting provenance and arguments. It does not repair the tool, grant arbitrary Toolbox.call access, query private stock, buy goods, publish, or demonstrate sales effects. Exact immutable source permits relying on its sorting/category logic; the output projector alone does not independently recompute all sorting/category/counter totals. Source authentication ultimately trusts the pinned fixed official public reader and its API.

## Recommendation

Keep generic planner caller inputs denied. The independently tested bounded public-preview host is suitable only for that limited observation-to-plan chain. Keep time windows and missing actual stock exclusions visible to the decision model/user. A public-window plan is neither demand prediction nor purchase authorization. Current supply cost, expiry/storage, fees/gas, refund/benefits, current stock and cash must be checked before purchasing. The attached guard proposal is an audit specification; this reviewer changed no host or business source.

All reviewed generated sources and v1 failures are retained. Byte hashes demonstrate exact reviewed contents, not an independent assertion about model authorship; historical forge and actual use provenance must remain separately documented.
