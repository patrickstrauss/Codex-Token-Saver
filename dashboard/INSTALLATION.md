# Codex Token Saver dashboard

Installed September 13, 2026 from [Will-Luck/claude-tools-dashboard](https://github.com/Will-Luck/claude-tools-dashboard), MIT license, commit `289253de78116310d9e682e0680bd8db2a526f14`. Upstream LICENSE is retained. Local changes are visible with `git diff app.py`; this is a locally adapted checkout, with no automatic updates.

Launch from PowerShell, hidden, without opening a browser:

```powershell
$dashboardRoot = 'C:\Users\Patcharagit Strauss\AppData\Local\CodexTokenSaver\dashboard'
Start-Process -FilePath "$dashboardRoot\.venv\Scripts\pythonw.exe" -ArgumentList 'app.py' -WorkingDirectory $dashboardRoot -WindowStyle Hidden
```

The parent bundle's tray host owns the normal launch and shutdown workflow. Do not start another instance if port 8095 is already occupied. The uv environment's launcher may create a second Python process; use the listener's owning process when diagnosing shutdown.

- Dashboard: `http://127.0.0.1:8095/`
- Liveness: `http://127.0.0.1:8095/health`
- Current snapshot: `http://127.0.0.1:8095/api/stats`
- Live updates: `http://127.0.0.1:8095/events`
- Metrics: `http://127.0.0.1:8095/metrics`

Configuration is loaded from the adjacent `.env`. The server binds only to `127.0.0.1`. Python 3.12 is isolated in `.venv`; `requirements-installed.txt` records installed package versions. The local service uses Flask for a single-user loopback dashboard.

RTK reads `C:\Users\Patcharagit Strauss\AppData\Local\rtk\history.db` using a SQLite read-only URI. The retained 146-command history already existed before installation, with 10,665 estimated tokens avoided and a weighted output reduction of 11.5%. Installation test data is excluded. RTK values are approximate terminal-output tokens, not account quota or billed savings.

Headroom reads `http://127.0.0.1:8787/health` and `/stats`. Version 0.37 compatibility uses `persistent_savings.lifetime.tokens_saved` for durable compression counts, falling back to `tokens.proxy_compression_saved`, and uses `tokens.proxy_savings_percent` for the session reduction ratio. Tool-schema deferral, cache discounts, and API-equivalent dollars are not combined into the displayed compression number. Only requests routed through that proxy contribute; zero is a valid initial value.

The API returns separate `rtk` and `headroom` objects. For tray text use `rtk.total_saved`, `headroom.total_saved`, and each object's `active`/`health` flags. `headroom.requests_total` reports observed proxy requests. `combined_saved` and `combined_saved_usd` are deliberately null, because tool scopes may overlap. The visual dashboard hides upstream aggregate/Claude/account dollar widgets and unrelated tool cards. Claude credential access and collection are disabled in code, and no Codex credentials are read by this dashboard.

Validation: five focused adapter tests passed, along with 33 upstream command-redaction tests. Live HTTP checks matched RTK CLI counts and verified loopback binding. Browser rendering, live SSE updates, and console errors were checked. Fixture values in the tests are isolated and never written to production telemetry.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_codex_install.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_app.py -q -k Sanitise
```
