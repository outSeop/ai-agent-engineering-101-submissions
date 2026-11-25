# Independent first-purchase bonus v4 validation

Final core result: **13/13 passed** using ordinary official `Toolbox.run`, original tracked dispatcher/Fixture, and isolated synthetic SQLite databases. No testing flag was manually set. The exact four generated source files are unchanged.

Covers first purchase, returning payer/new rights/campaign rename, missing or contradictory historical evidence, never-settled refunds, REAL expiry, small-base lot creation, event order, global budget/cap concurrency, duplicate concurrency, policy removal while waiting for a lock, transactional rollback, and whole-lot refund/debt/unrelated-owner compatibility.

The first v4 run passed 12 cases; the refund case stopped on a verifier setup error before business execution. After supplying the fixture's synthetic shop address with no key or token, the refund case passed separately. Original private results and logs are preserved. `safe-results.json` clearly separates these runs.

Refund completion used a closed synthetic confirmation database. This proves bookkeeping compatibility; it does not establish real approval, payment or receipt integration. No actual operating readiness is claimed by this QA. Root's subsequent activation is separate from verifier activity.

Reproduction uses the repository's existing tracked `submissions/26510122/round-4/codex-r4/{dispatcher,fixture,price_policy,procurement}.py`, operator kit, and public refund-v3 source. Their exact baseline hashes are in safe-results.json. No business libraries are duplicated. From this folder, choose a new nonexistent private output directory and run:

```sh
BONUS_QA_ROOT=/tmp/bonus-v4-qa-unique /path/to/r4-operator/.venv/bin/python qa_first_purchase_bonus_v4.py
```

The two published host test files only adapt import/output paths; private-original and public hashes are recorded. Synthetic fixture traffic is mocked. Do not point this verifier at production state. Raw logs, fixture DBs, JWTs, real credentials and model reasoning are excluded.
