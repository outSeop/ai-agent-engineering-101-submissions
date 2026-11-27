# Cache reader dependency isolation (HOST only)

The live forum publisher changed from v5 to v9 at 2026-11-27 22:03 KST.
The existing catalogue and card offer producers still verified v5 at that mutable path,
so customer-cache refresh failed and the card keeper returned maintenance_unavailable.

This package reuses the exact archived v5 four files (including its unmodified forge
record). It is a dependency snapshot, not a new forge or a claim of new model authorship.
The original original-source manifest and original producer files remain unchanged.
Only the producer's verify_source filesystem root is rebound to this protected snapshot.
The existing v8a catalogue and native_card_keeper_v1 helpers are loaded separately with
their original pins; their acquire functions, pricing, reservations and SQL are unchanged.

The original price_context_runtime_v8a bootstrap retains its absolute price-policy binding
and runs the original pinned entrypoint. Catalogue only performs original GET observations,
read-only SQL, and publication of the original TTL150 catalogue/sidecar. The existing card
keeper retains its original model selection, cooldown and publication authority.
No new service, timer, business loop, payment or procurement authority is introduced.
Main/frontend services, wallets, ledgers, original stock8 and publisher9 remain in place.

Use --check before activation. This verifies sources without executing a target or reading
production tokens/DB. Existing timer overrides must pin MANIFEST.json with
--package-manifest-sha; preserve the original target arguments. Roll back by restoring
the previous existing drop-in contents and daemon-reload; no main restart is needed.

This fixes dependency failure only. New broad buyer-demand matching remains staged;
cache recovery is not evidence of buyer conversion or a new settlement.
