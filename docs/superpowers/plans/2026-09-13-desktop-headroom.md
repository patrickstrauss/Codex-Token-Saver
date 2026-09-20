# Desktop Headroom Implementation Plan

> For agentic workers: use subagent-driven development for independent backend, dashboard, and RTK wrapper tasks. Root owns MCP transport, registration, integration checks, and final review.

**Goal:** Make Headroom useful inside Codex desktop for large local file reads without introducing a network proxy dependency.

**Architecture:** Codex starts an optional stdio MCP server. The server reads explicitly requested files, applies the installed Headroom SDK locally, and exposes exact originals through retrieval. Its own SQLite ledger feeds a separate dashboard counter. Codex continues using its existing OpenAI provider, model, authentication, and reasoning settings.

**Tech stack:** Python 3.13, Headroom 0.37.0, MCP SDK, SQLite, existing Flask dashboard, Windows tray, native C# RTK launcher.

**Scope:** File/tool-content compression only; no claim of automatic full-conversation compression or billed savings. No new API keys, global proxy route, model changes, or mandatory MCP startup.

## Backend and measurements

- [x] Implement `DesktopHeadroom.read_file`, `retrieve`, and `stats` in `desktop_headroom.py` with tests in `tests/test_desktop_headroom.py`.
- [x] Reject invalid ranges, relative paths, binary content, and files over 2 MB. Preserve exact originals in the local Headroom cache.
- [x] Count original content and complete returned text using cached o200k tokenization. Record signed read savings and negative retrieval overhead in `headroom/desktop-state/activity.db`.
- [x] Verify offline SDK behavior, exact retrieval across restart, compression fallback, and concurrent SQLite writes.

## MCP transport and installation

- [x] Expose three read-only tools from `desktop_mcp.py`: `headroom_read_file`, `headroom_retrieve`, `headroom_stats`.
- [x] Test stdio initialization, tool schemas, tool errors, real compression, and subsequent retrieval using an isolated state directory.
- [x] Add only `mcp_servers.headroom_desktop` to the shared host config through `install_desktop_mcp.py`; set `required=false` and bounded startup/tool timeouts. Back up and verify all other settings unchanged.
- [x] Add concise tool preference and fallback instructions to the owned AGENTS section.

## Dashboard and Windows integration

- [x] Add a separate desktop Headroom card and tray counter using the signed local ledger. Keep proxy history separate and never infer process health from historic counters.
- [x] Replace shell-based RTK argument forwarding with a native executable; test literal arguments and stream/exit behavior.
- [x] Re-start only verified owned tray/dashboard processes so UI updates load.

## Acceptance

- [x] Run scoped tests and one real Codex tool-use smoke check with the normal provider/model/reasoning preserved.
- [x] Prove an unavailable optional MCP server does not prevent a normal Codex response.
- [x] Verify shared desktop configuration, rendering, persisted counters, and direct networking. Document that an existing desktop session may need restarting to load the newly registered tools.
