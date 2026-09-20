# Desktop integration verification — September 13, 2026

Headroom is registered as an optional local MCP tool server for Codex desktop. It compresses selected large local file reads and supports exact original retrieval. Codex keeps its existing direct OpenAI connection, `gpt-6-astra` model, and `ultra` reasoning setting. Global proxy routing remains disabled.

## Verified

- **87 root tests passed**, covering Headroom compression and retrieval, offline tokenizer/cache failures, signed savings, MCP stdio transport, config preservation, native Windows argument forwarding, and prior service recovery protections. See `logs/desktop-final-unit-tests.log`.
- A fresh run of the Codex engine bundled with desktop automatically selected `headroom_read_file` for a generic large-file inspection request, then used `headroom_retrieve` to confirm the exact critical record. The fixture used 6,757 original content tokens and returned 2,450 content tokens across both calls: **4,307 estimated net tokens avoided**. Synthetic activity used isolated storage and does not appear in real desktop savings. See `logs/desktop-use-smoke-result.json`.
- A second run with a deliberately missing optional MCP executable completed normally and replied `CODEX_WITHOUT_HEADROOM_OK`. Both live runs preserved the full shared config file. See `logs/desktop-missing-smoke-result.json`.
- Installed settings compare equal to the backup after removing only the new `headroom_desktop` server. Other model, provider, reasoning, and user settings are unchanged. Registration is optional (`required=false`) with bounded startup and tool timeouts.
- The dashboard health endpoint and tray report healthy. The rendered dashboard shows separate RTK, Headroom desktop, and historical CLI proxy counters. The optional HTTP proxy is not listening. Real desktop history is currently empty because the existing desktop session has not loaded the new tools.
- Native `rtk.exe`, `codex-saver.exe`, and `codex-headroom.exe` preserve literal arguments, working directory, standard streams, and child exit codes without shell expansion.

## Using it

Restart Codex once, then open a new task to load the new tools. Open **Codex Token Saver** from Windows Start, click the **TS** tray icon, or visit [the dashboard](http://127.0.0.1:8095/).

Headroom applies when Codex uses these local file tools; it does not compress every message or all network requests. RTK applies to supported commands invoked through RTK. Counters are estimates of content reduction, not account quota or billing. Returned headers and exact retrieval costs are included in the Headroom desktop estimate; MCP framing and model reasoning are excluded.

The currently open Codex GUI was not restarted during installation. A true laptop reboot/login test remains outstanding. Live integration checks used the same bundled Codex engine and shared host configuration in fresh processes.

## Records and recovery

`desktop-verification.json` records installed-state checks; `desktop-integration.json` identifies the config backup. `README.md` contains usage and recovery instructions. To disable only these tools, set `mcp_servers.headroom_desktop.enabled=false` and restart Codex. Do not restore global proxy routing.
