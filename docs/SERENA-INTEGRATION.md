# Serena navigation

The managed MCP entry point remains `serena_mcp.py`. It launches the official isolated Serena runtime through a standard MCP bridge, exposing only `activate_project`, `get_symbols_overview`, `find_symbol` and `find_referencing_symbols`. Both the upstream context and the bridge enforce this fixed tool set. Activating a project cannot expose editing tools. Project selection requires an explicit absolute checkout path; home directories and drive roots are rejected.

Each new tool call reads `settings/components.json`. Turning Serena off blocks subsequent calls even in an already loaded Codex task. A call already dispatched may finish. A malformed preference file also blocks new calls. Existing idle MCP/LSP processes may remain until Codex reloads them; the switch controls use, and is not a promise to immediately unload processes.

Exact symbol bodies and reference results carry the bundle's existing authenticated exact-response receipt, so a running, validated Headroom request backend preserves them rather than applying another lossy compression pass. Normal overviews remain overviews. Native source tools remain available if the language server cannot resolve a symbol.

The bundle records only completed/failed/blocked counts and latest activity in `serena/activity.json`; it does not record query arguments, project paths or source text in that ledger. Official Serena keeps its own local logs and project state. No synthetic token savings are claimed for navigation.

Updater compatibility remains `probe_runtime(root, python_path)`. Candidate validation initializes the official server directly and verifies exactly the four tools even when the component is off. Normal tool use always passes through the live preference gate.

`scripts/verify_serena_navigation.py` checks real Python and TypeScript overviews, exact bodies, callers, source freshness after a file edit, stable tool exposure after activation, and off/on behavior in the same MCP session. It creates a temporary bundle and project while reading already installed Serena dependencies. Use the installed Serena interpreter to run it; `--bridge-python` can select the separate interpreter Codex uses for the bridge. No Codex configuration or production project is modified.
