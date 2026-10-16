# Codex Token Saver dashboard

The dashboard has five views: **Overview** for request and output savings, **Toolkit** for component preferences, **Activity** for recorded operations and hook coverage, **Updates** for checked runtime upgrades, and **Diagnostics** for the optional CLI proxy and live savings feed. Navigation links support direct bookmarks. Use the appearance button for dark or light mode; the choice is saved only in this browser. Refresh an existing dashboard tab after a UI upgrade; no laptop restart is needed for styling and navigation changes.

Savings windows and current backend compression rates have separate scopes. Estimates from different layers are never added together. Negative local output savings mean net added output, including retrieval costs. Opening or navigating the dashboard does not change component settings or start model inference.

Adapted from [Will-Luck/claude-tools-dashboard](https://github.com/Will-Luck/claude-tools-dashboard), MIT license, commit `289253de78116310d9e682e0680bd8db2a526f14`. Upstream LICENSE is retained. See the [root README](../README.md) for development setup and [Using the bundle](../docs/USING-BUNDLE.md) for the current component controls.

Launch from PowerShell, hidden, without opening a browser:

```powershell
$dashboardRoot = Join-Path $env:USERPROFILE 'CodexTokenSaver\dashboard'
Start-Process -FilePath "$dashboardRoot\.venv\Scripts\pythonw.exe" -ArgumentList 'app.py' -WorkingDirectory $dashboardRoot -WindowStyle Hidden
```

The parent bundle's tray host owns the normal launch and shutdown workflow. Do not start another instance if port 8095 is already occupied. The uv environment's launcher may create a second Python process; use the listener's owning process when diagnosing shutdown.

- Dashboard: `http://127.0.0.1:8095/`
- Liveness: `http://127.0.0.1:8095/health`
- Current snapshot: `http://127.0.0.1:8095/api/stats`
- Live updates: `http://127.0.0.1:8095/events`
- Metrics: `http://127.0.0.1:8095/metrics`

Configuration is loaded from the adjacent `.env`. The server binds only to `127.0.0.1`. Python 3.12 is isolated in `.venv`; `requirements-installed.txt` records installed package versions. The local service uses Flask for a single-user loopback dashboard.

The installed dashboard's `RTK_DB_PATH` points to `%USERPROFILE%\CodexTokenSaver\data\rtk\history.db`, opened through a read-only SQLite URI. Recent and lifetime windows are separate. `records_readable` reports collection success; `recent_use` reports a command within the last five minutes. Neither installation nor readable history establishes current command routing. Test data remains isolated from production telemetry.

The legacy CLI Headroom card reads port 8787. Desktop request compression is a separate managed relay on 8788 with its backend on 8789; local file/command activity has its own SQLite ledger. These counters are intentionally separate and can overlap.

The API returns `rtk`, `desktop_headroom`, legacy `headroom`, and `components` separately. Overall health includes selected components; a readable RTK database cannot hide an unavailable selected request compressor. Component and summary APIs reuse the update API's loopback Host/Origin/CSRF checks. Reads never change routing or start inference. `combined_saved` and `combined_saved_usd` remain null. The dashboard hides upstream aggregate/Claude/account-dollar widgets and does not read account credentials.

See [UI validation](../docs/CONTROL-UI-VALIDATION.md) for automated coverage and the isolated browser fixture. Run the complete dashboard suite from this directory:

```powershell
& .\.venv\Scripts\python.exe -m pytest
```
