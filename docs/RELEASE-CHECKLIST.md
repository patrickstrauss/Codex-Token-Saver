# Release acceptance

Every candidate must pass the Windows package workflow for its exact commit.
Keep its source ZIP, checksum and JSON evidence together. See
[qualification status](RELEASE-STATUS.md) for evidence scope and remaining work.

Client adapters are qualified separately from automatic compression and hooks.
Before advertising live compatibility with an external client, record its version,
stdio initialization/tool discovery, a real tool call, trust/reload behavior and
disconnect/uninstall preservation. JSON format tests alone are insufficient.

## Automated gates required for every candidate

The workflow enforces these checks; a previous green run does not qualify a newer commit.

- Full Git history and final package scans pass with redacted location-only reports.
- ZIP manifest hashes, allowed file set, private-state exclusions and packaged Markdown links pass audit.
- Both Windows Server jobs pass: full and CoreOnly install, artifact repair and repeated install.
- Invalid manifests/checksums, traversal, duplicate-case paths and local source edits refuse safely.
- Isolated Codex configuration/authentication and unrelated settings remain intact.
- Source upgrade succeeds; injected failure restores added, removed and changed files.
- Uninstall restores owned integrations, retains a backup and permits clean reinstall.
- Adapter format, conflict, rollback and removal tests pass. Shared stdio initialization,
  discovery and exact Headroom reads pass for all nine serializers.
- Offline facts and exact retrieval pass; latency, expansions and retrieval costs are published.
- Draft assets include checksum, inventory, lifecycle, client, protocol, audit,
  security and provenance reports identifying the exact commit/workflow.

## Manual gates before a stable public release

- [x] Owner selects MIT for original project code. Third-party licenses remain separate.
- [ ] Owner reviews notices, release contents and public repository/release visibility.
- [ ] Clean Windows 11 x64 standard-user VM: download/extract/install, trust hook, open tray/dashboard and use tools.
- [ ] VM reboot/login: singleton tray/dashboard/proxy ownership, normal native Codex connectivity.
- [ ] VM uninstall while active asks for close/restart; after restart it completes and native Codex resumes.
- [ ] VM reinstall succeeds; backup is retained; uninstall/refusal paths preserve unrelated tasks/shortcuts.
- [ ] Owner reviews the preview draft and its exact test evidence before publication.

Current public support target is Windows 11 x64. CI uses Windows Server images;
Windows 10, ARM64, macOS and Linux are not qualified. A skipped or unperformed gate
must remain unchecked. Until desktop/reboot qualification passes, label a release
**preview**, not stable or “fully tested.” Code signing is not implemented.

Windows 11 VM work is **paused**. Do not recreate the VM as part of release automation.

## Gates for additional claims

- [ ] Live external-client support: record exact client version, authenticated tool call,
  trust/reload behavior and disconnect/uninstall preservation. Shared MCP tests do not
  install or log into those clients.
- [ ] End-to-end coding quality/usage: finish the
  [paired study](BENCHMARK.md#native-codex-ab-study-not-yet-measured).
  A failed pilot or local avoided-token estimate does not establish quota savings.
