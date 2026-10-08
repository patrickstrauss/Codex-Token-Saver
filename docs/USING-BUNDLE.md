# Using the bundle

**Browser automation (Playwright CLI)** and **Structural code search (ast-grep)** are included in full installations. Enable each under **Your toolkit**; reload Codex guidance when convenient. Their activity counters measure tool calls, not saved tokens. See [examples, Electron limits, and RTK command scope](CLI-TOOLS.md).

**Bundle tool router (Laya)** is the main entry point for explicit bundle work. Natural-language `bundle_query` calls use the local classifier; structural requests with `pattern` + `language` and existing typed bundle MCP/CLI calls use validated routes without model startup. Structural matches preserve exact text/locations and default to 50 per page. Prefer them for call shapes and code syntax; use literal search for text and Serena for named definitions/references. Automatic compression and hooks remain fast. Reload MCP tools or restart Codex when convenient to load this upgrade in existing processes. See [routing examples and limits](LAYA-ROUTER.md).

Open **Codex Token Saver** from the Windows Start menu, click the **TS** tray icon, or visit [the local dashboard](http://127.0.0.1:8095/). The installed app lives in `%USERPROFILE%\CodexTokenSaver`; a Git checkout is separate source code.

## Choose the components

Use **Bundle controls** to change one component at a time. **On** is your saved choice. **Ready**, **Bypassed**, **Error**, and the last activity explain what is currently observed; installed software and readable history do not prove that a task is using it.

| Control | What it changes |
| --- | --- |
| RTK command filtering | On filters supported commands explicitly run through RTK. Off passes supported external commands through unchanged. RTK-only transformation commands are rejected while Off; administrative commands remain available. Ordinary PowerShell scripts are not automatically rewritten into RTK commands. |
| Headroom local output | Checks eligible local files and command output. Off keeps original output and disables the extra local filtering of RTK results. Existing original-content retrieval remains available. This switch is independent of RTK. |
| Headroom request compression | Uses the existing managed Enable/Pause controller. Off restores the owned direct-routing setting. Already-open connections can retain their previous route until closed; restart Codex when convenient after changing it. |
| Serena symbol navigation | Offers four read-only navigation tools. A project must be selected explicitly. Off blocks new calls in already-loaded tasks; in-flight reads may finish. Idle language-server processes may remain until Codex reloads them. |
| Playwright CLI | Allows browser automation through named CLI sessions. |
| ast-grep | Allows structural code searches with exact matched text and locations. |
| Laya router | Routes explicit bundle work and classifies natural-language requests locally on CPU. Automatic Headroom/RTK hooks retain their fast paths. |

Missing runtimes have unavailable controls and an explanation. Enabling one library does not silently enable its dependencies. After installing this update, restart Codex once: existing file-tool processes need to load the new controls, and newly registered tools need discovery. Existing tasks can then be resumed. Later preference changes are checked on each new tool call by the updated wrappers.

For unavailable request compression, run **Setup-Request-Compression.cmd** from the latest extracted deployment package. It downloads and validates the local compressor while preserving Codex's current connection. After success, turn the dashboard control On and restart Codex once. For an earlier team installation showing RTK history errors or missing local-tool status, use **Repair-Team-Setup.cmd** from that package and restart the dashboard. See the [team setup and repair guide](TEAM-INSTALL.md).

## Read the activity

**Recent bundle activity** contains new, bounded records grouped by task when a caller UUID is available. Diagnostic checks and informational commands are separate from operations. Unknown callers stay unknown; historical counters and request-savings totals are not assigned to a task retroactively. The RTK hook coverage panel reports observed rewrites and skips, not completed commands or quota savings.

RTK defaults to **Today**. Select **7 days** or **Lifetime** to compare periods. The dashboard retains the lifetime figure, latest command time, collector time, and large single-record contributions. A high lifetime reduction can come from an old large output while current tasks rarely invoke RTK.

RTK, Headroom local output, and Headroom model-request counters measure different stages. They can overlap and are never added together. Local retrieval costs can lower net savings. Serena reports observed navigation calls, without inventing a token-saving estimate. The dashboard does not measure your Codex account quota or bill.

## Update libraries

Expand **Library updates**, click **Check for updates**, and select an installed runtime: **Headroom**, **RTK**, **Serena**, or **Laya**. Each candidate is staged and checked before its runtime selection changes; **Rollback** returns to the retained previous selection when available. Headroom also offers **Refresh dependencies** when appropriate. Laya uses `laya/runtime.json` to select its staged runtime and preserves its pinned classifier model manifest and revision.

Checks and installs are manual. Existing MCP processes may need a Codex reload after a runtime update. New command workers use the selected runtime. Running work must finish before incompatible runtime operations proceed.

## If something stops working

The Windows dashboard starts independently of the Codex or terminal process that launches it. Closing that starter should not stop the dashboard. If `http://127.0.0.1:8095/` refuses a connection, click the Token Saver tray icon to check/start the service, then refresh the page; the tray also retries automatically once a minute.

The native launcher also recovers an unexpectedly failed tray helper: it waits two seconds and retries up to twice, without opening extra browser tabs. Normal Quit and duplicate-instance exits are respected. Repeated failures stop the retry loop and are recorded in `logs/tray-launcher.log`, along with helper PIDs and exit codes. Open the app again after correcting a persistent failure. This recovery supplements the Windows startup task; it does not establish the cause of an earlier unlogged shutdown.

Check the affected component's status, latest activity and error. No recent use can mean the current workload did not invoke that component. A selected but bypassed request compressor is a different condition from a broken RTK launcher.

Use the dashboard controls for routine changes. If the local request relay prevents Codex from connecting, run `Restore-Codex-Direct.ps1` from the installed bundle and restart Codex. Preserve state and backup directories during repairs. Compression is lossy; exact-output bypasses, original retrieval and task-level validation are required whenever omitted details could change the result.
