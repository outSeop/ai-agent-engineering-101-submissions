# Semantic3 listener-only host infrastructure

New listener18808 proxies unknown task IDs and card GETs to fixed18807, retaining both prior edges18807 and18806 plus original main18805. Distinct marker r4-semantic3-front-v1; private state runtime/front-semantic3-edge. The original identity/token check still uses source127.0.0.2 to main18805. SDK7, wallet, DB, financial core, native tools and existing running services are untouched. The native/runtime source is separately pinned; this package contains no business source or forge metadata.

The root-only transition guard defaults to inspection, and requires expected main PID, old18807 PID and older18806 PID. It queries the seop service manager with fixed runuser identity. Apply changes only the single exact own NAT rule at OUTPUT1 from to-port18807 to18808 by -R, preserving original comment, .1 source/destination, dport18805 and UID1000. Rollback returns to18807. No flush/deletion, process restart or conntrack reset. Before apply require same card/name/description/URL/wallet across18805/6/7/8, same pending sale URLs and10seconds TCP idle on all old listeners.

This is compare-before/after validation, not atomic CAS against noncooperating iptables writers. Root must be the exclusive network-rule operator. Both old task stores must remain alive; context hints TTL is not task-store expiry. Unknown old task IDs are never converted to new sessions or consent. Cross-process customer_active coordination is not promised.

Model budget is unchanged: one decision, local30s/max800 tokens inside40s flow, no repair/retry. Local timeout does not cancel upstream provider work. Tests use isolated Toolbox roots and mock networking. No listener/rule or live Model call is performed during staging QA.

Root inspect example: transition_guard.py --package-manifest-sha SHA --expected-main-pid MAIN --expected-old-edge-pid EDGE18807 --expected-legacy-edge-pid EDGE18806 --expected-public-url ORIGINAL_HTTPS_URL . Add --apply only after independent review; --rollback reverses to18807. Service template intended unit: ourolabs-market-r4-semantic3-front.service.
