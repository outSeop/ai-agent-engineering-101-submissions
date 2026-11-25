Current release: `public_catalogue_runtime_v2`, manifest `e83ca0ac4493d7de4d50190f0bbadbb8f89fe89e74b82038dec30d82159e24db`. Host v2 clarifies render arguments and records schema rejection; the original genuine tool remains v2. The v1 runbook below is historical. The single producer now verifies the v2 manifest. See SERVER_CODEX_HANDOFF.md for executed cutover and private backup paths.

# Catalogue host operation

Use one existing `ourolabs-market-r4-customer-context.timer` and replace only its service ExecStart with the reviewed producer. Do not run old and new producers concurrently. The main catalogue flag takes precedence over previous public-reply/context flags; those remain available for rollback. The installed drop-ins are `90-public-catalogue.conf` under the main and customer-context service directories.

`CUTOVER_RUNBOOK.md` records the original executed staging paths and gates. Its preflight helper remains in the private live staging directory named there, together with per-cutover private SQLite online backups and wallet/DB identity evidence. It is not a standalone fresh-checkout deployment script. Preserve the active DB/WAL/SHM, keys, inventory and ledgers. Never restore an old DB to roll back code. A quick-tunnel restart can change the URL; verify registry and public Card after propagation and restore the one producer timer.

The immutable release and genuine forge files are under `../public_catalogue_runtime_v1/`. Check its manifest before activation. The legacy financial dispatcher is unchanged and is not claimed to be migrated or newly verified by catalogue-only tests.
