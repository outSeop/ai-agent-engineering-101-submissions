# Card reselection maintenance (external host infrastructure)

The existing pinned same-choice keeper runs first. Only `requires_class_selection` allows a fresh official classroom Mind selection through genuine stage1; a new current observation is checked before genuine apply4. Existing production apply3 and shared tool sources stay unchanged. New authority/proof and current-head CAS preserve card history, policies, name and skills. The host owns canonical regular-file/private-directory checks; source apply4 alone does not guarantee them.

This bundle contains genuine apply4 original bytes, not a new forge. Development authorship is the actual R4 official Mind using the requested Codex CLI provider. Provider metadata does not independently report an upstream model ID. Operational selection uses `llm=market`. The other Python files are externally authored host plumbing, not native business tools.

## Root-coordinated installation

Copy this exact frozen directory to `r4-operator/deploy/native_card_reselection_v1`. Preserve the existing `deploy/native_card_keeper_v1` and its pinned manifest. Root changes only the existing card keeper service entrypoint; no main restart is needed. Use the operator venv Python:

```
<venv>/bin/python -I -B <operator>/deploy/native_card_reselection_v1/card_maintenance.py --operator <operator> --allow-maintenance --failure-cooldown 600
```

Without `--allow-maintenance`, validation is dry and invokes no producer, Model or card write. Keep the existing 60-second timer; failed/unknown reselection starts a 600-second cooldown before calling the Model, including killed/unknown attempts. Same-choice refresh continues during cooldown. An overlapping wrapper is busy; recent foreground customer activity defers reselection. Missing/malformed or >4MiB transport metrics also defer. This is a bounded recent-activity detector, not a promise about arbitrarily old financial requests.

Do not give the Model wallet/identity authority. Preserve the existing original SDK7 and keeper source verification. The publication lock, original/current head CAS and fresh selected-facts checks remain mandatory. Do not kill a commit: service timeout should accommodate the existing keeper and one bounded selection cycle (180 seconds recommended); do not add overlapping callers.

## Evidence

`qa/test_maintenance.py` contains eight synthetic mock cases, with only the import path made relative. All eight passed; they do not prove real Model behavior. The parent separately ran the exact reselection host in shadow and live with classroom Mind, then verified public card equality. The auditor did not run that live operation. `qa/actual-legacy-keeper-compatibility.json` is a read-only derived proof that the original production keeper/apply3 subsequently refreshed the new apply4 event successfully, preserving selections and non-description metadata.

The full original comparison is untrusted user data with a 64KiB bound. Original SDK observation text may truncate; the separately appended original user data does not. Over-limit data holds instead of silently truncating. Production DB/wallet/inventory are not copied into the host job. No new finance or market-write privileges were added.

Actual parent live event: e8e51e2f64ff4d6591bca758cdb0b8a0bb0da068016cc7e2b15030cef8e51a68. Original keeper follow-up event: 6471dd3282a472fab70a54e6c0ded566b5ce3c73a66126bf8f431ea40344d5ef. No raw inventory, customer data, wallet or reasoning is exported here. Failed development/QA records remain at original private paths.
