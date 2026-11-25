# Checkout transport regression

One independent synthetic test passed using the current deployed catalogue runtime v2, genuine catalogue context, Mock Model quote_and_send, original dispatcher checkout, and official SDK ASGI final response. Final artifact data and checkout JWT are byte-for-byte identical to the original dispatcher return. JWT signature verification and item/claim/price/unit against the synthetic issued sale passed. No settlement, real Model, network payment or production state change occurred.

The initial verifier assumed JWT keys sku/grade and status quoted; the actual contract is item/claim and issued. That initial verifier failure and raw synthetic response remain private. Only verifier assertions changed; business source did not change.

Set CHECKOUT_QA_ROOT to a fresh private output directory before running the host test from the existing operator checkout. The SDK transport and genuine tool bytes are pinned in safe-result.json. This proves checkout data delivery, separately from public price rendering.
