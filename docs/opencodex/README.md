# OpenCodex source prototype

The token-saver-v2.64.0.patch file targets OpenCodex v2.64.0, commit
4cb43cb0a8c6b60318cf0d63ffa8e57fd18407b2.
It adds an optional transform consumer, a default-off strict configuration block,
the adapter-build hook, conditional extension commands, runtime capability publication,
focused tests and contract documentation. Current source commit: 4e13350.

Apply only to an isolated source checkout:

    git apply --check PATH_TO_PATCH/token-saver-v2.64.0.patch
    git apply PATH_TO_PATCH/token-saver-v2.64.0.patch

Use the pinned project's Bun dependency lock, run the focused Token Saver tests,
and run the bundle's offline witness. The two wire/pipeline tests are intentionally
skipped unless the witness starts its isolated service and supplies its fixture URL.
They never select a live provider.

This is an **unshipped prototype**, not an installer or an OpenCodex binary.
Full socket transport testing, complete route migration, release packaging and Windows
lifecycle qualification remain pending. See [the checkpoint](../OPENCODEX-COMPATIBILITY.md).

The source commands are `ocx config token-saver-state --json` and
`ocx config token-saver-set <expected-sha256> <json-or-null> --json`.
Only the extension subtree is returned. The bundle uses these with its own receipt;
direct edits after adoption are treated as conflicts. The bundle controller exposes
`status`, `enable`, `pause` and `disconnect` through `opencodex_control.py`.
Pause and disconnect preserve OpenCodex routing and the original-retrieval worker.

[Validation results](VALIDATION.md) and [offline witness](offline-witness.json) record
the tested scope and remaining qualification gaps.

Upstream: https://github.com/lidge-jun/opencodex
Upstream is MIT-licensed; retain its license when distributing a patched tree.
