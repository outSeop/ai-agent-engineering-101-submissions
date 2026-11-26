# Front-only edge host — staged, not installed

Purpose: keep oldmain/cloudflared/registeredURI/worker and pending checkout intact while a new listener can serve new conversations. No join, Mind.loop, stock/forum loop or tunnel is created. No production source/DB/key/permission was changed by this preparation.

## Exact composition

`run_front_edge.py` requires both --edge-manifest-sha and --runtime-manifest-sha. It verifies its own original files before importing the exact front module or reading a key. It then verifiesSDK7, the candidate bundle and originaldispatcher/worker/refund source hashes. Use the original operator venv as user1000. Default is verification only; --serve explicitly starts127.0.0.1:18806.

It builds the original SDK managed app/Toolbox on the original shop root. The only real key is the existing shop key read in memory with Wallet.from_hex, not Wallet.load (which chmods). Original Signer grants only existing tool permissions; a2a_info is sign/sign_jwt, not pay. Read-only generated candidate tools still receive their own empty tokens/addresses+NoWallet. Original Model authentication stays in its private ctx. Existing worker-token is read on each POST; no copied key/token/env file is created. No buyer key or new wallet is needed.

An original SDK InMemoryTaskStore instance is captured only during single-threaded app assembly; its constructor symbol is immediately restored and SDKsource bytes stay unchanged. Native anonymous ServerCallContext is used to look up tasks, matching the current unauthenticated SDK HTTP app. New/knownedge tasks use the newapp. Unknownold taskId/GetTask/CancelTask goes to original127.0.0.1:18805 with source127.0.0.2, unchanged JSON bytes and query bytes. No rights, customername or raw history is promoted into identity. This does not migrate original taskstore; oldtasks retain the old pipeline. Edge's own store is still in memory and a lateredge restart loses that transport state; ledger rights remain unchanged. Future authenticated HTTP middleware would need a matching taskstore scope review.

GETcard proxies to originalbackend and adds x-r4-edge:r4-front-v1. Before everyPOST (including oldtask fallback), a cheap source.2 localcardGET must still show the startup registeredURL/name/role/wallet. Drift/unavailable returns503 before Model/financial/proxy. Full registry validation occurs only at startup. HTTPproxy never follows redirects/retries POST and only targets the fixed oldbackend; query_string is preserved. Tracecontainsroute/status/time/count only, no body/headers/token. A tracewrite failure never breaks a completed response.

## Budget semantics

V2 keeps strictone Model decision per newrequest, no formatrepair and no providerretry. Timeout supplied to originalModel is at most30seconds and remaining40second hostbudget minus5second reserve; max_tokens800. The original Broker class is subclassed only to set these budget kwargs (source/handle unchanged). The selected runtime must separately advertiseone finaldecision and1..3items; this package does not rewrite Modelmessages. Original SDK uses a daemon HTTP thread: this is a localwait cap, NOT cancellation of the upstream providerjob. Late results never become tool actions. It is not a harddeadline on an already-started original financial operation; do not cancel that operation. Invalid/late decisions use the runtime's verified readonlyfallback/hold. Oldtask proxies retain the original backend's behavior. Root must wire the genuinely forged prepared runtime after its separate QA.

Original main's customer_active is process-local and does not observe newedge requests. Thus old stock/forum and edge may overlap Model calls; cross-process serialization is NOT guaranteed. No fakeheartbeat, SIGSTOP or main sourcepatch was added. Existing DB atomics preserve financial concurrency; no extra background loop is started.

## Route and rollback template

`route_guard.py` is a root-review tool; it was tested with mocked commands only. No installation or rule was run by the author. It requires exact packagepin, originalMainPID and originalPublicURL. It checks originalDBpendingURLs, source/cardidentity, edgeheader and continuous10second18805 TCPidle (up to40seconds); keepalive default was independently read as5seconds. It then inserts exactlyone OUTPUT rule:

```
-t nat -I OUTPUT 1 -p tcp -s 127.0.0.1/32 -d 127.0.0.1/32 --dport 18805 -m owner --uid-owner 1000 -m comment --comment codex-r4-front-edge-v1 -j REDIRECT --to-ports 18806
```

The source.2 oldbackend proxy bypasses that source.1 rule, even with the sameUID. No otherport/chain/process is changed. Roothelper uses the explicit originaluser bus to readMainPID. --apply is explicit; default inspects. Afterinsertion it checks originalpendingURLagain and publicedgeheader/wallet. A failed publicprobe deletes exactlythat rule. --rollback uses the same fullspec with-D; it never flushes a chain or kills a connection/process. A duplicate matching rule is reported as incomplete rollback rather than removing unrelated entries. Installingiptables, applyingrule and any service start are root's finalreviewed actions, not this preparation.

NAT affects newflows; keepalive existingconnections may remain old. OriginalTCPidle was only briefly observed by the auditor, not the finalcontinuousdrain. Rootmust perform the fullguard atcutover and prove actualpublicpath by edgeheader+privateedge trace. Do not deleteconntrack/resetconnections. NATrules are not made persistent acrossWSLrestarts here. Edgeavailability/quickrollback matters because an unavailableedge can make originalSDKtunnelhealthprobes fail; existingmain is intentionally keptalive for rollback.

## Verification and limitations

NoWallet actualSDKASGI tests cover newtask/knowntask, unknownoldtask rawbodyproxy, GetTask fallback, cardproxy/marker, sizecap, querypreservation, identitydrift503, logfailure and Modelcap. ProxyHTTPtarget is mocked in these tests; a separate realGET with source127.0.0.2 to originalcard succeeded200. No realPOST was sent to oldmain. Routeunit tests mock every subprocess/HTTP/rule, including exactapply/delete and pendingURLblock. NoactualModel, sign, pay, DBwrite or serviceaction occurs in these tests.

The original registeredURL/pendingright protection remains a deploymentprecondition. Do not rewrite sales/JWTURLs, release old reservations or claim the new pipeline is live before publicpath proof. Genuine6 naturalrice/nuts classroom canary separately exposed emptycandidate regression; root has requested genuine7. This edgepackage does not approve that businessruntime.

## V2 calibration evidence

Three18secondwaits timedout locally. One30/40/800 calibration got actualJSON at14.45seconds but selected4items, violating render1..3. It proves providerresponse, not a valid execution or production success. Root explicitly chose30/40/800 for the next staged test and requested runtimeone-decision guidance. V1 stays frozen. No additional actualModel call is made by this staging. Routing marker/spec remaintransportv1 and are unchanged.

Publicationnote: historical failurebytes are unchanged; their v2artifact filenames use underscores to avoid an API-key regex falsely matching the substringsk- inside the wordtask-scope. V1/originalfailure filenames remain preserved. Actualcredential matching remains unchanged.
