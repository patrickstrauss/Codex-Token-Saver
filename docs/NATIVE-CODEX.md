# Native Codex with Token Saver

Open **Codex Token Saver** and **Codex**. OpenCodex is optional and is not needed for RTK, Headroom file reading, Serena, ast-grep, Playwright CLI or Laya. Explicit bundle tool requests keep their Laya gateway; automatic compression and command hooks keep their fast paths.

Native request compression uses Token Saver's stable local relay on port 8788 and its managed Headroom backend on 8789. Codex retains its ChatGPT authentication, selected model and reasoning effort. The relay does not choose another model. Pausing request compression restores Token Saver's own route through the existing controller.

## Returning from an existing OpenCodex installation

The checked `native_migration.py` utility provides `prepare`, `connect` and `status`. It removes only the discovered OpenCodex root API endpoint, its matching realtime endpoint and its owned model catalog. It makes an exact configuration backup, preserves other settings and rejects unknown routes or concurrent edits. It does not recover, decrypt or rewrite chat history.

Before changing modes, disable OpenCodex's Codex integration (`clientIntegrations.codex = false`) and its Windows startup entry. Preserve its provider configuration. Do not use an old combined bundle's Connect script afterward: that script intentionally reconnects OpenCodex.

Run `prepare` using the installed dashboard Python. Restart only Token Saver's owned, paused proxy workers to load the native backend, then run `connect` after the native runtime and source validation passes. This is a qualified migration operation, not an instruction to kill all Python processes. The native backend continues to serve unexpired exact originals from the previous transform worker's store.

After successful activation, finish active work, fully exit Codex, close OpenCodex, and reopen **Codex Token Saver + Codex**. Loaded chats keep their old connection until Codex exits. A Windows reboot is not required. Existing chats that contain provider-owned encrypted compactions may still need separately approved targeted recovery; switching the route does not repair their history.

The Headroom dashboard now measures native proxy savings. Previous OpenCodex transform totals remain a separate history. Eligible requests can save zero tokens; tool activity is not proof of quota savings.
