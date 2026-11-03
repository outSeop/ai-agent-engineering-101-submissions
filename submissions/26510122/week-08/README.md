# Week 08 shop: model decisions with inventory calculations

This is the first Round 3 shop and buyer implementation. It does not silently
switch the running week-07 services. Live settlement evidence is still needed.

## Decision path

1. The kit v4 writes `.market/inventory.json` and `catalog.json`. The seller
   offers only an in-stock unit, and temporarily holds a unit after signing a
   receipt so that another negotiation cannot promise it immediately.
2. `newsvendor_tool.py quote` calculates transparent A/B/C price anchors from
   the actual unit cost, list price, grade, expiry and storage charge. The
   initial A=1.0, B=0.8, C=0.6 multipliers are hypotheses, not lecture values.
3. `market_memory.py` keeps append-only `logs/shop-events.jsonl` and imports
   confirmed `[acp] settled` lines from the kit log. A signed receipt stays
   `RECEIPT_PENDING` until the kit reports a ledger settlement. Each model
   prompt gets a bounded summary of first-hand outcomes, including failed and
   unresolved negotiations.
   `inventory_observation.py` separately attributes exact SKU visits and stockouts,
   deduplicates tasks, and measures stock exposure only between snapshots at most
   120 seconds apart. Missing snapshots and ambiguous product requests remain
   unknown. A stocked-shop visit rate is a selected observation, not total demand;
   the public `demand.json` lists categories without demand weights.
4. The Codex harness chooses the physical unit, opening price and follow-up
   action. The quote candidates and memory are evidence for that choice. The
   seller records the model decision separately from the emitted ask/counter.
   Code checks that the selected unit still exists and the price is positive.
5. The `restock` hook offers the model a bounded set of food SKUs from its own
   observations, recent public Round 3 settlements and exploratory samples.
   The model proposes a SKU and demand scenario. The newsvendor tool calculates
   quantity candidates; a second model decision approves one complete plan
   (quantity, target stock, validity and total unit budget) or holds. The tool
   calculates both a tight budget and a repeat-sales budget, so the model sees
   that replacement authorization is distinct from buying stock up front.
   Public sales are labeled separately:
   they do not reveal unfilled demand or buyers' private budgets.
   Before five observed visits for that SKU in the last 12 hours, the entire
   plan is capped at two units; total live stock is capped at 20 units.
   `replenishment_plan.py` reuses that approval for 180 or 600 seconds within the
   fixed target, per-order quantity and total authorized quantity (at most 20).
   It reserves emitted intents before returning them, waits for a newer
   inventory snapshot before another intent, and checks the cash reserve again.
   Expiry, catalog/grade changes, three newly observed stockouts or a substantial
   observed visit-rate change require reassessment. Budget exhaustion respects
   the three-minute model cooldown; new risk evidence can bypass it.
   For ordinary budget/lease renewal, an unchanged scenario may be reused for at
   most 30 minutes, while the model still approves newly calculated quantities
   against current evidence. The approver can request `replan`, which emits no
   purchase and asks the next hook for a fresh scenario. Risk changes bypass
   this shortcut. New planning takes two model calls, stable renewal one, and
   valid plan execution zero.
   Inventory older than 30 seconds and failed model approvals emit no purchases.
6. `market_buyer_r3.py` selects only stocked, acceptable SKUs from other shops.
   The model chooses a shop, SKU and first offer; `buyer_policy.py` guards the
   private budget and a provisional surplus margin. Food requires a certificate
   and enough shelf life for the user's use window plus a buffer. Goods require
   a certificate and grade A or B; a six-hour warranty is preferred, not a
   blanket requirement before observing market availability.
7. `buyer_r3.py` negotiates through A2A without disclosing the private mandate
   cap. The model chooses later offers; the code caps each offer and checks the
   signed receipt against the selected SKU, final offer and task. Kit v4 still
   verifies signatures, ACP checkout, AP2 mandates and the payment ceiling.
8. `buyer_memory.py` imports kit payments separately from pending receipts and
   remembers goods breakage by product name without blaming a particular shop;
   shop identity is the registry `name`, with changing URLs recorded as aliases.
   Legacy URL-only events are reused only when their identity is unambiguous;
   an order's recorded shop identity takes priority over a reused address.
   Corrected payment outcomes and quality records are joined by order/ledger
   rather than counted as separate purchases. The model sees aggregate outcomes,
   grade-specific paid-price ranges and at most three linked cases. Selection
   receives a shorter evidence brief plus labeled public-review examples, so
   tool ordering never hides the reason a shop was included.
   `review_r3.py` records settled grade/value and can publish a ledger-backed
   buyer forum note after a useful discount. Forum posts are spaced 30 minutes
   apart. Buyer price shares (food 0.85, goods 0.75 of list) are starting
   hypotheses and need live calibration.

The newsvendor rule is `F(Q*) >= (p-c)/(p-v)` for a discrete demand forecast,
where `p` is expected sale price, `c` estimated purchase cost and `v=0`
for food that expires. The forecast horizon is the smaller of 24 hours and
one quarter of the catalog shelf life. Before supply, actual grade and cost
are unknown: `restock.py` uses the market's grade frequencies and cost-range
midpoints, which imply expected food cost of 0.5 times list price. The real
cost and grade from inventory replace that estimate when a unit arrives.
The forecast mean cap (1.5 with sparse visits, otherwise 10 units per horizon)
is our conservative policy, not a published market demand limit. Both the
effective forecast and this cap are shown to the final model approver.

## Context construction

Each model call starts a fresh session. The application supplies current facts,
calculation results and a small historical view; it does not maintain an LLM
summary or a vector database. `context_compaction.py` makes deterministic views:

- Current inventory, cash, authorization caps and tool candidates remain separate
  from historical observations and temporary forecast assumptions.
- Older trades contribute exact outcome counts and paid-price ranges by grade.
  At most three relevant same-grade cases plus two other-grade cases retain
  opening/settled grade, cost, historical hours left, price and final outcome.
  Offer/counter arrays retain their last four values and original counts.
- Seller opening prompts share one memory per SKU/grade instead of repeating it
  per physical unit. Restock links and filters candidate-SKU trades before
  choosing cases, so inventory snapshots cannot push settlements out of view.
- A buyer sees a short first-hand seller evidence brief AND separately labeled
  public-review examples. Current negotiation context keeps four short messages;
  original messages are appended to the event log, including messages observed
  before a network failure. Model explanations are not promoted into rules.

Budgets are serialized UTF-8 bytes, not token estimates: 3,200 per buyer memory,
1,600 per buyer-selection brief, 3,600 per seller SKU/grade (a shared 12,000-byte
opening-memory allowance), and 3,000 for restock trade history. Buyer selection
keeps its full prompt within 32,000 bytes by removing the lowest-priority
optional candidates; every displayed candidate retains its payment cap.
The harness logs the actual serialized prompt byte count. Event files are not
rewritten or truncated by constructing these views.

On synthetic long-history fixtures, seller memory went from 12,032 to 1,951
bytes and buyer memory from 36,708 to 955 bytes. Two real model probes separated
40 paid trades from one pending receipt, retained the C-grade/two-hour discount
condition, and selected confirmed payment evidence over higher public stars.
These are context-size and evidence-reading checks, not market-profit results.

## Run locally

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python ../../../scripts/market_kit.py join --dir . --market https://market.ourolabs.ai \
  --name outseop-26510122 --tunnel
```

The join command above requires the same shop key and owner claim as the
existing market identity, and a reachable tunnel. Do not create a second live
shop alongside the week-07 supervisor. Neither keys nor claim codes belong in
Git. Check the public `/api/shops` round before running the economy hooks;
the restock command holds outside Round 3. Until live outcomes exist,
the grade multipliers and demand estimates are
experimental inputs rather than measured improvements.

## Known gaps to check at launch

The public [Round 3 contract](https://market.ourolabs.ai/agent.md) supplies the
inventory fields, supply grade/cost ranges, food grade cutoffs and goods storage
rule. An idealized local forecast/review ablation is not a live-market replay:
at the November 3 check the public API was still in Round 2 with no Round 3
entries in the latest 500 ledger rows. In the 18 synthetic demand cases, shorter
periodic review improved mean cash profit, while the faster forecast increased
fill rate but slightly reduced mean profit. Both short- and long-window evidence
are therefore shown to the model rather than automatically preferring the short
forecast. Python plots and simulation data remain in the ignored `flow/` folder.

The model probes use explicitly synthetic visits, settlements and stock with
public catalog metadata. The initial probes exposed excessive budget renewals;
approval now selects complete tool-calculated lease/budget alternatives, and
stable scenario renewals need only the final approval. A 20-hook probe made four
real model calls, versus seven scheduled calls under the old three-minute
cooldown. This checks call reuse and guards, not live service or profit.

- `inventory.json` can be ten seconds old. The seller rereads it before a quote
  and a receipt; the kit makes the final stock check during checkout.
- A unit's food grade can deteriorate during negotiation. The seller rereads
  it and does not make a fixed grade claim in the receipt. The kit attaches the
  market certificate for the unit by default.
- A signed receipt may fail checkout. Only `[acp] settled` is a confirmed sale.
- Shop visits are a selected sample of market demand. Replenishment forecasts
  must not treat them as all demand; early lots are deliberately small.
- Goods need a different multi-period holding and warranty model. This first
  replenishment hook buys food only; the seller can sell goods already in stock.
- The buyer policy has not yet been exercised against Round 3 live shops. Track
  `payments.jsonl` refusals and adjust the initial price shares, grade filter,
  food buffer and warranty preference from confirmed settlements.
