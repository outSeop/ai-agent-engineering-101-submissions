# Verified alternatives through the SDK

The R4 development model gpt-6.2-sol proposed the version 4 code and selftest changes. The host applied the exact literal edits before the original SDK forged and tested the tool. Version 4 allows a read to advance access time while preserving device, inode, mode, ownership, link count, size, modification time, status-change time, and byte-count checks. Tool authority and marketplace rules remain unchanged.

The manifest binds logic.py, test.py, permission.yml, and forge.json under deploy/public_alternatives_native_v4/tools/public_alternatives. Run the 18 independent ordinary SDK checks from the operator root.

    unshare -Urn .venv/bin/python -B evidence/20261128-public-alternatives/native-v4/test_public_alternatives_sdk.py --source deploy/public_alternatives_native_v4/tools/public_alternatives

## Actual model check

The isolated official SDK ASGI test used 117 synthetic stock rows, a 12-product verified menu, and one Market model call within the 30-second limit. The model chose render_public_alternatives in 8.9908 seconds. The inquiry broker took 11.4169 seconds, and both the seed and inquiry took 12.9624 seconds in total. The SDK returned HTTP 200 and INPUT_REQUIRED. The answer preserved the verified body and added SKU guidance. Its ordered artifact matched the tool's SKU, grade, and price facts. It stated that no checkout document was issued and cleared the earlier durable product hint. The test made no financial executor call or forum post. See [the safe result](actual-market-asgi-safe.json).

## Earlier observations

1. The model chose semantic lookup and received no match although verified alternatives were available.
2. After narrowing the action set, the model returned output that did not parse as a decision.
3. After adding the JSON contract, one model call exceeded 30 seconds.
4. A retry picked the relevant item in direct prose. The existing public response guard declined that reply. The prompt now requires the tool whenever a relevant candidate is selected. Keeping the full menu and removing unrelated context reduced prompt content from 7,172 to 5,134 UTF-8 bytes.
5. On the compact prompt one model call timed out. In a separate request, the stock reader returned source_unavailable before inference. A controlled fixture reproduced that failure by changing only access time. Version 4 passed the access-time regression and the isolated actual-model check above.

The SDK and Market check exercise a synthetic request and isolated persistence. Real-customer conversions, payments, and settlements are outside the verification scope.
