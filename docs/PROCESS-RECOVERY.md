# High process count or memory use

Serena starts its backend only when navigation is used and unloads it with its language servers after two idle minutes. Its lightweight MCP bridge remains available and remembers each chat's active checkout. Laya's shared model unloads after five idle minutes. After installing this update, fully quit and reopen Codex to replace previously loaded workers; restarting Windows is unnecessary for this lifecycle update. Active lookups can finish normally.

## Stop the bundle without deleting your data

In the dashboard, open **Your toolkit → Turn off Token Saver → Disable Token Saver…**, or right-click the **TS** tray icon and choose **Disable Token Saver…**. A separate Windows confirmation explains the changes. Fully quit Codex before continuing; if it is still open, the dialog lets you retry or cancel. Opening or cancelling the dialog does not disable anything. Wait for the success message, then **restart Windows yourself**.

If the UI is unavailable, fully quit Codex and run **Disable-Token-Saver.cmd** from the installed folder or the latest fully extracted deployment package. Both entry points use the same disable procedure: disable owned startup entries and Codex integrations, turn the bundle preferences off, and restore an owned request route before marking the proxy uninstalled. The procedure does not terminate applications, reboot Windows, delete installation files/history, or change your model, reasoning, authentication or unrelated tools.

Restarting Windows is required to clear existing workers. Closing the tray alone leaves services running; component switches and Pause are not full shutdown controls. Disable failures must be addressed before treating the bundle as disabled. Keep the printed report and backup location. Windows startup changes and configuration edits are separate operations; inspect any partial-failure report.

The disable command preserves an independent registration belonging to another installation by refusing to modify it. It does not manage unrelated copies of Headroom. Re-enabling the disabled bundle requires explicit startup and tool registration setup; simply reopening its dashboard is insufficient.

## If the installation folder was already deleted

The automated disable command needs the installed Python runtime for safe TOML and owned-route recovery. Do not recreate random config entries or delete your whole Codex configuration to silence startup errors.

1. Fully quit Codex. Open **Task Scheduler → Task Scheduler Library**. Inspect **Codex Token Saver** and, if present, **Codex Token Saver Proxy**. Disable only entries whose Actions target the deleted `%USERPROFILE%\CodexTokenSaver` folder. If an older **Codex Token Saver.lnk** exists in the Windows Startup folder, remove that shortcut only after confirming its target points to that folder.
2. Before starting another Codex task, disable its missing bundle MCP servers: **headroom_desktop**, **bundle_serena**, and **bundle_laya_router**, when their commands point to the deleted folder. Inspect any additional **headroom** registration too: disable it only if its command points into the deleted folder. Disable the **Checking automatic Headroom command compression** user hook if it also references that folder. Leave registrations for other installations intact.
3. If Codex had request compression enabled, its saved connection may still point to `http://127.0.0.1:8788/v1`. Restore the pre-bundle connection from the user's own configuration backup or get maintainer help before changing it. When the only addition was a top-level `openai_base_url = "http://127.0.0.1:8788/v1"`, removing that exact added line restores the default connection. Preserve any pre-existing custom endpoint. Do not delete model, authentication, profile or unrelated configuration settings.
4. Restart Windows. The deleted installation should no longer be requested at login or by Codex.

## Capture evidence if it happens again

Run **Get-Token-Saver-Diagnostics.cmd** before stopping or deleting anything. This read-only command works from the extracted package even when the installation is missing. It prints the location of a JSON report containing installed version (when available), process names, paths, parent IDs, creation times, working-set sizes and fixed role labels. It includes unexplained `headroom.exe` processes as well as bundle workers and their descendants. It does not copy raw command lines, environment variables, tokens, config contents or conversations. Paths may identify a Windows user; review the report before sharing it.

Windows Python virtual environments commonly have a small launcher plus an interpreter child; two rows can represent one service. MCP tools may also have separate processes for concurrently loaded Codex tasks. Process count alone does not establish a leak. Look for continued growth after work is idle, orphaned ancestors and increasing memory.

## September 23 investigation

The reported installation was deleted before its process paths, command lines and startup logs could be captured, so its exact cause remains unconfirmed. Deletion stopping the spawning ties the symptom to that installation, but does not identify the faulty launch path.

The current bundle launches the managed proxy through `python.exe proxy_runtime.py --serve`, and its native command wrapper is named `headroom-run.exe`. The screenshot showed `headroom.exe`, which is also an upstream CLI entry point. Source inspection found no bundle startup path that invokes that entry point or installs upstream `headroom mcp serve`. An independent or older registration remains a possibility, not a finding.

Isolated service/supervisor checks cover single-instance locking, startup backoff, slow workers and crash recovery. A real Windows virtual-environment timeout check preserves the original command output and confirms its interpreter exits. These checks did not reproduce the reported accumulation. The confirmed recovery gap was the lack of a complete disable option; the disable command and diagnostic capture address that gap without claiming an unproven leak fix.

Regression checks also found a separate model-validation false negative: cold CPU inference could exceed the production compression time limit and return unchanged text, then be reported as an unavailable runtime. The model capability probe now has its own bounded time allowance and preserves failure diagnostics. Production compression limits remain unchanged. This validation issue does not establish the cause of the reported process accumulation.
