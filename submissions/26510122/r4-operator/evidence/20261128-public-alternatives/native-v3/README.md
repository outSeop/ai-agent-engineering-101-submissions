# Verified public alternatives

The R4 development model authored a separate read-only tool through the official SDK. The Model selected code edits; the host expanded literal edits mechanically and did not implement marketplace matching logic. We preserved the SDK rejection and the two versions that passed native selftests but failed the independent present-title guard. Version 3 passed the same general checks.

From the operator root:

    .venv/bin/python -B evidence/20261128-public-alternatives/native-v3/test_public_alternatives_sdk.py --source deploy/public_alternatives_native_v3/tools/public_alternatives

The tests use synthetic stock and NoWallet. A separate synthetic question against the existing current public cache verified read-only matching and exact render facts, with no actual Model or financial action.
