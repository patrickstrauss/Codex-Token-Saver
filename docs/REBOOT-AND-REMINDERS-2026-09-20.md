# Reboot repair and implicit Serena

Historical retained-component report. See [the current bundle guide](USING-BUNDLE.md) for installation and controls.

The post-reboot check found functional services only after the user manually opened the tray. Both scheduled launches had ended with `0xC000013A`; logs also showed competing launches. The precise source of that termination code was not established. A competing Headroom startup could overwrite the serving process's diagnostic receipt before losing the backend port.

Startup now has one authority: a scheduled, unelevated, interactive tray task using a native GUI launcher that starts PowerShell without a console. The tray maintains dashboard and supervisor recovery. Migration checks ownership, backs up existing registration, verifies the replacement, retires only owned duplicate entries, and restores snapshots on failure. A Startup shortcut is used only if task registration is unavailable. Existing worker processes and managed routing are preserved during migration.

Headroom now publishes its exact-retrieval receipt only after receiving HTTP or WebSocket traffic. A failed competing bind cannot replace proof from the serving backend. The isolated real-SDK check verifies this race without using production ports or histories. This change takes effect when the backend next starts; installing the file does not alter an already running process.

## Serena

Enabling Serena also installs a managed global Codex instruction block, backed up and updated transactionally with its MCP configuration. For relevant code navigation, Codex should activate the current checkout and prefer symbol overviews, targeted bodies and references. MCP initialization supplies the same concise workflow. No per-task prompt is required. Tool selection is still performed by Codex; unsupported queries or disabled Serena fall back to normal source tools. New instructions require a fresh task/tool connection or Codex restart.

## Verification boundaries

The live post-reboot Serena queries and RTK command passed. Backend receipt tests use temporary state and an unrelated local port. Startup tests use a real hidden child process and isolated OS-boundary fakes; an early test accidentally touched startup registration and was immediately restored and verified before the test isolation was corrected.

The final scheduled-launch check can verify the configured task and hidden process without rebooting the laptop. A subsequent Windows restart is still required to confirm the corrected logon sequence and load the backend diagnostic change.

Final historical verification: 396 core checks (one skipped) and 240 dashboard tests passed. After Windows COM normalized empty arguments and ISO durations differently from the original fixtures, the comparison was corrected and all 9 startup tests passed. The first live migration safely rolled back; the corrected migration then succeeded. A real scheduled launch created the tray through the new GUI executable, reported healthy, retained both request-worker process identities, and left the legacy task disabled and duplicate Startup shortcut absent.
