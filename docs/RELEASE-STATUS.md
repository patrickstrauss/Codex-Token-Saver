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
- **The current configuration failed its token-reduction objective in testing.**
  Two full-configuration repetitions of five tasks passed 10/10 attempts per arm,
  but the bundle used 70.9% more input-plus-output tokens and 26.2% more uncached
  input-plus-output tokens. Automatic compression and the reviewed hook were
  enabled. Browser tasks and external clients remain excluded. This does not
  establish results for larger workloads or account quota savings. See the
  [overall evidence](benchmarks/effectiveness-windows.md) and [methodology](BENCHMARK.md).
- **Packages are unsigned.** Checksums do not establish publisher identity.
- **The owner made the repository public.** Preview/stable release publication
  still requires review of the [checklist](RELEASE-CHECKLIST.md), notices and exact
  candidate evidence. A public repository does not qualify a release.

These release-tooling changes require no laptop restart, authentication reset or
model-route change. Installation/runtime updates have their own documented
close/restart requirements in [installation guidance](INSTALL.md).
