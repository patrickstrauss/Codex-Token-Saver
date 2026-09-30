# Using the bundle

**Browser automation (Playwright CLI)** and **Structural code search (ast-grep)** are included in full installations. Enable each under **Your toolkit**; reload Codex guidance when convenient. Their activity counters measure tool calls, not saved tokens. See [examples, Electron limits, and RTK command scope](CLI-TOOLS.md).

**Bundle tool router (Laya)** adds the explicit `bundle_query` MCP tool. Calls to this tool go through local Laya before the bundle executes a validated sequence. Other Codex tools continue normally. Enable the card and reload MCP tools to discover it. See [routing examples and limits](LAYA-ROUTER.md).

Open **Codex Token Saver** from the Windows Start menu, click the **TS** tray icon, or visit [the local dashboard](http://127.0.0.1:8095/). The installed app lives in `%USERPROFILE%\CodexTokenSaver`; a Git checkout is separate source code.

## Choose the components

Use **Bundle controls** to change one component at a time. **On** is your saved choice. **Ready**, **Bypassed**, **Error**, and the last activity explain what is currently observed; installed software and readable history do not prove that a task is using it.

| Control | What it changes |
| --- | --- |
| RTK command filtering | On filters supported commands explicitly run through RTK. Off passes supported external commands through unchanged. RTK-only transformation commands are rejected while Off; administrative commands remain available. Ordinary PowerShell scripts are not automatically rewritten into RTK commands. |
| Headroom local output | Checks eligible local files and command output. Off keeps original output and disables the extra local filtering of RTK results. Existing original-content retrieval remains available. This switch is independent of RTK. |
| Headroom request compression | Uses the existing managed Enable/Pause controller. Off restores the owned direct-routing setting. Already-open connections can retain their previous route until closed; restart Codex when convenient after changing it. |
| Serena symbol navigation | Offers four read-only navigation tools. A project must be selected explicitly. Off blocks new calls in already-loaded tasks; in-flight reads may finish. Idle language-server processes may remain until Codex reloads them. |
| LangMem local summaries | Allows explicit local summary jobs. Off prevents new jobs; saved summaries remain readable. Requires llama.cpp to be On. |
| llama.cpp local inference | Allows the local model to load for a requested summary job. The model unloads afterward. Off prevents new jobs; use **Cancel running job** to stop work already started by the bundle. |

Missing runtimes have unavailable controls and an explanation. Enabling one library does not silently enable its dependencies. After installing this update, restart Codex once: existing file-tool processes need to load the new controls, and newly registered Serena and summary tools need discovery. Existing tasks can then be resumed. Later preference changes are checked on each new tool call by the updated wrappers.

For unavailable request compression, run **Setup-Request-Compression.cmd** from the latest extracted deployment package. It downloads and validates the local compressor while preserving Codex's current connection. After success, turn the dashboard control On and restart Codex once. For an earlier team installation showing RTK history errors or missing local-tool status, use **Repair-Team-Setup.cmd** from that package and restart the dashboard. See the [team setup and repair guide](TEAM-INSTALL.md).

## Read the activity

RTK defaults to **Today**. Select **7 days** or **Lifetime** to compare periods. The dashboard retains the lifetime figure, latest command time, collector time, and large single-record contributions. A high lifetime reduction can come from an old large output while current tasks rarely invoke RTK.

RTK, Headroom local output, and Headroom model-request counters measure different stages. They can overlap and are never added together. Local retrieval costs can lower net savings. Serena reports observed navigation calls, without inventing a token-saving estimate. The dashboard does not measure your Codex account quota or bill.

## Request a local summary

1. Turn **LangMem local summaries** and **llama.cpp local inference** On after their runtimes and local GGUF model are configured.
2. Expand **Experimental local summaries** and select the intended task.
3. Choose **Refresh summary** once. The job processes the pending history in batches and shows progress. The local model stays loaded between batches and unloads when the job ends.
4. Use **Cancel running job** if needed. Completed batches remain saved; another refresh resumes them. New conversation messages added during a job are picked up on the next refresh. Original conversation files remain unchanged.

This is an optional local aid, not a replacement for Codex's encrypted native compaction. Native compaction stays enabled. Summaries are not automatically injected into model requests. Long jobs can take time. The reader scans a fixed source snapshot, ignores native compaction metadata, and reports incomplete/malformed records or records exceeding its 16 MiB bound. Coverage counts text segments, so long messages can count as several segments. Older summary formats are marked stale and rebuilt on explicit refresh.

Historical source-evidence notes retain nonzero command exit codes and incomplete-output observations across batches. They do not establish whether a failure remains unresolved, and cannot prove the summary is factually complete. A shorter local summary does not by itself establish any savings in Codex usage. Check originals for exact facts, paths and requirements before relying on a generated summary.

## Update libraries

Expand **Library updates**, click **Check for updates**, and select an installed runtime: **Headroom**, **RTK**, **Serena**, **LangMem**, or **llama.cpp**. Each candidate is staged and checked before its runtime selection changes; **Rollback** returns to the retained previous selection when available. Headroom also offers **Refresh dependencies** when appropriate.

Checks and installs are manual. Model GGUF files are not automatically replaced. Existing MCP processes may need a Codex reload after a runtime update. New command workers and summary jobs use the selected runtime. Running work must finish before incompatible runtime operations proceed.

## If something stops working

Check the affected component's status, latest activity and error. No recent use can mean the current workload did not invoke that component. A selected but bypassed request compressor is a different condition from a broken RTK launcher.

Use the dashboard controls for routine changes. If the local request relay prevents Codex from connecting, run `Restore-Codex-Direct.ps1` from the installed bundle and restart Codex. Preserve state and backup directories during repairs. Compression is lossy; exact-output bypasses, original retrieval and task-level validation are required whenever omitted details could change the result.
