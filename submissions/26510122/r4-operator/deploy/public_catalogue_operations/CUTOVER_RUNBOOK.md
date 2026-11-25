> Historical v1 cutover record. Current host release is v2; do not execute v1 pins against the active v2 launcher. Preserve DB state during any code rollback. See SERVER_CODEX_HANDOFF.md.

# R4 catalogue cutover

The deployed source is the pinned `public_catalogue` v2 inside host release `public_catalogue_runtime_v1`. The main service currently uses v4b. Run these commands as the existing WSL operator in one Bash shell. Proceed only after genuine Model and independent QA approval.

## Prepare while the shop is running

```bash
set -euo pipefail
umask 077
OP=/home/seop/.local/share/ourolabs-r4-checkout/submissions/26510122/r4-operator
LIVE="$OP/../round-4"
STAGE="$OP/runtime/r3-stock-20261124-204104/agent-work/validation"
PY="$OP/.venv/bin/python"
UNIT="$HOME/.config/systemd/user"
MAIN=ourolabs-market-r4
PRODUCER="$MAIN-customer-context"
RELEASE=public_catalogue_runtime_v1
MANIFEST=69df7f745a4a90b841aba1dcd2094c94216e0c9aa32690583034cbda5def5b11
BACKUP="$OP/runtime/catalogue-cutover-$(date +%s)"
PREFLIGHT="$STAGE/public_catalogue_cutover_preflight.py"
LAUNCHER="$LIVE/codex-r4/managed_launcher.py"
BASE_DROP="$UNIT/$MAIN.service.d/90-public-catalogue.conf"
PRODUCER_DROP="$UNIT/$PRODUCER.service.d/90-public-catalogue.conf"

test ! -e "$BASE_DROP"
test ! -e "$PRODUCER_DROP"
test ! -e "$OP/deploy/$RELEASE"
"$PY" -B "$PREFLIGHT" backup --backup-dir "$BACKUP"
TEMP_RELEASE=$(mktemp -d "$OP/deploy/.public-catalogue.XXXXXX")
cp -a "$STAGE/$RELEASE/." "$TEMP_RELEASE/"
test "$(sha256sum "$TEMP_RELEASE/MANIFEST.json" | cut -d' ' -f1)" = "$MANIFEST"
mv -T "$TEMP_RELEASE" "$OP/deploy/$RELEASE"
PYTHONPATH="$LIVE/codex-r4" "$PY" -B "$STAGE/$RELEASE-launcher.py" check \
  --operator-dir "$OP" --agent-root "$(realpath "$LIVE")" --enable-procurement \
  --enable-public-catalogue > "$BACKUP/launcher-check.log"
tail -n 1 "$BACKUP/launcher-check.log"
```

The last JSON line must report `official_kit_files_verified=7`, `public_catalogue=true`, `joined_or_started=false`. The backup contains a checked SQLite online copy and a private wallet-hash/inode and DB-inode baseline. Wallet key bytes are not copied. Check these items again if the staging pause is lengthy.

## Cut over outside the wholesale window

```bash
# Pause only the existing timer. Wait for its one-shot process to finish cleanly.
systemctl --user stop "$PRODUCER.timer"
for attempt in {1..35}; do
  producer_state=$(systemctl --user show "$PRODUCER.service" -p ActiveState --value)
  if [[ $producer_state == inactive || $producer_state == failed ]]; then break; fi
  sleep 1
done
test "$producer_state" = inactive
"$PY" -B "$PREFLIGHT" drain-live --backup-dir "$BACKUP"
systemctl --user stop "$MAIN.service"
if ! "$PY" -B "$PREFLIGHT" drain-stopped --backup-dir "$BACKUP"; then
  systemctl --user start "$MAIN.service" "$PRODUCER.timer"
  exit 1
fi

# Exact files only, on the same filesystem as their targets.
test "$(sha256sum "$LAUNCHER" | cut -d' ' -f1)" = be9cbf962ea4c5edd91eeea6d567411369de8e025d30112d5914f1cc2258c21f
test "$(sha256sum "$STAGE/$RELEASE-launcher.py" | cut -d' ' -f1)" = d709e8bb6ce227658c173bc88e686b2533fc6253acd2f0c5850edeb2ef2565ff
install -m 600 "$STAGE/$RELEASE-launcher.py" "$LAUNCHER.catalogue-next"
mv -T "$LAUNCHER.catalogue-next" "$LAUNCHER"

mkdir -p "$UNIT/$PRODUCER.service.d"
printf '[Service]\nEnvironment=R4_ENABLE_PUBLIC_CATALOGUE=1\n' > "$BASE_DROP.next"
mv -T "$BASE_DROP.next" "$BASE_DROP"
printf '[Service]\nExecStart=\nExecStart=%s -I -B %s --operator %s --manifest-sha256 %s --publish-cache\n' \
  "$PY" "$OP/deploy/$RELEASE/public_catalogue_snapshot_producer.py" "$OP" "$MANIFEST" > "$PRODUCER_DROP.next"
mv -T "$PRODUCER_DROP.next" "$PRODUCER_DROP"
systemd-analyze --user verify "$MAIN.service" "$PRODUCER.service" "$PRODUCER.timer"
systemctl --user daemon-reload
systemctl --user start "$MAIN.service"
# Check local Card and matching registration before starting the read-only producer.
```

The catalogue route takes precedence over both previous environment flags. The single existing producer service has its ExecStart replaced and the single existing timer is reused. Main start brings the PartOf worker back through its original dependency. The read-only producer requires an active main and matching registry.

## Verify and restore periodic snapshots

After the local Card and public registry report the same newly registered HTTPS endpoint and preserved wallet, run the producer once and then restart its prior timer.

```bash
systemctl --user start "$PRODUCER.service"
systemctl --user start "$PRODUCER.timer"
systemctl --user is-active "$MAIN.service" "$MAIN-worker.service" "$PRODUCER.timer" "$MAIN-card-keeper.timer"
systemctl --user show "$MAIN.service" -p MainPID -p NRestarts
systemctl --user show "$PRODUCER.service" -p Result -p ExecMainStatus -p DropInPaths
"$PY" -B "$PREFLIGHT" verify --backup-dir "$BACKUP"
```

Use the existing `worker_bootstrap.registered_party()` and `card_url(get(LOCAL_CARD))` read-only checks or the existing independent operator verification route. Check `/api/shops` independently against the local URL and public wallet. The quick tunnel URL can change. Confirm the public Card at the new URL and ordinary public information A2A reply without purchase intent. Record safe HTTP/task outcome, client time, `public-catalogue-metrics.json` phase deltas, and producer freshness from the cache metadata only. Check hidden-service status and seven kit hashes; keep the card keeper untouched. Never log the owner code, worker tokens, wallet bytes, or customer rights.

## Rollback

Use the same drain protections before stopping a running new instance. If unresolved work exists, wait and reconcile through the live service instead of overwriting state. If installation failed while stopped, the old launcher can be restored immediately because no new service executed. The reviewed source bundle can remain in place.

```bash
systemctl --user stop "$PRODUCER.timer"
# Confirm the oneshot has finished, and if main is running, drain-live before stop.
systemctl --user stop "$MAIN.service"
"$PY" -B "$PREFLIGHT" drain-stopped --backup-dir "$BACKUP"
test "$(sha256sum "$BACKUP/managed_launcher.before.py" | cut -d' ' -f1)" = be9cbf962ea4c5edd91eeea6d567411369de8e025d30112d5914f1cc2258c21f
install -m 600 "$BACKUP/managed_launcher.before.py" "$LAUNCHER.rollback-next"
mv -T "$LAUNCHER.rollback-next" "$LAUNCHER"
rm -f -- "$BASE_DROP" "$PRODUCER_DROP"
systemctl --user daemon-reload
systemctl --user start "$MAIN.service"
# Verify local Card/registry/wallet again, then run the original read-only producer.
systemctl --user start "$PRODUCER.service"
systemctl --user start "$PRODUCER.timer"
"$PY" -B "$PREFLIGHT" verify --backup-dir "$BACKUP"
```

The SQLite copy is for forensic recovery. Keep the active DB and its WAL/SHM files in place for both directions.

