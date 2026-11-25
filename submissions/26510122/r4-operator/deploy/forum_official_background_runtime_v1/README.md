# Optional own-seller official Mind tick (external host infrastructure)

Staging only. No schedules, production services, DB, wallet or procurement were changed. Nine narrow original-SDK/mock tests passed, plus the actual SDK `cmd_run` construction/join/start fixture. These use fake Model and publication callbacks, not a real classroom canary. Failed first candidates/fixtures are preserved separately.

Root composes this optional host with native2 slate host, whose expected bundle manifest is 7aef69c623416aad508ffb3875b6e8644aaa55b0e84ffb176e7581d67625cfa7. No new business rule is implemented here: native eligibility/selection policy controls spotlight choice. A closed choice receives feedback without consuming a publication attempt. The unchanged legacy publisher freshly validates before real publication. One unknown publication still consumes the one attempt.

CRITICAL installation contract: at master `install_mind` definition time, before the launcher replaces `official.Mind`, capture `native_sdk = SimpleNamespace(Mind=official.Mind)` and pass that immutable class facade as the first argument to `install_tick`. Do not pass the later mutable installed SDK module to the tick; otherwise it may re-enter managed initialization. The original `Mind.run_once` function is inherited unchanged. `make_campaign_mind` comes from the pinned existing `deploy/forum_campaign_operator.py`.

After the managed Mind's super constructor:
```
hook = install_tick(native_sdk, coordinator, operator, root, agent, model, ctx,
                    stock=self.stock_coordinator)
coordinator.execute = slate_module.bind(..., audit=hook.audit)
```
The shared `ctx` is stored by reference. Initial SDK context has exactly market/name/tokens/addresses/signer; shop_url and shop token appear after join. No registration fields are invented during construction.

Original coordinator loop and stock serialization remain unchanged. Only coordinator.tick is replaced. Poll120/330 and customer priority are retained. The total Model budget is 25 seconds across all official Mind calls; it is never reset per call or repair. Errors escape the SDK retry-sleep path as a host RuntimeError after private diagnostics, preventing timeout inflation. No Model system/output is rewritten. The Model context has no signer, wallet, addresses or tokens; original operating Model authentication remains internal to its unchanged source.

Private persistent output: operator/runtime/forum-background-official/tick-*/. Native input/result via optional audit callbacks, exact Model messages/responses (token strings redacted in logging only), context/reconcile/outcome, and safe timestamped summary are retained with0700 directories/0600 files. Full context is separately appended as untrusted data with64KiB limit, not hidden in trusted system text. SDK observations can still truncate at6000; full private snapshots avoid treating them as complete. A passive stock.tick observer records status/opens-delta/original idle rule and skip reason; it invokes the original tick once and returns its original result unchanged. Direct early tick returns have safe customer_active/next_poll_not_due reasons.

Read-only diagnosis: current source uses direct Model.complete in the old coordinator, but a current403 was NOT demonstrated. Real successful posts exist, so do not attribute all missing traffic to gateway failure. DB confirmed26 own posts:23C,1A,1B,1without explicit grade; all were spotlights and none buyer replies. Last confirmed grades at observation were A,C,C, so last-two-C did not apply then. Past category is not present in original post text and must stay unknown unless separately observed at publication.

Public GET comparison observed mixed100 had63buyer rows and role=buyer100 had100. Both had0matches for the legacy explicit-request regex within6h. This is not a claim that buyers have no demand. No hidden threads were added to publisher scope. The public schema exposes likes/dislikes/score, not views, reader identities or click counts; no view-to-contact conversion can be computed from it.
