# OpenCodex candidate source

The token-saver-v2.64.0.patch file targets OpenCodex v2.64.0, commit
4cb43cb0a8c6b60318cf0d63ffa8e57fd18407b2. Candidate source commit:
d51b66a104f5cf200058c253038d2407768779bc.

Text-only arrays and custom-tool outputs now reach compression; mixed-media and annotated blocks stay unchanged.

The patch adds optional outbound transforms, strict default-off configuration,
conditional extension commands, live persisted policy, validated runtime readiness,
focused tests and contract documentation. It does not select models or providers.
Windows packaged-app detection accepts Bun's encoded `%7EBUN` path, allowing
the dashboard to find its bundled GUI without an environment override.

Apply only to an isolated source checkout:

    git apply --check PATH_TO_PATCH/token-saver-v2.64.0.patch
    git apply PATH_TO_PATCH/token-saver-v2.64.0.patch

Use the pinned Bun lock, focused tests, and the bundle's offline witness.
The wire/pipeline tests require the isolated service URL from that witness and otherwise
skip. They do not select a real provider.

A compiled Windows x64 candidate and GUI now accompany the bundle's combined upgrade
folder. This is a local candidate, not an official upstream release. See
[installation steps](../OPENCODEX-INTEGRATION.md) and [validation](VALIDATION.md).

The commands are `ocx config token-saver-state --json` and
`ocx config token-saver-set <expected-sha256> <json-or-null> --json`.
Only the extension subtree is returned. Receipts detect outside edits.
The bundle's `opencodex_control.py` exposes status, enable, pause and disconnect.
Pause and disconnect preserve OpenCodex routing and exact retrieval.

Upstream: https://github.com/lidge-jun/opencodex
OpenCodex is MIT-licensed; the candidate distribution retains its LICENSE.
