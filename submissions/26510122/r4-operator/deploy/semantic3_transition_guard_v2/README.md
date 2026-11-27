# Separate semantic3 transition-only guard v2

No listener/app/financial/SDK/runtime change. The live original front package remains deploy/front_semantic3_edge_runtime_v1, immutable manifest25d099830f88215ffebc37c41fd9cef8c3a28d0206f411ab9488c646a62980d9, and this helper additionally verifies its exact files before use. Existing18808 and previous services are not restarted.

Confirmed source bug: the original guard ignored the identities() return after idle10 and compared the public card to an older description. The first failed postcheck did not identify its specific mismatched field; a description race is therefore a plausible cause, not a proven historical diagnosis. Root preserved the failed attempt and successful exact rollback.

After idle10 this helper binds the latest origin again. Postcheck uses strict original name/roles/wallet/supportedInterfaces/URL/pending URL invariants, and compares public description against freshly agreed local cards. Description-only observation races may retry at most3 attempts within a20-second monotonic budget. Each postcheck HTTP timeout is clamped to min(3,remaining); late responses are not accepted. A known previous marker never passes: when enough budget remains, wait6seconds (greater than the old5second keepalive) then try again, at most2waits. No conntrack reset or process changes. Unexpected marker, identity/URL/pending changes fail immediately.

Apply still requires the exact single own OUTPUT rule, unchanged comment/.1source/.1destination/dport18805/UID1000, expected original+old edge PIDs and continuous10second old-listener idle. -R changes only to-port18807→18808. Rollback returns to18807 and does not require a failed new18808 listener to answer. No delete/flush. Public failure still invokes the exact reverse only against the unchanged owned rule. Optimistic compare-before/after protection is not CAS against an unrelated concurrent iptables writer: root must remain the exclusive operator.

CLI arguments are unchanged: --package-manifest-sha THIS_NEW_MANIFEST --expected-main-pid MAIN --expected-old-edge-pid EDGE18807 --expected-legacy-edge-pid EDGE18806 --expected-public-url ORIGINAL_URL . Default inspect; explicit --apply/--rollback are separate root actions. Do not pass the original front manifest as this guard's own manifest.

QA:9 existing transition/PID/selector checks +9 focused card refresh/deadline checks. All networking, sleeps, services and iptables were mocked. No actual apply or Model call was performed by the auditor.
