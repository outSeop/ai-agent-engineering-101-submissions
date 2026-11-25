# Price context bootstrap — external filesystem binding

The unchanged price policy module uses a relative configuration path. Snapshot/card services launched from the operator directory could therefore miss the registered shop's policy, while the publisher subprocess in the shop directory used it. This host verifies the exact original module bytes and binds only `price_policy.POLICY_PATH` to the registered shop's absolute config path before executing either of two unchanged fixed entrypoints. The pricing formulas, config contents, target files, cwd and original target `__file__` are preserved.

Install this exact bundle at operator/deploy/price_context_runtime_v1. Root retargets only the two existing service commands; retain all their original arguments:

```
<venv>/bin/python -I -B <bundle>/price_context_bootstrap.py catalogue -- <original catalogue args>
<venv>/bin/python -I -B <bundle>/price_context_bootstrap.py card -- <original card args>
```

`--check catalogue` or `--check card` verifies sources and binding without executing a target. Both real checks passed. An arbitrary target or operator, changed manifest/dependency, unrelated preloaded price module, or symlink config fails closed. A missing config retains the original policy module's fail-closed behavior.

Exact target manifests: catalogue818e94a3c7c845ed7b3b93afe41c0883e6eecda24b0b0bf960f5d87dc1efa094; card296ed9c61e69e797fe74b1219d7a267a3e982ce743b1876bcabce8867240c960. Source price_policy6e101702c38d47b3f2c68c860dc0198fd1d7557e311c2753dc4a71fed127118f. These originals remain untouched. No policy data file is copied to this bundle. Only source code is read for source verification. The check path reads the established config file to verify regular-file identity, without recording its contents.

Eight narrow tests use synthetic policy files in temporary roots and the original source bytes. They reproduce a different policy being found in a wrong cwd, then confirm the bound registered config is used while both data files and cwd stay unchanged. Target runpy is mocked in execution tests; all real checks leave target code unexecuted. No DB, market, Model, wallet or service operation was performed by this task. This is host infrastructure, not an agent-forged business tool.
