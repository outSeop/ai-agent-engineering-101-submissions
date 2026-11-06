# Procurement outcome tracking

The model approves a basket before the supply window. On opening, tools recheck
cash, reservations, stock and time, then return a `buy` protocol. Its
`_procurement` metadata links each line to the exact decision and reservation.

The frozen `seller_kit.py` loads the official shared kit without modifying it.
`procurement_transport.py` observes its existing restock calls. Authentication,
request bodies, three 429 retries, delays, inventory refresh and 402 batch stop
are still handled by that kit. Logged HTTP metadata contains no headers, keys,
tokens or response bodies.

Stages: `portfolio_execution_started` → `portfolio_execution` →
`portfolio_execution_completed` → `procurement_protocol_output` →
`procurement_protocol_received` → `procurement_request_started` →
`procurement_supply_result` → physical unit reconciliation. An emitted request,
an accepted supply response, arrival and resale are distinct observations.

Only an exact intent/decision/window/SKU/quantity match can release funds for a
definite rejection or a line never sent by a finished batch. These also stop
consuming the rolling exploration budget. A timeout or 5xx retains its
reservation. An accepted response also retains it until a physical unit is
observed. Conflicting physical evidence restores conservative accounting.

The independent planner worker reconciles about once a minute under the same
portfolio lock. `state/procurement-health.json` lists old unknown arrivals and
missing execution/kit/request/response stages. Warning events are deduplicated.
Alerts never trigger automatic retries or purchases.

Historical repair is conservative and does not rewrite raw logs. Run
`ops/reconcile_legacy_supply.py --runtime state/seller-runtime --console
logs/seller-r3-kit-console.log` for a dry run, adding `--apply` to persist it.
It requires a complete, uniquely matched printed protocol plus its timestamped
emission and exact saved intent. It can recover definite HTTP refusals and
lines after the official kit's `buy[:10]` cutoff. Duplicate batches or dates,
missing evidence, partially observed quantities and 5xx are not released.

Validation uses the actual shared kit's restock function with synthetic HTTP
responses: 402 batch interruption, never-sent tails, retry exhaustion, success,
5xx, timeout, conflicting evidence and ambiguous legacy batches.
