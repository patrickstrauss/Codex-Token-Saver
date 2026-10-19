# Release qualification status

Reviewed 19 October 2026. This project is prepared as a **Windows x64 preview**.
Native Codex is the primary integration; OpenCodex is optional. Original project
code uses MIT; dependencies retain their upstream licenses.

## Candidate evidence

The [Windows package workflow](https://github.com/patrickstrauss/Codex-Token-Saver/actions/workflows/windows-package.yml)
tests full and CoreOnly packages on Windows Server 2025/2022. A successful run
qualifies only its exact commit. `release-provenance.json` records the candidate's
commit, version, workflow and limits; use it as the authority.

| Evidence | Scope |
|---|---|
| ZIP and `.sha256` | Source distributable and checksum; no installed models/caches/history |
| `package-audit.json` | Manifest hashes, allowed files, private-state exclusions and document links |
| `security-history.json`, `security-package.json` | Pinned Gitleaks scans; credential values/snippets omitted |
| `lifecycle-result.json` | Isolated source upgrade, injected rollback and owned integration removal |
| Successful workflow jobs | Install, repair, rerun, backup-preserving uninstall and reinstall |
| `coding-clients.json` | Serializer/connector preservation, conflict and removal contracts |
| `mcp-protocol.json` | Nine adapter initializations/exact reads; Laya and Serena tool discovery |
| `runtime-inventory.json` | Installed dependency versions on that runner |
| `performance-benchmark.json` | Synthetic offline fact/retrieval/latency measurements |

CoreOnly omits Laya's managed model runtime. Protocol discovery/exact reading does
not qualify model-based routing. Use the full installation for routed explicit tools.

## Remaining gates

- **Windows 11 desktop/reboot acceptance is paused.** Server CI does not replace
  that manual test. No VM is recreated for this release work.
- **External clients need live qualification.** All nine serializers and shared
  server protocols are tested; authenticated client UI/trust behavior is unverified.
  See [client setup](CODING-CLIENTS.md).
- **End-to-end coding savings are unmeasured.** Offline results include negative
  results. The native context pilot failed before reporting usage and provides no
  quality/quota result. See [benchmark scope](BENCHMARK.md).
- **Packages are unsigned.** Checksums do not establish publisher identity.
- **Public publication requires owner review.** Creating a draft does not publish
  the repository/release. Review the [checklist](RELEASE-CHECKLIST.md), notices and
  candidate evidence before changing visibility.

These release-tooling changes require no laptop restart, authentication reset or
model-route change. Installation/runtime updates have their own documented
close/restart requirements in [installation guidance](INSTALL.md).
