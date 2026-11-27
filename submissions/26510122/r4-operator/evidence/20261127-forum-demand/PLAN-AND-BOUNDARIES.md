# Forum targeting and first-purchase benefit repair

Status: implementation in isolated native SDK session; no operational change at this checkpoint.

The user explicitly asked to repair buyer-request collection/stock matching and advertise the actual first-purchase extra5% benefit. Existing DB, two wallets, acquisitions, original seller Model/loop and paused r4/r4-2/r4-3 automations must be preserved. New procurement campaign activation is a separate task still awaiting approval.

Verified baseline: own24h80 confirmed posts/78SKU/A26B34C20, all standalone, reply0; all195 option-generating ticks have reply_options0. Mixed forum latest100 covers about14min/61 buyer rows at inspection, despite original eligibility maxage6h. `since=0` returns newest ascending; `since>0` returns earliest rows after cursor. Current lower-bound search and bounded forward paging must prove coverage, not call a partial feed complete.

Business changes must be Model-authored via original Mind→forge_tool→ordinary SDK; the public exact c15424... parent and four original version5 files have independent HTTP200/bytehash proof. No private customer message, reasoning, keys or wallet data are approved development source. HOST only orchestrates exact native tools, bounds execution and verifies source.

## Important deployment boundary

Original `managed_launcher.py:51–90` captures native slate2 source/pins and background tick at startup. `r4_forum_slate_host.py:51,90,174–190` computes/validates cached eligibility before dispatching publication. No SIGHUP/ExecReload/management reload hook exists. Expanding only publisher eligibility does NOT put new reply choices into the already-running Model context.

However, original SDK `Toolbox.run:300–317` executes current `tools/forum_marketing` files afresh on every invocation, including rereading permission.yml. A fully genuine replacement with unchanged authority can update final rendered benefits without restarting main, CF, worker or edge task stores. Preserve the separately pinned `codex-r4/forum.py` unchanged. Preserve atomic unknown/sending publication lock, source verification and final inventory/price checks. A script-authored tool body/forged provenance is not acceptable.

Ordinary main restart is unsafe under the current preservation requirement: main1192914 and cloudflared1192922 share the service cgroup, KillMode=control-group, SIGINT handler and SDK finally terminate CF. Main-only forced kill also drops its CF output pipe reader. The original InMemoryTaskStore has no enumeration/export/import API; front stores surviving does not preserve the original main store. No restart, process injection, added autonomous loop or misleading claim of hot-reloaded targeting is authorized by this checkpoint.

Next: generate and independently test native forum descendant with bounded buyer6h acquisition, conservative short-name/alias matching, same final recheck, exact current policy/budget-gated bonus disclosure. Stage the new scope/old genuine2 prioritizer/original Mind glue. If native publisher replacement passes checks, apply only that no-restart source exchange, then confirm next actual seller post includes valid bonus terms. Expanded targeting stays staged until a separately reviewed main-process transition can preserve the required state or the user explicitly accepts its concrete effects.

Bonus semantics from actual installed native tool: basis is grade list base; 5%, max5000 credits, first eligible verified settlement+delivery per sending wallet, global configured lifetime budget, active policy interval, next purchase only,7days from original settlement, refund revocation. Current policy ends2026-11-28 20:32:49 KST; do not renew/change policy, budget or awards as an advertising fix. Invalid, expired or exhausted policy means omit bonus, never advertise an unverified promise.

Private baseline is local runtime/marketing-request-20261127-root/before-private.json. Original DB/device/inode, wallet/source identities, price/bonus policy, stock four files and five PID/restart snapshots are pinned. The pending unpaid sale is already missing due to expired inventory, not silently cleared. Runtime raw logs remain private and untouched.
