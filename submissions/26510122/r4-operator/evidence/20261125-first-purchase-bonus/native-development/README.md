# First-purchase bonus development evidence

The official Mind used the local GPT-6.2 Sol development CLI to author all four retained tools. The operating classroom model and host integration are separate. No existing wallet keys, ledger or real tool token were included in these development sessions. The public-safe package contains exact native source files, manifest hashes and six derived native forge event summaries. It omits the private raw model responses, ReAct logs, keys, customer data and transactions.

- v1 passed its own SDK test. It used a provisional source-disabled rollout constant and keyed awards by payer plus campaign. It did not implement the final global eligibility or budget contract.
- v2 passed its own SDK test and added the protected config, global payer and capped budget logic. Its integer-only timestamp validation rejected REAL values in the actual legacy SQLite schema.
- The first v3 attempt was rejected because a synthetic temporary fixture was outside the permitted write scope. The second v3 attempt passed. Independent QA then found that v3 could overlook a prior same-payer row with missing evidence and could issue an award after policy removal while waiting on the database lock.
- The first v4 attempt was rejected by the expired-purchase regression. The revised v4 passed its own SDK test and independent synthetic legacy SDK checks, including missing history and policy races. Operational activation and actual credited purchases are distinct evidence.

Each successful source matches the logic and test bytes in the model's actual observed official forge action. The published response fingerprints and private-log fingerprints support later reconciliation without exposing raw text. CLI configuration reports the requested development provider. The upstream model identity is unavailable.

