# Public catalogue validation tools

These are externally authored, read-only host QA tools. They do not author the forged catalogue or implement purchase/refund decisions. The market tool is the exact original `public_catalogue` v2 recorded in the release manifest.

Run `python -B qa_public_catalogue_sdk_asgi_host.py --runtime-bundle ../public_catalogue_runtime_v2 --runtime-manifest-sha e83ca0ac4493d7de4d50190f0bbadbb8f89fe89e74b82038dec30d82159e24db --output <fresh-private-directory>`. This uses synthetic inputs and a Mock model. The output must be private; raw SDK logs are not publication artifacts.

`public_catalogue_class_canary_host.py` prepares a fresh isolated session by default. `--run-class` explicitly enables the existing classroom-model credential. It accepts only a fresh `r4-operator/runtime/public-catalogue-class-canary-*` session and owned 0400 public snapshot, verifies SDK7 and the release, gives the generated catalogue no wallet/token/address capability, and blocks all financial execution. Read `--help` for required arguments. Use `-B` to avoid writing bytecode into immutable inputs.

Actual class sessions and the 7-case SDK test are distinct. Publication summaries are in `evidence/20261125-public-catalogue/host-class-validation/`; actual public transport probes are separately recorded under public deployment validation. The narrowly accepted timeout fallback is not a general natural-language purchase/refund fallback.
