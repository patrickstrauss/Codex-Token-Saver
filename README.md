# Codex Token Saver

**A Windows tray app for controlling and measuring local token-saving tools used with Codex.** The dashboard provides independent controls for RTK, Headroom local output, Headroom request compression, Serena, LangMem summaries and llama.cpp. Requested settings, readiness and recent activity are shown separately. Start with [Using the bundle](docs/USING-BUNDLE.md).

The bundle lives in `%USERPROFILE%\CodexTokenSaver`, a regular user folder. The earlier `%LOCALAPPDATA%` installation was affected by Codex MSIX filesystem virtualization: files visible inside Codex differed from those seen by Explorer and login startup.

Open **Codex Token Saver** from the Windows Start menu, open the [dashboard](http://127.0.0.1:8095/), or click the **TS** tray icon. Windows may hide the icon under the tray's up-arrow.

**Team installation:** Follow [Download the workflow artifact and set up Codex](docs/TEAM-INSTALL.md#download-the-workflow-artifact). Choose an approved successful **Windows package** run in [GitHub Actions](https://github.com/patrickstrauss/Codex-Token-Saver/actions), download **windows-package**, extract both ZIP layers, then run **Install.cmd**. No developer tools are required. The guide covers enabling Serena, verification, troubleshooting and updates. Keep local summaries/local inference Off for now; fresh request-compression setup is unsupported. Existing managed connections are preserved, and the installer will not overwrite an existing installation.

In **Local summaries**, paste a `codex://threads/<task-id>` link and look up the task before starting. Completed batches are saved for resumption. Summary generation does **not** require restarting Codex or replace native compaction. Restart only when Codex needs to load newly installed or updated local tools.

Expand **Library updates** to check Headroom, RTK, Serena, LangMem and llama.cpp releases, install a validated candidate, or roll back to the retained previous runtime. **Refresh dependencies** updates Headroom's compatible Python dependencies when its core is current. Model GGUF files are not automatically replaced. Checks and installations are manual; see [Updating the libraries](LIBRARY-UPDATES.md).

## Source checkout and development

This repository contains adapters, dashboard code, native launcher source and tests. It excludes installed environments, downloaded executables, models, credentials and local histories. Cloning it does not install runtimes or change Codex configuration. Keep the development checkout separate from the stable `%USERPROFILE%\CodexTokenSaver` installation used by Windows startup.

For isolated dashboard development on Windows with Python 3.12 and Node.js available:

```powershell
git clone https://github.com/patrickstrauss/Codex-Token-Saver.git
Set-Location Codex-Token-Saver
py -3.12 -m venv dashboard/.venv
& ./dashboard/.venv/Scripts/python.exe -m pip install -r dashboard/requirements.txt -r dashboard/requirements-dev.txt
Push-Location dashboard
& ./.venv/Scripts/python.exe -m pytest
Pop-Location
```

The tests use isolated data. For a UI preview that cannot change live settings or launch a model, run `dashboard/tests/ui_fixture.py` with that interpreter and open `http://127.0.0.1:18795/`. Stop the fixture after testing. Build the RTK launcher from [native/](native/README.md); full SDK/MCP/model checks also require the separately installed, pinned runtimes. See [UI validation](docs/CONTROL-UI-VALIDATION.md), [Serena validation](docs/SERENA-INTEGRATION.md) and [request connection validation](DESKTOP-REQUEST-PROXY.md).

Deploy only validated source into the stable installed bundle, retaining its runtime selections, histories and recovery backups. Do not replace its configuration with development fixture data or redirect startup to an unvalidated checkout.

## Components

| Component | Purpose and location |
| --- | --- |
| RTK 0.49.0 | Compact supported terminal output; native `bin\rtk.exe` launches `tools\rtk.exe`; history is `data\rtk\history.db` |
| Dashboard and tray | Separate savings counters on loopback port 8095; `dashboard\`, `Tray.ps1`, `Start-Services.ps1`; logs in `logs\` |
| Headroom desktop | Installed Headroom 0.37.0 SDK, exposed through the optional local `headroom_desktop` MCP server; `desktop_mcp.py`, `desktop_headroom.py` |
| Headroom request compression | Stable loopback relay on 8788, separate Headroom backend on 8789, supervised by the **Codex Token Saver Proxy** login task; controls and state in `proxy\` |
| Headroom CLI proxy | Separate experimental option; loopback port 8787 when explicitly started |
| Serena | Optional read-only symbol/navigation MCP tools; a live preference gate also controls already-loaded tasks |
| LangMem + llama.cpp | Experimental summaries for explicitly selected tasks, generated with a configured local model; native Codex compaction remains enabled |
| Library updater | Manual dashboard controls; `bundle_updates.py`, `runtime_selection.py`, staged environments and rollback records in `updates\` |

RTK works when supported `rtk` commands are invoked. Its native launcher also checks eligible stdout with Headroom when running inside Codex. The RTK command executes exactly once; optional compression happens afterward. The launcher keeps RTK history in the stable bundle data directory and preserves command arguments; `bin\rtk.cmd` remains for legacy use.

## Automatic command output

The native RTK integration needs no additional tool selection. It applies only to supported human-readable command output in Codex. Machine-readable RTK statistics, exact/interactive requests, failed commands, small output, and long-running or oversized streams remain unchanged. Headroom must produce a smaller result after including its retrieval header. Missing, broken, or timed-out compression returns original output; it never replays the command.

For additional commands, go to **Codex Settings → Hooks → Reload hooks → User**, review **Checking automatic Headroom command compression**, and click **Trust**. Codex requires review of the exact new hook definition. The installer does not grant trust. Existing tasks can use the integration; creating a new task is unnecessary.

The hook handles supported standalone PowerShell calls with an explicit Windows `.exe` path, such as `& 'C:\Program Files\Git\cmd\git.exe' status`, including eligible statements inside multiline scripts. It preserves other statements, comments, arguments, and command order. It does not rewrite commands inside assignments, pipelines, control flow, subexpressions, or redirects; ambiguous commands, dynamic arguments, exact source/diff reads, and unsupported executables also stay unchanged. Eligible tools include selected Git, search, and test/build commands; browser tools and ordinary chat are outside this scope. RTK already covers the common bare `rtk` path automatically, so it does not depend on hook selection.

Command compression considers outputs starting at 1 KiB and 350 estimated tokens. A result is returned only when it is smaller in both bytes and tokens after including its recovery instructions. Outputs that do not benefit stay unchanged. The dashboard separates hook checks, rewritten calls, skipped calls, and actual reductions; skip reasons describe a bounded recent log window.

The hook only rewrites the pending command. Codex's normal command execution, sandbox, and approval checks still apply. Add `# headroom: exact` to decline hook rewriting. `HEADROOM_EXACT=1` bypasses the launcher's additional Headroom stage; RTK's own filtering still applies. Run the original command, or turn RTK off, when you need its complete output. The command runner can also be invoked with `--exact`. The dashboard reports checked command outputs and their last outcome separately from token savings.

## Using Headroom in desktop

Existing and new tasks work once Codex has loaded the local tools. If the tools are absent after their initial registration, restart Codex; creating a new task is unnecessary. `desktop-integration.json` records initial registration, not current activity. The native RTK update applies to subsequent commands without restarting Codex; use Reload hooks and Trust for the additional command hook.

Codex receives instructions to prefer `headroom_read_file` for initial inspection of large local JSON, CSV, and log files. Headroom runs locally and returns a compressed overview when useful. For exact details before edits, quotations, or decisions that require complete information, Codex can use `headroom_retrieve` or read with `compress=false`. Already-read text should not be sent again just to compress it.

The server starts with Codex over standard input/output and is registered with `required=false`. If a local tool fails or is absent, Codex can continue with ordinary file tools. The integration does not change your model, reasoning setting, account authentication, or API route. It needs no HTTP proxy or dashboard connection.

Original file text is cached locally for up to 24 hours in `headroom\desktop-state\originals.db` to support exact retrieval. This cache can contain the contents of files you ask Codex to inspect. The counters in `headroom\desktop-state\activity.db` store token counts and activity times separately. Desktop compression runs offline with telemetry disabled.

## Connections and startup

Windows login startup runs the dashboard and tray. The separate **Codex Token Saver Proxy** task supervises the request relay and compression engine. Enabling request compression changes only the built-in OpenAI endpoint to the local relay, after validation; it preserves provider identity, authentication, model, reasoning, and task history. Codex manages its optional local file-tool process independently.

Use **Bundle controls → Headroom request compression**, or the existing Enable/Pause controls under **Headroom request savings**. Restart Codex when convenient after a connection change and resume existing tasks. Pausing restores the owned endpoint setting and retains the relay. Already-open connections can retain their previous upstream until closed; the app does not interrupt or replay them.

The user-logon scheduled task, Windows Startup fallback shortcut, and Start Menu shortcut are installed. Their paths and a successful scheduled launch were verified outside Codex through Explorer. `Install-Startup.ps1` can repair them; inspect `install-startup-result.json` for the result. **A true reboot/login test remains outstanding.**

The older `bin\codex-headroom.exe` experiment uses port 8787 only for its launched CLI process when no endpoint is already configured. It does not replace an active desktop request route. `bin\codex-saver.exe` launches a CLI session using your current configuration, including the request relay when enabled. Both launchers preserve literal arguments. Use the dedicated recovery script below to restore a normal connection.

## Reading the counters

The dashboard keeps these counters separate:

- **RTK:** estimated terminal-output tokens avoided by supported commands, with Today / 7 days / Lifetime windows, last actual recorded command time and large-record contributions.
- **Headroom desktop:** signed local file/stdout reduction estimate, including returned text headers and deducting later retrieval output. Command estimates are measured before Codex truncation and are not proof that the model's context shrank by that amount. RTK's own reduction is excluded from Headroom's input baseline. Checked commands can produce zero reduction. Expansion/retrieval can make net savings negative. MCP framing, model usage, and subsequent reasoning are outside this estimate.
- **Headroom CLI proxy:** reductions reported by the separate optional proxy, including retained historical records.
- **Headroom request savings:** Headroom-reported input reductions from model requests sent through the new relay. The backend records each request; relay counters measure completed HTTP/WebSocket connections and currently active connections. A long-lived WebSocket can record savings before its connection completes.

These scopes may overlap: **never add them together** or treat them as ChatGPT quota or billed savings. “Configured” means the desktop tool is registered to load with Codex; saved history does not establish that it is running or being used now.

The new request integration follows the [Headroom desktop app](https://github.com/gglucass/headroom-desktop)'s complete-request approach, including its coding profile and local Kompress engine. Output shaping and model/effort routing remain disabled to preserve your selections. Eligible content and workload determine savings; no fixed percentage or account-quota reduction is promised. The earlier [comparison](HEADROOM-COMPARISON.md) documents why local-output counters alone showed less activity.

The original proxy check recorded **234 reduced tokens**. The preserved `headroom\state\savings_events.jsonl` record appears in the CLI proxy card as historical data while that proxy is off. It is separate from desktop file-tool savings. Imported RTK history is retained. Synthetic validation uses separate state and is excluded from the real desktop counters.

The [JSON summary](http://127.0.0.1:8095/api/stats) exposes `rtk`, `desktop_headroom`, and `headroom` separately. [Request proxy status](http://127.0.0.1:8095/api/request-proxy) exposes the new connection and request counters. Empty history and unavailable data are distinguished.

## Recovery and maintenance

Use `Start-Services.ps1` to start or recover the dashboard. Dashboard failures do not require changing Codex desktop settings. Inspect `logs\` and the startup result file for local errors.

If Codex cannot connect, run **Restore-Codex-Direct.ps1** from this bundle folder, then restart Codex. It restores the endpoint owned by this integration. Do this before disabling **Codex Token Saver Proxy** startup. Backend failure normally lets new requests use the direct upstream connection; a stopped relay itself needs supervisor recovery. Login startup cannot guarantee the relay starts before Codex. Requests already dispatched are never replayed by the relay.

To disable login startup, disable the **Codex Token Saver** scheduled task and remove its shortcut from `shell:startup`. This controls the dashboard and tray, not Codex's MCP tools. For routine compression changes, use the independent dashboard controls. Turning Headroom local output Off retains original-content retrieval; use the managed request control separately for routing changes.

Preserve `data\rtk`, `headroom\desktop-state\activity.db`, `headroom\state`, and `proxy\backend-state` when repairing or migrating savings history. Keep `proxy\route-receipt.json` and its config backups for endpoint restoration. The [September 13 repair report](REPAIR-REPORT.md) describes the earlier startup repair. A full reboot/login test remains outstanding.

Initial versions are pinned. The Library updates panel stages and validates core-library updates while preserving the local adapter; the custom dashboard code is maintained separately. Sources: [RTK](https://github.com/rtk-ai/rtk), [Headroom](https://github.com/headroomlabs-ai/headroom), and the [dashboard](https://github.com/Will-Luck/claude-tools-dashboard), pinned to `289253de78116310d9e682e0680bd8db2a526f14`. Included upstream licenses remain intact. The dashboard does not read Codex or Claude account credentials.
