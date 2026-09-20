# Claude Tools Dashboard

[![CI](https://github.com/Will-Luck/claude-tools-dashboard/actions/workflows/ci.yml/badge.svg)](https://github.com/Will-Luck/claude-tools-dashboard/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/Will-Luck/claude-tools-dashboard)](https://github.com/Will-Luck/claude-tools-dashboard/releases)
[![Licence](https://img.shields.io/github/license/Will-Luck/claude-tools-dashboard)](LICENSE)
[![GHCR](https://img.shields.io/badge/ghcr.io-will--luck%2Fclaude--tools--dashboard-blue?logo=github)](https://github.com/Will-Luck/claude-tools-dashboard/pkgs/container/claude-tools-dashboard)
[![Docker Hub](https://img.shields.io/badge/Docker%20Hub-willluck%2Fclaude--tools--dashboard-blue?logo=docker)](https://hub.docker.com/r/willluck/claude-tools-dashboard)
[![Pulls](https://img.shields.io/endpoint?url=https://pkgbadge.pphserv.uk/Will-Luck/claude-tools-dashboard/pulls.json)](https://github.com/Will-Luck/claude-tools-dashboard/pkgs/container/claude-tools-dashboard)
[![Image Size](https://img.shields.io/endpoint?url=https://pkgbadge.pphserv.uk/Will-Luck/claude-tools-dashboard/size.json)](https://github.com/Will-Luck/claude-tools-dashboard/pkgs/container/claude-tools-dashboard)
[![Platforms](https://img.shields.io/endpoint?url=https://pkgbadge.pphserv.uk/Will-Luck/claude-tools-dashboard/arch.json)](https://github.com/Will-Luck/claude-tools-dashboard/pkgs/container/claude-tools-dashboard)

Live wallboard for monitoring token savings across your Claude Code toolchain. Tracks [RTK](https://github.com/reachingforthejack/rtk), [Headroom](https://github.com/chopratejas/headroom), [jCodeMunch](https://github.com/jgravelle/jcodemunch-mcp), and [jDocMunch](https://github.com/jgravelle/jdocmunch-mcp) in a single-page dashboard with real-time SSE updates.

![Dashboard](screenshots/dashboard-full.png)

## What it shows

- **RTK** -- command-level token savings from the CLI proxy (SQLite)
- **Headroom** -- context compression stats from the MCP server (HTTP API)
- **jCodeMunch** -- indexed repos and session savings (filesystem + MCP)
- **jDocMunch** -- documentation indexing and section retrieval savings (filesystem)
- **jDataMunch** -- indexed datasets and session savings (filesystem + MCP)
- **Combined total** with sparkline trends and live activity feed
- **Stats ticker** -- weekly savings breakdown, daily burn rate, Claude usage percentages (5-hour, weekly, Sonnet), and reset countdown (reads Claude Code credentials directly, no extra tools needed)

## Quick start

```bash
# Clone and run locally
git clone https://github.com/Will-Luck/claude-tools-dashboard.git
cd claude-tools-dashboard
pip install -r requirements.txt
python app.py
# Open http://localhost:8095
```

### Docker (pre-built)

```bash
# Docker Hub
docker run -d --name claude-tools-dashboard \
  -p 8095:8095 \
  -v ~/.local/share/rtk:/root/.local/share/rtk:ro \
  -v ~/.code-index:/root/.code-index:ro \
  -v ~/.doc-index:/root/.doc-index:ro \
  -v ~/.claude/.credentials.json:/root/.claude/.credentials.json:ro \
  --network host \
  willluck/claude-tools-dashboard

# Or from GHCR
docker run -d ... ghcr.io/will-luck/claude-tools-dashboard
```

### Docker (build from source)

```bash
docker build -t claude-tools-dashboard .
docker run -d --name claude-tools-dashboard \
  -p 8095:8095 \
  -v ~/.local/share/rtk:/root/.local/share/rtk:ro \
  -v ~/.code-index:/root/.code-index:ro \
  -v ~/.doc-index:/root/.doc-index:ro \
  -v ~/.claude/.credentials.json:/root/.claude/.credentials.json:ro \
  --network host \
  claude-tools-dashboard
```

Use `--network host` so the container can reach the Headroom proxy on localhost. Alternatively, set `HEADROOM_URL` to point at the host IP. The credentials mount is optional -- without it, the usage ticker just shows dashes.

## Configuration

All settings via environment variables. Copy `.env.example` for reference:

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8095` | Dashboard listen port |
| `HOST` | `0.0.0.0` | Bind address. Set `127.0.0.1` to expose only behind a reverse proxy |
| `HEADROOM_URL` | `http://127.0.0.1:8787` | Headroom proxy stats endpoint |
| `RTK_DB_PATH` | `~/.local/share/rtk/history.db` | RTK SQLite database |
| `RTK_BIN` | `rtk` | Path to RTK binary |
| `JCODEMUNCH_INDEX_DIR` | `~/.code-index` | jCodeMunch index directory |
| `JCODEMUNCH_BIN` | `jcodemunch-mcp` | Path to jCodeMunch binary (version check) |
| `JDOCMUNCH_INDEX_DIR` | `~/.doc-index` | jDocMunch index directory |
| `JDOCMUNCH_BIN` | `jdocmunch-mcp` | Path to jDocMunch binary (version check) |
| `JDATAMUNCH_INDEX_DIR` | `~/.data-index` | jDataMunch index directory |
| `JDATAMUNCH_BIN` | `jdatamunch-mcp` | Path to jDataMunch binary (version check) |
| `SSE_INTERVAL` | `2` | Seconds between SSE heartbeat pushes |
| `COLLECTOR_INTERVAL` | `0.25` | Seconds between background collector ticks |
| `CLAUDE_CREDENTIALS` | `~/.claude/.credentials.json` | Claude Code credentials (for usage API) |
| `WEEKLY_CACHE_DIR` | `~/.cache/claude-tools-dashboard` | Weekly savings snapshot directory |

## API

| Endpoint | Description |
|----------|-------------|
| `GET /` | Dashboard HTML (self-contained SPA) |
| `GET /health` | JSON health check |
| `GET /api/stats` | Current aggregated snapshot as JSON (one-shot, no SSE) |
| `GET /metrics` | Prometheus text exposition (savings, per-tool health, usage, freshness) |
| `GET /events` | SSE stream (auto-reconnects) |

## Architecture

Single-file Flask app (`app.py`) that:

1. Polls RTK's SQLite database for command history and savings
2. Queries Headroom's HTTP stats API for compression data
3. Reads jCodeMunch, jDocMunch, and jDataMunch index files for repo, doc, and dataset metrics
4. Pushes aggregated state to browsers via SSE, and exposes the same snapshot as JSON (`/api/stats`) and Prometheus metrics (`/metrics`)
5. Serves a self-contained HTML/CSS/JS dashboard (no build step)

The frontend uses vanilla JS with CSS custom properties for theming. Sparkline charts are drawn with inline SVG. No external Python dependencies beyond Flask and python-dotenv.

## License

MIT
