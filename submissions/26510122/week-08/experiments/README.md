# Seller introduction experiment — November 3, 2026

The token-saving introduction is a promising presentation candidate. This small
probe did **not** establish lower model-call counts, higher settlement rates, or
live-market profit. Existing seller copy and buyer policies were left in place;
no live service was restarted and no market messages were sent.

## What was compared

Six descriptions/opening replies are preserved in `seller_copy_variants.json`:
ordinary inventory, token saving, explicit purchase steps, quick trading, clear
terms/certificates, and minimal wording. The stocked product, price, grade,
certificate, warranty, reviews and firsthand-history conditions were identical.
The full messages differ in length and emphasis, so this does not isolate the
causal effect of the word “tokens.” The claims are not proven capability
differences between shops.

For each of the two CLI model identifiers, six circular arrangements were
tested in both food and goods contexts: 12 choices per model. Every introduction
appeared in each position twice. Anonymous IDs were fixed to display positions.
Jobs were shuffled with a saved seed. Each call used a fresh temporary context.
The buyer's ordinary objective was useful surplus and valid settlement; the
selection prompt did not ask it to minimize token use.

**Visibility limitation:** our current `market_buyer_r3.choose` does not consume
Agent Card descriptions. Its card lookup happens after selection and only reads
the endpoint. Therefore this choice experiment measures what happens **if the
descriptions are visible**, not an improvement to our deployed selection flow.
Other agents' use of descriptions was not verified.

## Observed choices

| Introduction | gpt-5.6-luna, n=12 | gpt-6-luna, n=12 |
| --- | ---: | ---: |
| Ordinary inventory | 1 | 0 |
| Token saving | 6 | 4 |
| Explicit purchase steps | 0 | 2 |
| Quick trading | 2 | 1 |
| Clear terms/certificates | 2 | 4 |
| Minimal wording | 1 | 1 |

Ten of twelve choices in **each** model came from the first two displayed
positions. Rotation balances exposure, but this still shows strong position/ID
sensitivity and weak discrimination when economics are tied. These are small
descriptive samples, not independent real customers or statistical proof of an
advertising effect. The two model groups should remain visible separately.

Two additional independent buyer-role sub-agents received different description
orders. Under ordinary buying priorities, one weakly preferred explicit steps;
the other explicitly used displayed order to break an economic tie. When
conversational overhead was explicitly prioritized, the first preferred minimal
wording, while the second retained its tie-break. Their inherited model identity
was not separately reported; these are two judges, not two additional confirmed
model families. Original answers and mappings are preserved in
`../logs/seller-copy-independent-judges-2026-11-03.json`.

## Actual buyer-code probe against an offline shop

The existing `buyer_r3.negotiate` ran twice for each opening variant using the
real `gpt-5.6-luna` follow-up model. All HTTP calls were intercepted by a local
MockTransport. Every mock shop opened at 900, received an initial 650 offer,
countered at 800, and issued a placeholder receipt only for an offer of at least
800. Buyer authorization was 850. No seller model or real checkout ran.

| Opening variant | Requests per negotiation | Buyer model calls per negotiation | Mock receipts, n=2 |
| --- | ---: | ---: | ---: |
| Ordinary inventory | 4 | 2 | 1 |
| Token saving | 4 | 2 | 0 |
| Explicit purchase steps | 4 | 2 | 2 |
| Quick trading | 4 | 2 | 1 |
| Clear terms/certificates | 4 | 2 | 1 |
| Minimal wording | 4 | 2 | 0 |

All twelve negotiations sent three numeric offers. The first offer is fixed
before the model reads the opening; the model sees that opening in its first
follow-up's recent history. The buyer already sends very short numeric messages,
and the mock seller's subsequent replies are fixed. This probe therefore cannot
measure savings in a real seller model's generation cost. Mock receipts contain
placeholder signatures and are **not** settlements or real cryptographic proof.

The two repetitions per copy are insufficient to rank agreement reliability.
In failed mock negotiations the last offer remained below the attainable 800
price, despite the 850 authorization. The current follow-up prompt does not
tell the model how many of its three permitted offers remain. That is a concrete
context omission and a useful separate improvement hypothesis, not an established
cause of each failure. Buyer policy was not changed by this experiment.

Actual CLI input/output usage, cached input and model replies were preserved.
Negotiation prompts averaged 534–557 serialized bytes, while reported CLI input
usage included roughly 12.5k–13.4k tokens of variable system overhead. Caching
also differed between calls. These raw usage counts do not identify a copy-only
cost effect or monetary saving. The invariant call count is the clearer result.

## Evidence and reproduction

There were **49 CLI call attempts: 48 completed and one timed out**. The first
`gpt-6-luna` goods/rotation-0 call exceeded 60 seconds. Its original failure is
preserved, and only that failed case was retried in a separate run with a
90-second timeout. No successful case was rerun or selected away. The aggregate
rejects duplicate successful cases rather than choosing a favorable result.

Run from the week-08 directory with existing CLI model access; output directories
must be new. The commands make real model calls but no marketplace requests.

```sh
.venv/bin/python experiments/seller_copy_probe.py \
  --output logs/seller-copy-new-run --workers 3
WEEK08_MODEL=gpt-6-luna .venv/bin/python experiments/seller_copy_probe.py \
  --phase selection --output logs/seller-copy-second-model-new-run --workers 2

# Optional: retry only a failed case, preserving its original run.
WEEK08_MODEL=gpt-6-luna WEEK08_MODEL_TIMEOUT=90 \
  .venv/bin/python experiments/seller_copy_probe.py --phase selection \
  --case selection:goods:0 --output logs/seller-copy-new-retry --workers 1
```

The preserved runs are `../logs/seller-copy-probe-2026-11-03/`,
`../logs/seller-copy-probe-gpt6-luna-2026-11-03/` and
`../logs/seller-copy-probe-gpt6-luna-retry-2026-11-03/`. Each includes a manifest,
full model prompts/answers/usage and per-case outcomes. The aggregate JSON is
`../logs/seller-copy-aggregate-2026-11-03.json`, generated with:

```sh
.venv/bin/python experiments/seller_copy_report.py \
  logs/seller-copy-probe-2026-11-03 \
  logs/seller-copy-probe-gpt6-luna-2026-11-03 \
  logs/seller-copy-probe-gpt6-luna-retry-2026-11-03 \
  --output logs/seller-copy-new-aggregate.json
```

Keep token-saving wording as a test candidate alongside clear terms. A next
candidate could combine a brief-chat promise with concrete price/receipt steps;
that combination has not been evaluated here. Establishing real efficiency
requires observing replies, calls and successful checkouts in buyers that
actually see and act on these introductions.
