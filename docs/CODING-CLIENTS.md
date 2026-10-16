# Coding clients

Token Saver's local tools are available to stdio MCP clients on Windows x64.
Codex remains supported. OpenCodex is not required. Other operating systems and
automatic model-request compression in other harnesses are not qualified.

The adapters below share the same managed runtimes and dashboard. Adding a client
does not duplicate the installation, select a model, reset login, or convert chat
history. All explicit bundle operations still pass through Laya; automatic Codex
compression and RTK hooks keep their existing fast paths.

## Installation without Codex

From an extracted release, run in PowerShell:

```powershell
.\Install.ps1 -Harness standalone
```

This installs the normal app, Start menu shortcut and startup registration without
creating or editing Codex configuration. Open the app from the Start menu. Choose
**Toolkit > Coding clients** for a client-specific MCP snippet and setup command.
`Install.cmd` retains its Codex default. `-SkipIntegration` remains an isolated
installation mode without Windows startup or client registration.

An existing installation keeps its original client mode. Add clients with the
connector below; changing the installer mode requires the documented safe
uninstall/reinstall procedure. Never remove an active installation directory.
Use the full installation for routed MCP work. CoreOnly omits Laya's managed
runtime and is not qualified for the mandatory explicit-tool gateway.

## Connect and disconnect

Run the installed script from PowerShell. Commands without `-Apply` only show a
plan; `export` prints JSON and never changes client configuration.

```powershell
$bundle = Join-Path $env:USERPROFILE 'CodexTokenSaver'
& "$bundle\Connect-Harness.ps1" -Action list
& "$bundle\Connect-Harness.ps1" -Action export -Client claude-code
& "$bundle\Connect-Harness.ps1" -Action connect -Client claude-code
& "$bundle\Connect-Harness.ps1" -Action connect -Client claude-code -Apply

# Project scope: select an existing project explicitly.
& "$bundle\Connect-Harness.ps1" -Action connect -Client gemini-cli -Scope project -Project 'C:\Projects\Example' -Apply

# VS Code: select the active profile through MCP: Open User Configuration.
# Supply that exact file, or use project scope for .vscode/mcp.json.
& "$bundle\Connect-Harness.ps1" -Action connect -Client vscode -Config 'C:\path\to\profile\mcp.json' -Apply

# Custom profiles/paths are supported for every listed serializer.
& "$bundle\Connect-Harness.ps1" -Action disconnect -Client claude-code -Apply
& "$bundle\Connect-Harness.ps1" -Action disconnect-all
```

After connecting, reload the client and review its MCP trust prompt. The connector
does not approve trust or enable disabled bundle components. Component switches
are shared by all connected clients. A receipt proves configuration, not that a
running session loaded it. Foreign client session IDs are not mapped to Codex
conversation titles; unattributed activity remains unknown.

The connector rejects conflicting names and changed owned entries. It preserves
unrelated settings, comments, trailing commas and a UTF-8 BOM. Local backups and
ownership receipts are retained under `integrations/`; these can contain private
client settings and must never be committed or shared. Close clients before
applying setup changes. If a write is interrupted, keep its transaction backup
and inspect the original file rather than deleting ownership evidence.

## Adapter contracts

| Client ID | User configuration | Project configuration | Server section |
|---|---|---|---|
| `claude-code` | `~/.claude.json` | `.mcp.json` | `mcpServers` |
| `gemini-cli` | `~/.gemini/settings.json` | `.gemini/settings.json` | `mcpServers` |
| `cursor` | `~/.cursor/mcp.json` | `.cursor/mcp.json` | `mcpServers` |
| `opencode` | `~/.config/opencode/opencode.json` | `opencode.json` | `mcp` |
| `vscode` | Explicit active-profile path | `.vscode/mcp.json` | `servers` |
| `cline` | CLI: `~/.cline/data/settings/cline_mcp_settings.json`; IDE: explicit path | Explicit path | `mcpServers` |
| `kilo` | `~/.config/kilo/kilo.jsonc` | `.kilo/kilo.jsonc` or existing root `kilo.json` / `kilo.jsonc` | `mcp` |
| `windsurf-cascade` | Explicit legacy Cascade MCP path | Explicit path | `mcpServers` |
| `generic` | Explicit path or manual export | Explicit path or manual export | `mcpServers` |

OpenCode's existing `.jsonc` alternative is supported. If both JSON and JSONC
files exist, select the intended file with `-Config`. If your client redirects
its home/config directory with an environment variable, use `-Config` with its
actual path. VS Code's portable Copilot configuration is a separate
`mcpServers` format: use `generic` for that file, not `vscode`.

Cline's CLI honors `CLINE_MCP_SETTINGS_PATH`; for its IDE, open **MCP Servers >
Configure > Configure MCP Servers** and supply that exact path with `-Config`.
Kilo uses its own configuration, never an OpenCode fallback. Multiple existing
Kilo config files require explicit selection. The Windsurf adapter is for legacy
Cascade, now documented under Devin Desktop. Its newer Devin Local agent uses a
different configuration and is not qualified by this adapter. Select the legacy
MCP file through that client and use `-Config`; no legacy directory is guessed.

Official formats checked 16 October 2026:
[Claude Code](https://code.claude.com/docs/en/mcp),
[Gemini CLI](https://geminicli.com/docs/tools/mcp-server/),
[Cursor](https://cursor.com/docs/mcp),
[OpenCode](https://docs.opencode.ai/docs/mcp-servers/),
[VS Code](https://code.visualstudio.com/docs/agents/reference/mcp-configuration),
[Cline](https://docs.cline.bot/mcp/mcp-overview),
[Kilo](https://kilo.ai/docs/automate/mcp/using-in-kilo-code),
[legacy Cascade](https://docs.devin.ai/desktop/cascade/mcp).

## Capabilities and limits

| Feature | Codex | Other MCP clients |
|---|---|---|
| Local Headroom reading and exact retrieval | Existing integration | Shared stdio server |
| Serena navigation and Laya bundle routing | Existing integration | Shared stdio servers; installed runtimes required |
| ast-grep, browser snapshots and Git reports through Laya | Available when enabled | Same tool contract |
| Explicit RTK, Playwright CLI and ast-grep commands | Available when enabled | Available when the harness permits local commands |
| Automatic command hook | Existing Codex contract and user trust | Not installed by these adapters |
| Model-request compression | Existing qualified Codex connection | Not installed; provider contracts differ |
| Cross-provider encrypted history migration | Not performed | Not performed |

For clients without MCP, use the installed CLI tools explicitly according to
`CLI-TOOLS.md`. A generic export is not a promise that every agent supports MCP
or unrestricted shell execution. Electron browser control still requires an
explicitly available CDP endpoint.

Current validation covers format contracts, preservation, conflict refusal,
rollback, multiple-client removal, launcher isolation and dashboard security.
Live authenticated sessions in external clients remain unverified until tested
with those installed clients. No end-to-end savings claim is inferred from MCP
registration or operation counts.

## Uninstall

The normal disable/uninstall flow removes connector-owned registrations before
moving the shared installation into its backup. It refuses changed entries and
active bundle workers. Disconnecting one client does not disable other clients
or their shared components. Manually copied snippets are not owned by the
connector: remove those entries yourself before uninstalling, then close the
clients. Backups preserve original settings; unrelated servers and authentication
remain with their client.
