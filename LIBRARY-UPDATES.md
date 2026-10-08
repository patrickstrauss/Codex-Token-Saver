# Updating the token-saving libraries

Open **Codex Token Saver** from the Start menu or tray, then expand **Library updates** in the [local dashboard](http://127.0.0.1:8095/).

1. Choose **Check for updates** to look up stable Headroom, RTK, Serena and Laya releases.
2. Choose **Update** for a newer release. When Headroom, Serena or Laya's core version is current, **Refresh dependencies** rebuilds it with the latest compatible Python dependencies.
3. Follow the progress message. Installation, dependency checks, compression, exact recovery, and compatibility validation finish before activation. Keep the background app running; the dashboard page can be closed.
4. Use **Rollback** to return a component to its retained previous version if needed.

Version checks and installations run only when requested. Current/latest columns refer to the selected component's version; they do not establish that every transitive Python dependency is current. A dependency refresh can keep the same Headroom core version while changing its supporting libraries.

## What the updater manages

**Headroom desktop:** the Headroom package and its Python dependency environment. Each update is installed under `updates\runtimes`, tested separately, and selected through `updates\active.json`. The original `headroom\.venv` remains the baseline fallback. Fresh command workers use the selected libraries. File tools already running inside Codex keep their loaded libraries; restart Codex when convenient to refresh those processes. Existing tasks remain usable.

When the desktop request integration is installed, Headroom updates and rollbacks also validate the candidate's request-backend configuration and protected model, reasoning, and text settings. If the bundled model is present, validation includes offline Kompress compression and exact-original recovery. A failed check leaves the previous runtime selected. These checks do not replace the separate HTTP/WebSocket integration validation.

Headroom 0.40.0 removed the legacy `effort_router` profile field and `effort_router_enabled` shaper field. The bundle adapter handles both older and newer SDKs while keeping user/system input compression and output/model/effort steering disabled. Older bundle adapters stop this update at desktop-proxy validation; update the bundle adapter before retrying rather than bypassing that check. Missing required input-protection capabilities still fail validation. The October 7, 2026 compatibility fix passed all seven updater phases with 0.40.0, including the existing local model and exact-original recovery, while retaining 0.37.0 for rollback.

An already-running request backend retains its current libraries. After active tasks finish, restart the **Codex Token Saver Proxy** task in Windows Task Scheduler, or sign out and back in, to load its selected runtime. Restarting Codex alone refreshes its file tools; it does not restart the independent request backend. The updater does not interrupt running proxy connections automatically.

**RTK:** the underlying `tools\rtk.exe`, downloaded from the official RTK GitHub release with its SHA-256 checksum verified. The custom `bin\rtk.exe` launcher remains in place. If Windows reports the binary is busy, the update keeps the current binary and asks you to retry after the command finishes.

**Serena:** staged Python runtimes must pass imports and read-only navigation-schema checks before activation. Existing MCP processes keep their loaded runtime until Codex reloads them.

**Laya:** staged Python runtimes must pass classifier compatibility checks before activation through `laya/runtime.json`. Rollback restores the retained prior selection. Updates preserve the classifier's pinned model manifest and revision; the shared worker loads the selected runtime when it next starts.

The October 8, 2026 bundle targets Headroom **0.40.0**, RTK **0.51.0**, Serena **1.7.0** and Laya **0.4.0**. Fresh installation also includes Playwright CLI **0.1.22**, ast-grep **0.45.3**, uv **0.12.23**, Node **24.21.0 LTS** and Python **3.13.16**, the latest release in the existing supported Python branch. Exact downloads and dependency hashes are recorded in the packaging manifests and locks.

The custom dashboard, tray, and integration code are maintained separately. This updater does not replace them with the upstream dashboard or change the experimental CLI proxy environment. Savings history, exact-original cache data, Codex settings, model, reasoning, authentication, and hook trust are preserved. Headroom's ONNX Kompress model and Laya's CPU classifier remain separate from native compaction research. Existing user models and saved summaries are retained.

## Recovery

Failed downloads, missing compatible Windows packages, or failed validation leave the previous version selected. The progress area reports the failure; retry the explicit action after resolving it. Interrupted staging remains separate from active libraries. The updater allows one operation at a time across app instances.

Rollback uses the retained prior runtime or verified RTK backup. It changes the selected library version, not your saved activity. A Headroom rollback also applies to fresh tool processes; already-running file tools keep their loaded version until Codex restarts.

The updater uses fixed official PyPI and RTK GitHub sources. It accepts only the listed components and actions from the dashboard. Local mutation requests require the dashboard's origin and page token; opening or refreshing the page does not start an installation.

The bundled `tools\uv.exe` installs candidate Python environments. Its version, hash, and license information are recorded in `updates\uv-tool.json` and `tools\licenses\uv`.
