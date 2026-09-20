# Repair — 13 September 2026

The original global Headroom route made Codex desktop depend on a local proxy. The installation also lived in Codex's MSIX private filesystem: Explorer could not find the normal AppData path used by the startup shortcut. Together these created a startup failure that could interrupt Codex connectivity.

The repaired installation is `C:\Users\Patcharagit Strauss\CodexTokenSaver`. Both Python environments were recreated at that stable path. RTK's history was preserved with SQLite backup, and its wrapper now writes to the stable data folder. Actual Windows startup and Start Menu shortcuts, user PATH, and a user-logon scheduled task were registered and verified from Explorer.

Codex desktop uses its normal connection. The bundle's global routing command refuses enable operations, and the tray has no routing toggle. Removing the remaining legacy marker comments preserved all parsed Codex settings. The selected model remains `gpt-6-astra` with `ultra` reasoning.

Headroom is an optional CLI experiment. It uses only a process-local endpoint override, preserves authentication/provider identity, and falls back directly before launch when unavailable. It never automatically replays a started request. Timeouts clean up only the service process tree created by that attempt; unrelated listeners remain untouched.

## Verification

- 100 dashboard tests and 45 routing, launcher, and service tests passed.
- Explorer launched the stable Python environment and current Codex CLI successfully; `rtk` resolved to the stable wrapper.
- Dashboard recovered automatically after its verified process was stopped: PID 11904 → 14660.
- Optional Headroom inference returned `TOKEN_SAVER_OK`, retaining `gpt-6-astra`, `openai`, and `ultra`. The proxy recorded two requests, zero failures, and 433 context tokens reduced in this smoke test.
- Direct inference with Headroom off returned `DIRECT_CODEX_OK` with the same model and reasoning settings.
- An unrelated listener on port 8787 survived the optional launch fallback. Codex config remained byte-for-byte unchanged.
- A live owned Windows Python fixture confirmed timeout cleanup stops both the launcher and its interpreter child.
- RTK estimates and Headroom reductions remain separate. Offline Headroom data is labeled historical; it is not current desktop compression or account quota savings.

Normal final state: tray and dashboard running, Headroom off. Supporting local JSON receipts are in the bundle root and `logs`.

A full laptop reboot and fresh interactive logon have not been performed. Scheduled launch, external Windows paths, process failure, and automatic recovery were tested without restarting the user's laptop or active Codex desktop.
