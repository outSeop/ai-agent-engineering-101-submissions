# HOST task persistence and direct ownership registry (staging only)

No service, listener, API/Model, firewall or financial operation was performed. No SDK or existing frontend source was changed. The separate HOST database must be created and opened as the same service UID, in an owned canonical 0700 directory; the SQLite file is 0600. It must never reuse the financial database. Full protobuf task bodies are private data, not public evidence.

## Integration API

`TaskStateDB(path, allowed_legacy_ports=tuple(range(18805,18811)))`; `SQLiteTaskStore(db, owner_resolver=original_SDK_resolve_user_scope)`. The native store provides async save/get/list/delete. Native save commits the serialized task and its logical `current` route in one SQLite transaction. Delete retains an ownership tombstone. The router resolves `current` to the stable engine listener; task IDs never act as authentication.

Registry methods: get_route(task_id, scope=''), bind(task_id, destination, scope='', provenance='own_list_tasks', topology=''), list_routes(scope=''), route_stats(), save_legacy_snapshot(task_id, task_proto, owner_port, scope='', observed_at=None, provenance='own_list_tasks'), get_legacy_snapshot(task_id, scope=''), set_maintenance(bool), maintenance_enabled(). Constructor defaults maintenance to true. Ownership reassignment/conflicting topology raises RouteConflict. LegacySnapshot exposes task_id, owner_port, task_proto, observed_at, provenance and a freshly decoded task property.

Only trusted original SDK owner scope is used: context.user.user_name (anonymous is empty string), domain-hashed at rest. Caller metadata.from/contextId is not an owner credential. Router inventory import must use the same trusted anonymous/authenticated scope as the original call. Snapshot storage does not migrate legacy task ownership to the new engine.

## Verified legacy discovery contract

Installed native JSON-RPC supports `ListTasks` with header `A2A-Version: 1.0`; historical `tasks/list` is not supported. For inventory use pageSize 100, historyLength 0, includeArtifacts false and honor nextPageToken. Full private snapshots omit historyLength and use includeArtifacts true. The handler invokes its own versioned store.list; these methods carry no referenced task ID so current old FrontEdge handles them locally rather than proxying unknown task IDs. Owner port therefore has direct provenance. Explicit overlapping task IDs across owners must be rejected by registry CAS.

DefaultRequestHandler TaskNotFound is JSON-RPC -32001; HTTP 404, transport error, 503, timeout or authorization failure is not absence. If ListTasks cannot establish an owner, a bounded ascending GetTask probe over original fixed ports can use first success only after every lower port returned formal TaskNotFound in the same trusted scope. Downward proxy topology and no concurrent legacy-store mutation remain assumptions; a task body must carry the requested exact ID, and lower-port recheck can detect some races. A higher hidden duplicate cannot be excluded by a proxy 200 alone. Parent router owns deadlines, rate limits, negative caching and uncertain outcomes, not this store.

Transport metrics and inspected decision-trace field names contain no task/context/port ownership linkage; sale schema has no task/context/port fields. No raw records were exported. Parent owns all actual legacy HTTP inventory reads.

## Restore boundaries

Task protobuf preserves status, artifacts, history, metadata and unknown fields without truncation. Restored WORKING means historical working, not an instruction to resume/reissue a financial operation. No task execution is triggered by opening the database. Read-only legacy snapshots require observed-at/stale disclosure; they do not prove fresh stock, settlement, consent, wallet rights or successful delivery. Legacy SendMessage continues directly to its original owner process.

Original agent_kit keeps a separate in-memory histories closure, and current PublicContinuity keeps an independent TTL hint cache. TaskStore durability alone does not restore those. PublicContinuity stores only up to three SKU/grade/preferred_price hints under task/context hash, with 300-second TTL, no consent/identity/financial authority. Parent owns a separate durable continuity subclass and SDK host injection; existing in-memory stores are untouched. New stable router/engine architecture can avoid a new listener/unit for each release, but engine restart additionally requires inflight drain and explicit uncertainty handling, not only persisted tasks.

## Validation

Eleven task-state tests passed, including fresh-interpreter restart, original SDK list differential, trusted-scope separation, atomic conflict rollback, concurrent route CAS, legacy snapshot restart, private file/link protection and maintenance persistence. All logs/task payloads/DBs are synthetic under temporary OP/runtime directories. No original keys or raw customer data were read. Tests do not prove operational migration, live ownership inventory completeness or financial recovery.

## Durable public hints added before deployment

`get_public_facts(key: bytes32, now: float)` and `save_public_facts(key, facts, now, ttl=300, limit=300)` persist a separate public_facts table. Explicit epoch seconds must come from the HOST wall clock. A backward clock before created_at or time at/after expires_at makes a hint unavailable. Retention is bounded to 300 seconds/300 records and three exact public fields per record; no consent, user identity, wallet rights or price approval is stored. The existing continuity wrapper still validates business SKU rules and rechecks fresh facts before any financial decision. This is a new predeployment schema, not a migration of any live state database.

Run with the operator virtual environment: `python -I -B tests/host_task_state/test_task_state.py`. Only synthetic temporary databases are created under operator/runtime.

`known_owner_response` is HOST-attested provenance only: a parsed Task protobuf returned by the router's fixed, already-verified native owner endpoint on SendMessage/GetTask. It is never read from incoming customer JSON. It can refresh the same owner's snapshot or bind a new task ID explicitly returned by that backend, and cannot reassign an existing task to another owner. Parent router validates response identity/call association.

## Optional common HOST engine integration

`front.capture_sdk_app(..., task_store=SQLiteTaskStore(db))` injects the original native TaskStore API during assembly and restores the SDK constructor immediately, even after failure. `run_front_edge.assemble(..., host_state_db=path, persistent_engine=True)` uses the shared private database for native tasks, route/current commit, and public-only continuity. In isolated mode the path must be beneath the same fixture root as agent/Mind/app/Toolbox, with empty tool credentials. `edge.loaded_broker` explicitly exposes the loaded broker to isolated QA; no sys.modules lookup is needed.

Materialized immutable front folders must contain `task_state.py` and `durable_public_continuity.py` alongside the front sources and include them in the pinned manifest. Source-tree assembly resolves those two from the parent source directory. The durable wrapper calls the actual original PublicContinuity validator and sanitizer; it does not broaden valid SKU/grade/price, consent or authorization rules. Epoch wall-clock TTL is used for restart safety, with backward-clock hints unavailable.

CLI `--host-state-db PATH --persistent-engine` selects stable engine mode; existing default mode is unchanged. The persistent engine never proxies unknown tasks: the flat router owns task-to-endpoint routing. Only the original card GET remains proxied. The previous admission file is unused in this mode; shared maintenance gates Send/stream/Cancel while GetTask/ListTasks remain readable. No new listener or service is started by these tests.

Run `python -I -B tests/host_task_state/test_task_integration.py` for four synthetic composition checks. The first attempt had one mock lifespan failure (not a runtime business failure); its safe result is preserved under runtime/task-state-20261128-audit/INTEGRATION-FIRST-HARNESS-FAILURE.json. The fixture added a standard lifespan handshake, and final4/4 plus original front protocol5/5 passed. Full original SDK ASGI/public behavior remains a separate parent/QA check before any deployment.

`transport_route(task_id)` returns the only distinct destination across trusted scopes, or raises RouteConflict on disagreement. This gives transport location only; the original native backend remains responsible for authentication. Snapshot fallback must not bypass that scope boundary.
