# Third genuine proposal7 — selftest rejected

The original SDK rejected selftest's expected active bonus. Exact proposed logic/test/permission and safe receipt are preserved without inventing an accepted forge record. No production change or real posting occurred.

Initial diagnostic found a fixture-only error: Python3.12 TemporaryDirectory returns an absolute path; the test replaced the protected relative POLICY constant with it, so the actual guard correctly omitted bonus. An external test-fixture adapter using the relative path reached all active/negative bonus assertions and one simulated successful publish.

The next diagnostic found a real proposed-source defect: history filters SQLite typeof(created) to integer, but the original forum_publication column is REAL and original confirmed rows are stored as real. A future genuine repair must accept finite integer/real values bounded to 0<created<=now and project the original exact {grade,category:null,at:int} schema. Do not weaken policy/identity/budget checks to satisfy the fixture. The diagnostic adapter is not the original proposal or an accepted forge.

The root's initial three-submission efficiency limit was not a user budget limit. A further narrow genuine repair may be authorized after diagnostics; no new feature expansion is implied.
