# Independent card-transition QA

These are externally authored QA/host-infrastructure scripts, not agent-created market tools. Original generated business code belongs in ../sources and is never modified by these tests. Original QA scripts are retained byte-for-byte. The labelled portable wrapper supplies temporary paths and copied pinned dependencies; it never calls tools on production card.json.

Observed results: v2 original selftest PASS; ordinary official Toolbox.call regression28/28 PASS; initial legacy-shape→native→guard→second native refresh→guard→rollback and adversarial-copy checks23/23 PASS. One issuer-contract failure remains preserved: choosing new native description policy anchors on the next refresh rejects protected_policy_overlap_or_change. Stable original skill clauses succeed. V1's2 initial-shape failures and3 deliberate bad-host-authority acceptance probes remain under v1/. Those are distinct source versions and host assumptions.

No actual production card, service, DB, wallet, ledger, customer, model or market was changed/called by these QA scripts. All source/authority views and changed cards are synthetic Fake-only files. This does not prove an actual authoritative inventory producer, live serving, legacy-writer fence, or production maintenance cutover is connected.

From this directory on Linux/WSL, use the operator virtualenv Python:

    <operator>/.venv/bin/python run_portable.py --operator <operator> --sources ../sources --output /tmp/card-transition-qa-NEW

--operator is used only for the existing official kit. No credentials or live state are copied. --sources must contain tools/{apply_staged_card(v2),stage_representative_card(v1),publish_shop_info(v1)} and tools/.deprecated/apply_staged_card@1. Every manifest/source hash is checked. --output must be a new directory. The wrapper copies source and QA into a fresh temporary Fake-only root, then invokes ordinary Toolbox.call. It does not manually set kit.testing. The issuer_limit failure is expected and reported, not converted into a pass. A preserved before-harness-correction script demonstrates a QA fixture JSON-edit error and is not executed.

Native issuer replacement_sha256 must cover exactly pinned stage.render output, excluding separator blank lines. Preserve source authority and original skill policy anchors honestly; a caller boolean or invented label is not authorization. Source provenance from private model responses is derived hashes/metadata only; raw thoughts/messages are not included.

publication-proof.json records exact-four-credential plus JWT/API-pattern checks before/after copy. No secret value or secret hash is exported. The scan is static hygiene, not a production capability audit.
