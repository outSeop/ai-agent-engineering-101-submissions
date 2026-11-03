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
   The model chooses a SKU and demand scenario. The newsvendor calculation then
   chooses a lot size for that forecast. Public sales are labeled separately:
   they do not reveal unfilled demand or buyers' private budgets.
   Before five observed shop requests for that SKU, the lot is capped at two
   units; total live stock is capped at 20 units. If the model is unavailable,
   the hook holds rather than speculatively buying.
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
Git. Round 3 opens November 3; actual settlement behavior can only be verified
then. Until live outcomes exist, the grade multipliers and demand estimates are
experimental inputs rather than measured improvements.

## Known gaps to check at launch

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
