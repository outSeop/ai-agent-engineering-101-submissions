# Public catalogue host v3b review leaf

This is a partial source-only host review evidence package, not a complete deployment bundle or live experiment. Full frozen candidate path and exact21-file manifest are in SAFE_SUMMARY and host-source/MANIFEST. Only the two changed external host files plus launcher are copied here; genuine public_catalogue4 source is unchanged and not relabelled as host-authored. Existing public evidence is untouched.

20 narrow Mock regressions passed. Real Model/catalogue/legacy execution and service/wallet/DB calls were all stubbed. Root performs real classroom canary and public endpoint validation separately. Original safe private result/log/diff/test source is copied byte-identically. No raw real customer trace, forum input, ledger, key, wallet or financial amount is published.

Reproduction uses an existing operator checkout and full frozen candidate, with its virtualenv dependencies:

    python reproduce_control_flow.py --operator /path/to/r4-operator --stage /path/to/public_catalogue_runtime_v3b --output /tmp/public-v3b-QA

The adapter changes only the two QA import paths in a temporary copy, disables bytecode writes, and copies synthetic result JSON to the requested output. Original test source is unchanged. The source-only review is external infrastructure work; it does not add product-selection logic, rewrite genuine tools, broaden financial rights or prove actual conversion. Runtime promotion and any later public results are outside this leaf.
