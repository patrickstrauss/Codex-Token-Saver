# Reboot repair, implicit Serena and summary reminders

The post-reboot check found functional services only after the user manually opened the tray. Both scheduled launches had ended with `0xC000013A`; logs also showed competing launches. The precise source of that termination code was not established. A competing Headroom startup could overwrite the serving process's diagnostic receipt before losing the backend port.

Startup now has one authority: a scheduled, unelevated, interactive tray task using a native GUI launcher that starts PowerShell without a console. The tray maintains dashboard and supervisor recovery. Migration checks ownership, backs up existing registration, verifies the replacement, retires only owned duplicate entries, and restores snapshots on failure. A Startup shortcut is used only if task registration is unavailable. Existing worker processes and managed routing are preserved during migration.

Headroom now publishes its exact-retrieval receipt only after receiving HTTP or WebSocket traffic. A failed competing bind cannot replace proof from the serving backend. The isolated real-SDK check verifies this race without using production ports or histories. This change takes effect when the backend next starts; installing the file does not alter an already running process.

## Serena

Enabling Serena also installs a managed global Codex instruction block, backed up and updated transactionally with its MCP configuration. For relevant code navigation, Codex should activate the current checkout and prefer symbol overviews, targeted bodies and references. MCP initialization supplies the same concise workflow. No per-task prompt is required. Tool selection is still performed by Codex; unsupported queries or disabled Serena fall back to normal source tools. New instructions require a fresh task/tool connection or Codex restart.

## Summary reminders

The tray checks local usage metadata once per minute. Reminders default to 70% of a task's reported context window and can be enabled, disabled or adjusted between 20% and 95% in the summary panel. The measurement is the latest request's reported `input_tokens` divided by `model_context_window`; cache-hit tokens are already included. Lifetime token totals are not used. Unknown context windows produce no guessed percentage.

Only recently active, non-archived user tasks can trigger a popup. Delegated agent tasks are excluded. One notification attempt is made per threshold crossing; it is rearmed when reported context drops below the threshold. Turning LangMem or llama.cpp off suppresses reminders. A fresh saved summary also suppresses the current reminder. Windows notification settings can silence the popup; the dashboard still shows qualifying tasks.

Clicking the reminder opens the selected task in the summary panel. It does not start inference. Summaries remain optional reference artifacts: they do not replace Codex history, prevent native compaction, or establish quota savings. No transcript or request content is sent to a notification service.

## Verification boundaries

The live post-reboot Serena queries and RTK command passed. A synthetic local-model summary preserved original content and constraints, and cancellation unloaded the model. Backend receipt tests use temporary state and an unrelated local port. Startup tests use a real hidden child process and isolated OS-boundary fakes; an early test accidentally touched startup registration and was immediately restored and verified before the test isolation was corrected.

The final scheduled-launch check can verify the configured task and hidden process without rebooting the laptop. A subsequent Windows restart is still required to confirm the corrected logon sequence and load the backend diagnostic change.

Final verification: 396 core checks (one skipped), 10 summary-engine tests and 240 dashboard tests passed. After Windows COM normalized empty arguments and ISO durations differently from the original fixtures, the comparison was corrected and all 9 startup tests passed. The first live migration safely rolled back; the corrected migration then succeeded. A real scheduled launch created the tray through the new GUI executable, reported healthy, retained both request-worker process identities, and left the legacy task disabled and duplicate Startup shortcut absent. The reminder API was active at 70%, a qualifying task queued one notification attempt, and local inference remained idle.
