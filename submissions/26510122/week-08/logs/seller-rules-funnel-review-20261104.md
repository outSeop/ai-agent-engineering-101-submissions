# Seller rules and deal funnel review — 2026-11-04

The seller has two repaired gaps: receipt grade claims were omitted, and single-unit experiments could not obtain the second observation required for maintenance. Rules were fetched read-only from https://market.ourolabs.ai/agent.md (snapshot: market-rules-review-2026-11-04.md). No competitor private logs or instructor database was accessed.

## Implemented

- Fixed goods declare their actual grade. Food grade is recomputed from expiry/catalog shelf life and declared only if it remains stable throughout the 600-second receipt hold plus 30 seconds. Missing shelf data or an imminent boundary omits the claim. Original signed fields remain shop/item/price/task. The Honest counter is optional grade-claim accuracy, not signature verification; existing claims are not backfilled.
- Opening quotes disclose actual SKU, grade at quote, remaining food life, and the included certificate, before price negotiation.
- A sold-out SKU with exactly one known-cost positive-spread settlement can be offered for one second-trial unit during growth. At most two such candidates are offered per window. A durable intent marker prevents another trial even after an unknown or unsuccessful result. A second positive sale qualifies for existing forecast-based maintenance; this does not lower the two-sale threshold.
- Trials use the replenishment path and shared cash/risk/window budget, not the exhausted rolling novel-exploration budget. Proven candidates keep priority. The model approves the basket, with hard validation of quantities, combined spend, category capacity, pending orders and window freshness.

## Observed funnel

Snapshot at **2026-11-04 15:06:55 KST**, previous three hours. These are observations before deployment, not an effect estimate.

| Rolling event | Count |
| --- | ---: |
| Requests | 353 |
| No stock | 45 |
| Purchase conditions unmet | 3 |
| Opening quotes | 292 |
| Signed receipts | 199 |
| Settlements | 131 |

A matched request cohort with at least ten minutes elapsed contains 331 tasks: 274 received an opening quote, 206 made an offer, 189 received a receipt, and 125 have a local settled-task link. Some events fall outside these stages, including stale inventory, cancellations and unfinished work; rolling counts should not be divided as if they were one cohort.

**Receipt-to-payment uncertainty:** an older receipt cohort has 190 receipts, but 57 reuse an identical unit/price combination. The old importer assigns a settlement to the latest receipt for that unit, so task attribution can be ambiguous. Of the 133 receipts with a unique unit/price combination, 111 have a matching settled unit/price (83.5%); 22 are not confirmed paid. This selected subset is not the overall conversion rate. Do not count every receipt pending as either a sale or a failure.

**Public cross-check:** 6,000 public ledger entries, approximately 14:45–15:06 KST, include 14 submitted results carrying our receipt. Nine settled; five did not. All 14 passed both signatures, item compatibility, order ownership and budget checks. Failed payment is the only false check in those five results. The public record does not identify the buyer's private rejection reason. Three failed receipts were C grade and two B; that small observational sample does not establish grade as the cause.

**Stock coverage:** only 9 of 45 no-stock events name a requested SKU: Pringles 6, kimchi 2, stool 1. The other 36 are broad category requests, especially grains 13 and dessert 7. One supply line does not cover all acceptable SKUs, and private acceptable lists are not visible unless communicated. Expanding bounded trial coverage is better supported here than assuming every lost sale requires a lower price.

**Concentration:** Pringles accounts for 62/131 settled units (47%). Three-hour revenue is 2,254,228; known acquisition spread is 497,406 **before holding costs/refunds**. SKU grade/cost draw varies, so these are not unit-level net profits.

## Rules checked and remaining issues

| Rule / issue | Assessment |
| --- | --- |
| Signed receipt and acceptable SKU | Already enforced; sampled failures all passed signatures and item compatibility. Keep canonical receipt item as shipped SKU. |
| Honest grade claims | Omitted optional field repaired; only future eligible claims will appear. |
| Food life and grade at checkout/settlement | Grade decays A >=80%, B >=45%, C below; certificate and requested lifetime must hold at payment. Claim boundary guard added; future payment timing is not guaranteed. |
| Goods holding cost | 1% of acquisition cost/day is reserved in working capital and modeled in price tools. Acquisition spread is not net profit. |
| Warranty | Optional, not currently sold. Full-price refund removes deal/revenue but leaves stars; no free warranty added. |
| Profit / ALL | Terminal cash minus capital/injections, unsold stock uncredited. ALL weights are percentiles, not a raw currency/stars sum. Existing deadline drawdown remains. |
| Supply windows | Approximately 20-minute jitter, open 3 minutes. Unknown purchase outcomes retain reservations; no automatic retry. |
| Forum | Shop votes do not directly enter shop ALL. Buyer forum/posts carry 40% total weight but publishing remains disabled under the current plain-buyer setup. Advertising is for discovery, not direct shop score. |
| Novel-exploration rolling cap | Internal policy, not a market rule. Near 6m gross worst-case commitments in 24h, even when items sell, keeps novel exploration almost frozen despite cash. Trials now have a separate replenishment route. Reworking that exploration cap remains a separate policy change. |
| Conditional buyer requirements | One rejected request says A/B acceptable, or C with warranty/refurbished pricing. Current regex conservatively parsed 6h warranty as mandatory for all grades. This is an observed parser limitation, not evidence warranty is required by the market. Two other unmet requests required 360h/541h food life. Preserve hard guarantees while designing alternatives handling separately. |
| Checkout leases in official kit | Open ACP checkout sessions reserve units; local negotiation/receipt leases and ACP leases are distinct. No checkout-refused/settle-refused lines were recorded in our seller kit logs during this audit. No kit lease defect is claimed from receipt nonpayment alone. |
| Settlement task linkage | Raw events retained. Same-unit reissued receipts require public result confirmation for definitive per-task attribution. Audit reports ambiguity explicitly instead of treating latest receipt as certain. |

## Internal model check

Three synthetic open-window runs copied live evidence/portfolio state into temporary directories. **No supply API calls or market writes were made.**

1. First run approved only proven replenishment and omitted trials without explaining them.
2. Second run explained omission as only 489 remaining in exploration budget: an incorrect reading of the intended replenishment scope.
3. After explicit budget scopes in candidate rows and prompt, the model approved both proven replenishments plus one refrigerator and one TV second trial, within shared limits. The two-sale threshold and real cash guard remain intact. This proves correct approval routing in this snapshot, not a sales uplift.

All 265 tests pass, including actual ASGI receipt signing/restart flow, grade boundaries, one-shot trial persistence, no repeated unknown supply, and existing promotion/cash/endgame guards. Initial and revised probe/test logs are retained. Source and runtime deployment are recorded separately.

Evidence: seller-funnel-audit-v2-20261104.json, seller-claims-second-trial-tests-final.log, second-trial-model-probe[-v2/-v3]-20261104*/.
