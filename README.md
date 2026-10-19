# Codex Token Saver

A Windows tray app that puts local coding tools, compression controls and honest
activity measurements alongside coding agents. Use native Codex with your existing
account and model, or connect Claude Code, Gemini CLI, OpenCode, Cursor, VS Code,
Cline, Kilo and other stdio MCP clients. OpenCodex is not required.

**Preview software.** Clean-install CI and benchmark evidence are provided with
builds. A stable release requires the desktop/reboot checks in the
[release checklist](docs/RELEASE-CHECKLIST.md). No fixed token or quota reduction is promised.
See [qualification status and evidence](docs/RELEASE-STATUS.md) before installing a candidate.

## Install

Windows x64 only; no administrator access or global Python/Node installation is
required. Download the ZIP and checksum from
[Releases](https://github.com/patrickstrauss/Codex-Token-Saver/releases), verify,
fully extract, close Codex and run **Install.cmd**. Until a release is published,
[Windows package artifacts](https://github.com/patrickstrauss/Codex-Token-Saver/actions/workflows/windows-package.yml)
are development builds. Never run an installer directly inside a ZIP.

Open **Codex Token Saver** from the Start menu. Its dashboard is local at
`http://127.0.0.1:8095`. Enable desired tools in **Toolkit** and review the shared
command hook in Codex Settings. Optional integrations start off. Request compression
requires separate setup and explicit activation; installation preserves routing,
model, reasoning choices and authentication.

Read [install/update/uninstall](docs/INSTALL.md) for requirements, download checks,
CoreOnly installs, recovery and limitations. Choose **Uninstall** in Windows
Installed apps or run **Uninstall-Token-Saver.cmd**. It restores owned integrations
and preserves local data in a dated backup. A restart can be required to release
active workers; it never forces Codex or Windows to close.

For other agents, run `Install.ps1 -Harness standalone` and open **Toolkit >
Coding clients**. Existing Codex installations can add clients without reinstalling.
See [client setup and capability limits](docs/CODING-CLIENTS.md). Local MCP tools
are shared; other clients' automatic hooks and model-request compression are not
installed. External authenticated sessions still require live qualification.

## Included tools

| Tool | Purpose |
|---|---|
| RTK | Reduce supported terminal command output; automatic hook has a fast path |
| Headroom | Compress eligible local file/output and optionally model-request content; exact local retrieval remains available |
| Serena | Navigate named definitions and references in code |
| ast-grep | Search code structure with typed syntax patterns |
| Playwright CLI | Browser automation; Electron renderer use needs an available CDP endpoint |
| Laya | Route explicit bundle tool requests to enabled components; automatic compression stays fast |

Tools are independently controlled. “Configured” describes registration, not proof
that an existing chat loaded or used a tool. Browser/search activity counts are not
token savings. The app does not replace Codex's model selection or general tool
selection. See [using the bundle](docs/USING-BUNDLE.md),
[CLI tools](docs/CLI-TOOLS.md), and [Laya routing](docs/LAYA-ROUTER.md).

## Does it help?

**The current full configuration increased token usage in the completed coding benchmark.**
Across two repetitions of five synthetic tasks, native and bundle each passed all
10 attempts. Explicit tools, automatic Headroom request compression and the reviewed
command hook were enabled in the bundle arm.

| Overall measurement | Native Codex | With bundle | Bundle change |
|---|---:|---:|---:|
| Input + output tokens, including cached input | 404,141 | 690,526 | **+70.9%** |
| Uncached input + output tokens | 175,533 | 221,534 | **+26.2%** |
| Passed attempts | 10/10 | 10/10 | |

The current configuration **fails its token-reduction objective on this workload**.
These are repeated small tasks on one laptop, not ten independent real-world
workloads. No account quota or billing savings were measured. See the
[overall effectiveness report](docs/benchmarks/effectiveness-windows.md), raw data,
frozen tasks and [per-run charts](docs/benchmarks/overall-windows.md).

The earlier [explicit-tool pilot](docs/benchmarks/coding-windows.md) is separate:
it also found overhead, but excluded automatic paths and passed only 4/5 strict
checks per arm. It is not pooled with the full-configuration results.

The [offline benchmark](docs/benchmarks/offline-windows.md) measures individual
tool output, including reductions, latency, a small-file expansion and retrieval
costs. Those local reductions do not establish a net end-to-end benefit.

Savings depend on workload. Local counts are estimates, layers can overlap, and
retrieval can erase savings. Never add RTK/local/request estimates together or
present them as measured ChatGPT quota savings. The [methodology](docs/BENCHMARK.md)
includes reproducible runners, failed diagnostic pilots and the remaining limits.

The Headroom request counter shows a rolling **last 24 hours**, across local
midnight. It uses the token-only event ledger, never substitutes lifetime totals,
and visibly marks partial coverage. The dashboard streams at most 32 MiB per
snapshot to bound memory and I/O; it does not delete or rewrite savings history.

## Privacy, development and licensing

Compression caches can contain source files and command output. Keep loopback
services local and redact diagnostics before sharing. Read [security/privacy](SECURITY.md).
The source package excludes runtime caches, personal histories, downloaded models
and credentials. Dependencies are pinned with hashes; updates are compatibility
checked before switching. Library updates and app source updates are separate.

Original project code is [MIT licensed](LICENSE). Upstream components retain their
licenses, including Serena 2's GPL-3.0-or-later application license. See
[third-party notices](THIRD-PARTY-NOTICES.md) before redistributing runtimes.
[Contributions](CONTRIBUTING.md) are welcome. This is an independent project and
is not affiliated with or endorsed by OpenAI or the included tools' authors.
