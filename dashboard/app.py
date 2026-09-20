"""Codex Token Saver -- Flask backend with SSE streaming."""

import json
import os
import glob
import re
import sqlite3
import subprocess
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

from dotenv import load_dotenv
from flask import Flask, Response, jsonify
from update_routes import register_update_routes
from proxy_routes import PANEL_HTML as REQUEST_PROXY_PANEL_HTML, register_proxy_routes
from component_routes import register_component_routes
from rtk_metrics import window_metrics

load_dotenv(Path(__file__).with_name('.env'))

app = Flask(__name__)

HOME = os.path.expanduser("~")

# Configuration via environment variables
HEADROOM_URL = os.environ.get("HEADROOM_URL", "http://127.0.0.1:8787")
HEADROOM_SAVINGS_PATH = Path(__file__).resolve().parent.parent / "headroom" / "state" / "proxy_savings.json"
HEADROOM_EVENTS_PATH = HEADROOM_SAVINGS_PATH.with_name("savings_events.jsonl")
DESKTOP_HEADROOM_DB_PATH = Path(__file__).resolve().parent.parent / "headroom" / "desktop-state" / "activity.db"
DESKTOP_INTEGRATION_PATH = Path(__file__).resolve().parent.parent / "desktop-integration.json"
AUTOMATIC_HEADROOM_PATH = Path(__file__).resolve().parent.parent / "automatic-headroom.json"
HEADROOM_HOOK_EVENTS_PATH = DESKTOP_HEADROOM_DB_PATH.with_name("hook-events.jsonl")
RTK_DB_PATH = os.environ.get("RTK_DB_PATH", os.path.join(HOME, ".local", "share", "rtk", "history.db"))
RTK_BIN = os.environ.get("RTK_BIN", "rtk")
JCODEMUNCH_INDEX_DIR = os.environ.get("JCODEMUNCH_INDEX_DIR", os.path.join(HOME, ".code-index"))
JCODEMUNCH_BIN = os.environ.get("JCODEMUNCH_BIN", "jcodemunch-mcp")
JDOCMUNCH_INDEX_DIR = os.environ.get("JDOCMUNCH_INDEX_DIR", os.path.join(HOME, ".doc-index"))
JDOCMUNCH_BIN = os.environ.get("JDOCMUNCH_BIN", "jdocmunch-mcp")
JDATAMUNCH_INDEX_DIR = os.environ.get("JDATAMUNCH_INDEX_DIR", os.path.join(HOME, ".data-index"))
JDATAMUNCH_BIN = os.environ.get("JDATAMUNCH_BIN", "jdatamunch-mcp")
PORT = int(os.environ.get("PORT", "8095"))
HOST = os.environ.get("HOST", "127.0.0.1")  # bind address; set 127.0.0.1 to expose only behind a reverse proxy
SSE_INTERVAL = int(os.environ.get("SSE_INTERVAL", "2"))
COLLECTOR_INTERVAL = float(os.environ.get("COLLECTOR_INTERVAL", "5"))
CLAUDE_CREDENTIALS = ""  # Disabled in the Codex installation; no credential reads.
USAGE_API_URL = "https://api.anthropic.com/api/oauth/usage"
USAGE_POLL_INTERVAL = 180  # 3 minutes, same as ccstatusline
USAGE_BACKOFF = 300  # 5 minutes on 429
WEEKLY_CACHE_DIR = os.environ.get("WEEKLY_CACHE_DIR", os.path.join(HOME, ".cache", "claude-tools-dashboard"))

# Persistent state for sparklines and fallback
_last_good = {}
_usage_cache = None
_usage_cache_time = 0
_sparkline_buffers = {
    "rtk": deque(maxlen=60),
    "headroom": deque(maxlen=60),
    "jcodemunch": deque(maxlen=60),
    "jdocmunch": deque(maxlen=60),
    "jdatamunch": deque(maxlen=60),
}
_headroom_last_total = 0
_headroom_history = []
_headroom_disk_cache = {}
_jcodemunch_last_total = 0
_jcodemunch_last_mtime = 0
_jcodemunch_history = []
_jdocmunch_last_total = 0
_jdocmunch_last_mtime = 0
_jdocmunch_history = []
_jdatamunch_last_total = 0
_jdatamunch_last_mtime = 0
_jdatamunch_history = []
_last_collect_success = {
    "rtk": 0.0,
    "headroom": 0.0,
    "jcodemunch": 0.0,
    "jdocmunch": 0.0,
    "jdatamunch": 0.0,
}

# Cached version strings. resolve_versions_once() populates this at module
# import, and the collectors read from it on every tick to avoid subprocess
# on the hot path.
_cached_versions = {
    "rtk": None,
    "jcodemunch": None,
    "jdocmunch": None,
    "jdatamunch": None,
}


def resolve_versions_once():
    """Resolve tool versions once. Called by DashboardCollector.run() at thread startup."""
    rtk_v = _run([RTK_BIN, "--version"])
    _cached_versions["rtk"] = rtk_v if rtk_v else "unknown"



def _run(cmd, timeout=2):
    """Run a command and return stdout, or None on failure."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


_SECRET_PATTERNS = [
    # Existing patterns (unchanged) -----------------------------------------
    (re.compile(r'((?:-e|--env)\s+\S*=)\S+'), r'\1***'),
    (re.compile(r'(\b\w*(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|PASSWD)\s*=)\S+', re.IGNORECASE), r'\1***'),
    (re.compile(r'sk-ant-[A-Za-z0-9_-]{8,}'), 'sk-ant-***'),
    # HTTP Authorization header with scheme (token, Bearer, Basic)
    (re.compile(r'([Aa]uthorization:\s*(?:[Tt]oken|[Bb]earer|[Bb]asic)\s+)\S+'), r'\1***'),
    # Custom X-*-Key or X-*-Token headers (X-API-Key, X-Auth-Token, etc.)
    (re.compile(r'(\b[Xx]-[\w-]*(?:[Kk]ey|[Tt]oken):\s*)\S+'), r'\1***'),
    # curl -u user:password
    (re.compile(r'(\s-u\s+[^\s:]+:)\S+'), r'\1***'),

    # New patterns (2026-04-17 correctness upgrade) -------------------------
    # GitHub token prefixes: ghp_, gho_, ghu_, ghs_, ghr_ + 36+ char body
    (re.compile(r'\bgh[pousr]_[A-Za-z0-9]{36,}\b'), 'ghX_***'),
    # GitLab personal access tokens
    (re.compile(r'\bglpat-[A-Za-z0-9_-]{20,}\b'), 'glpat-***'),
    # Slack tokens: xoxb (bot), xoxp (user), xoxa (admin), xoxr (refresh)
    (re.compile(r'\bxox[bpar]-[A-Za-z0-9-]{10,}\b'), 'xox*-***'),
    # Generalised sk- provider keys (sk-or, sk-OR, sk-proj, sk-live, etc.)
    # More restrictive than ^sk- so we keep the earlier sk-ant specific rule for readability.
    # Provider segment accepts both cases so sk-OR-... is covered.
    (re.compile(r'\bsk-[A-Za-z]{2,}-[A-Za-z0-9_-]{16,}\b'), 'sk-***'),
    # Legacy OpenAI keys: sk-<48+ alphanumeric> with no provider segment.
    # Runs AFTER the two sk- rules above so sk-ant-* and sk-<prov>-* keep their specific replacements.
    (re.compile(r'\bsk-[A-Za-z0-9]{32,}\b'), 'sk-***'),
    # URL-embedded credentials — redact only the password portion
    (re.compile(r'(://[^:/\s@]+:)([^@/\s]+)(@)'), r'\1***\3'),
    # JSON-shaped secret values
    (re.compile(r'("(?:api[_-]?key|access[_-]?token|secret|password)"\s*:\s*")[^"]+(")', re.IGNORECASE), r'\1***\2'),
    # Long hex tokens (naked opaque). 32+ chars catches Gitea/generic opaque tokens.
    # Trade-off accepted: this ALSO redacts full 40-char git SHAs and sha256:... docker
    # image digests as a side effect. Tests pin both behaviours so a future tweak (e.g.
    # adding exclusion anchors like (?<![:@=/])) is a conscious choice rather than a
    # silent regression. 32-char threshold preserves 7- and 8-char git SHAs.
    (re.compile(r'\b[a-f0-9]{32,}\b'), '***'),
]


def _sanitise_cmd(cmd):
    """Redact secrets from shell commands before they reach the frontend."""
    if not cmd:
        return cmd
    for pattern, replacement in _SECRET_PATTERNS:
        cmd = pattern.sub(replacement, cmd)
    return cmd


def collect_rtk():
    """Read rtk SQLite DB and return stats + history."""
    conn = None
    try:
        db_path = RTK_DB_PATH
        if not os.path.exists(db_path):
            return None

        conn = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Aggregate stats
        cur.execute(
            "SELECT COUNT(*) as cnt, "
            "COALESCE(SUM(saved_tokens), 0) as total_saved, "
            "COALESCE(SUM(input_tokens), 0) as total_input, "
            "COALESCE(SUM(output_tokens), 0) as total_output, "
            "COALESCE(SUM(exec_time_ms), 0) as total_time "
            "FROM commands"
        )
        row = cur.fetchone()
        total_commands = row["cnt"]
        total_saved = row["total_saved"]
        avg_savings_pct = round(100 * total_saved / row["total_input"], 1) if row["total_input"] else 0
        total_time_ms = row["total_time"]

        # Last 100 entries for history
        cur.execute(
            "SELECT timestamp, original_cmd, saved_tokens, savings_pct "
            "FROM commands ORDER BY id DESC LIMIT 100"
        )
        history = []
        for r in cur.fetchall():
            cmd = r["original_cmd"]
            if cmd.startswith("rtk "):
                cmd = cmd[4:]
            cmd = _sanitise_cmd(cmd)
            # Encoded scripts are unreadable in the activity list; keep the command label.
            cmd = re.sub(r'(?i)(-encodedcommand\s+)\S+', r'\1[script]', cmd)
            if len(cmd) > 240:
                cmd = cmd[:237] + "..."
            history.append({
                "time": r["timestamp"],
                "tool": "rtk",
                "cmd": cmd,
                "saved_pct": round(r["savings_pct"], 1),
                "saved_tokens": r["saved_tokens"],
            })

        windows = window_metrics(conn)

        # Version (cached at startup)
        version = _cached_versions.get("rtk") or "unknown"

        return {
            "active": windows['recent_use'],
            "records_readable": True,
            "recent_use": windows['recent_use'],
            "last_recorded_at": windows['last_recorded_at'],
            "collected_at": windows['collected_at'],
            "windows": {key: windows[key] for key in ('today', 'seven_days', 'lifetime')},
            "total_saved": total_saved,
            "total_commands": total_commands,
            "total_input": row["total_input"],
            "total_output": row["total_output"],
            "measurement": "Estimated terminal-output tokens avoided (RTK characters / 4). Historical local records; not subscription quota or billing.",
            "avg_savings_pct": avg_savings_pct,
            "total_time_ms": total_time_ms,
            "version": version or "unknown",
            "history": history,
        }
    except Exception:
        return None
    finally:
        if conn is not None:
            conn.close()


_HEADROOM_SKIP_LABELS = {
    "disabled": "local output filtering is Off",
    "invalid_preferences": "component preferences could not be read",
    "complex_syntax": "scripts, pipelines or unsupported syntax",
    "ambiguous_shell": "command path or shell is ambiguous",
    "dynamic_input": "variables or computed arguments",
    "unsupported_command": "command or output format is not supported",
    "exact_opt_out": "exact output requested",
    "already_wrapped": "already using Headroom",
    "missing_runtime": "Headroom runtime is missing",
    "missing_executable": "command executable is missing",
    "oversized_input": "command text exceeds the limit",
    "parse_error": "command syntax could not be parsed",
    "invalid_input": "invalid hook input",
    "unsupported_event": "unsupported hook event",
    "other": "other or unknown reason",
}

_update_routes = register_update_routes(app, Path(__file__).resolve().parent.parent, PORT, _cached_versions)
register_proxy_routes(app, Path(__file__).resolve().parent.parent, _update_routes)
collect_components = register_component_routes(app, Path(__file__).resolve().parent.parent, _update_routes,
                                               observations=lambda: _collector.snapshot() or {})


def collect_headroom_automation():
    """Bounded local observations; registration never claims trust or liveness."""
    data = {"configured": False, "status": "not_configured", "data_status": "empty", "observed": 0,
            "rewritten": 0, "skipped": 0, "skip_reasons": {}, "top_skip_reasons": [],
            "last_observed_at": None, "recent_window_only": True}
    try:
        receipt = json.loads(AUTOMATIC_HEADROOM_PATH.read_text(encoding="utf-8-sig"))
        data["configured"] = receipt.get("configured") is True and receipt.get("hook") == "headroom_commands"
    except (OSError, ValueError, AttributeError):
        pass
    if data["configured"]:
        data["status"] = "awaiting_first_event"
    try:
        with HEADROOM_HOOK_EVENTS_PATH.open("rb") as stream:
            stream.seek(0, 2)
            offset = max(0, stream.tell() - 256 * 1024)
            stream.seek(offset)
            if offset:
                stream.readline()
            lines = stream.read().decode("utf-8-sig", errors="replace").splitlines()
        for line in lines:
            try:
                event = json.loads(line)
                if event.get("outcome") not in ("rewritten", "skipped"):
                    continue
                data["observed"] += 1
                data["rewritten"] += event["outcome"] == "rewritten"
                if event["outcome"] == "skipped":
                    data["skipped"] += 1
                    reason = event.get("reason")
                    if not isinstance(reason, str) or reason not in _HEADROOM_SKIP_LABELS:
                        reason = "other"
                    data["skip_reasons"][reason] = data["skip_reasons"].get(reason, 0) + 1
                data["last_observed_at"] = event.get("timestamp") or event.get("ts")
            except (ValueError, AttributeError):
                continue
        if data["observed"]:
            data["status"] = "observed"
            data["data_status"] = "recorded"
        data["top_skip_reasons"] = [
            {"reason": reason, "label": _HEADROOM_SKIP_LABELS[reason], "count": count}
            for reason, count in sorted(data["skip_reasons"].items(), key=lambda item: (-item[1], item[0]))[:3]
        ]
    except FileNotFoundError:
        pass
    except OSError:
        data.update({"data_status": "unavailable", "observed": None, "rewritten": None, "skipped": None})
    return data


_HEADROOM_COMMAND_STATUSES = {
    'disabled',
    'compressed', 'small_output', 'no_reduction', 'command_failed',
    'compression_unavailable', 'exact_requested', 'size_limit', 'binary_output', 'non_utf8',
    'compression_timeout', 'streaming_timeout', 'inherited_pipe', 'interactive_passthrough',
}


def collect_desktop_headroom():
    """Read desktop tool counters; registration and history do not prove liveness."""
    configured = False
    try:
        receipt = json.loads(DESKTOP_INTEGRATION_PATH.read_text(encoding="utf-8-sig"))
        configured = isinstance(receipt, dict) and receipt.get("configured") is True and receipt.get("server") == "headroom_desktop"
    except (OSError, ValueError):
        pass

    data = {
        "configured": configured,
        "data_status": "empty",
        "total_saved": 0,
        "gross_saved": 0,
        "retrieval_tokens": 0,
        "read_count": 0,
        "command_count": 0,
        "command_saved": 0,
        "command_attempt_count": 0,
        "last_command_status": None,
        "last_command_check": None,
        "command_statuses": {},
        "retrieve_count": 0,
        "last_recorded_at": None,
        "source": "headroom/desktop-state/activity.db",
        "coverage": "This counter covers local files and selected command outputs; request savings are tracked separately below.",
        "measurement": "Local file/stdout reduction estimate, before Codex truncation. Includes returned text and retrieval costs; not account usage or billing.",
        "automation": collect_headroom_automation(),
    }
    conn = None
    try:
        if not DESKTOP_HEADROOM_DB_PATH.exists():
            return data
        conn = sqlite3.connect(DESKTOP_HEADROOM_DB_PATH.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT COUNT(*) AS event_count, "
            "COALESCE(SUM(saved_tokens), 0) AS total_saved, "
            "COALESCE(SUM(CASE WHEN kind IN ('read', 'command') AND saved_tokens > 0 THEN saved_tokens ELSE 0 END), 0) AS gross_saved, "
            "COALESCE(SUM(CASE WHEN kind = 'retrieve' THEN output_tokens ELSE 0 END), 0) AS retrieval_tokens, "
            "COALESCE(SUM(CASE WHEN kind = 'read' THEN 1 ELSE 0 END), 0) AS read_count, "
            "COALESCE(SUM(CASE WHEN kind = 'command' THEN 1 ELSE 0 END), 0) AS command_count, "
            "COALESCE(SUM(CASE WHEN kind = 'command' THEN saved_tokens ELSE 0 END), 0) AS command_saved, "
            "COALESCE(SUM(CASE WHEN kind = 'retrieve' THEN 1 ELSE 0 END), 0) AS retrieve_count, "
            "MAX(ts) AS last_recorded_at FROM events"
        ).fetchone()
        data.update({key: row[key] for key in ("total_saved", "gross_saved", "retrieval_tokens", "read_count", "command_count", "command_saved", "retrieve_count", "last_recorded_at")})
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='command_attempts'").fetchone():
            data["command_attempt_count"] = conn.execute("SELECT COUNT(*) FROM command_attempts").fetchone()[0]
            latest = conn.execute("SELECT status, ts FROM command_attempts ORDER BY id DESC LIMIT 1").fetchone()
            if latest:
                data["last_command_status"] = latest[0] if latest[0] in _HEADROOM_COMMAND_STATUSES else "other"
                data["last_command_check"] = latest[1]
            for status, count in conn.execute("SELECT status, COUNT(*) FROM command_attempts GROUP BY status"):
                status = status if status in _HEADROOM_COMMAND_STATUSES else "other"
                data["command_statuses"][status] = data["command_statuses"].get(status, 0) + count
        data["data_status"] = "recorded" if row["event_count"] else "empty"
    except (OSError, sqlite3.Error, ValueError):
        data.update({key: None for key in ("total_saved", "gross_saved", "retrieval_tokens", "read_count", "command_count", "command_saved", "command_attempt_count", "retrieve_count")})
        data["data_status"] = "unavailable"
        data.update({"last_command_status": None, "last_command_check": None, "command_statuses": {}})
    finally:
        if conn is not None:
            conn.close()
    return data


def _headroom_recorded_savings():
    """Read the bundle's counters only; never load Headroom or app credentials."""
    global _headroom_disk_cache
    for path in (HEADROOM_SAVINGS_PATH, HEADROOM_EVENTS_PATH):
        try:
            stat = path.stat()
            fingerprint = (str(path), stat.st_mtime_ns, stat.st_size)
            if _headroom_disk_cache.get("fingerprint") == fingerprint:
                return dict(_headroom_disk_cache["data"])
            recorded_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
            if path == HEADROOM_SAVINGS_PATH:
                with path.open(encoding="utf-8") as stream:
                    raw = json.load(stream)
                lifetime = raw["lifetime"]
                saved = lifetime["tokens_saved"]
                requests = lifetime.get("requests", 0)
                if not isinstance(saved, (int, float)) or isinstance(saved, bool) or saved < 0:
                    continue
                recorded_at = ((raw.get("lifetime_metrics") or {}).get("persistence") or {}).get("last_saved_at") or recorded_at
            else:
                saved, requests = 0, 0
                # Cache unchanged logs. Stream changed logs to avoid retaining their contents.
                with path.open(encoding="utf-8") as stream:
                    for line in stream:
                        try:
                            event = json.loads(line)
                            amount = event.get("saved")
                            if (event.get("source") != "proxy" or not isinstance(amount, (int, float))
                                    or isinstance(amount, bool) or amount < 0):
                                continue
                            saved += amount
                            requests += 1
                            recorded_at = event.get("ts") or recorded_at
                        except (json.JSONDecodeError, AttributeError):
                            continue  # A concurrent append may leave an incomplete last line.
                if not requests:
                    continue
            data = {
                "total_saved": saved, "lifetime_saved": saved,
                "lifetime_requests": requests, "source": path.name,
                "last_recorded_at": recorded_at,
            }
            _headroom_disk_cache = {"fingerprint": fingerprint, "data": data}
            return dict(data)
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            continue
    return None


def _headroom_offline(version="unknown"):
    data = _headroom_recorded_savings()
    if data is None and _last_good.get("headroom", {}).get("total_saved") is not None:
        previous = _last_good["headroom"]
        data = {key: previous.get(key) for key in (
            "total_saved", "lifetime_saved", "lifetime_requests", "last_recorded_at")}
        data["source"] = "last_live_snapshot"
    historical = data is not None
    return {
        **(data or {"total_saved": None, "last_recorded_at": None, "source": None}),
        "active": False, "optional": True, "health": "inactive", "version": version,
        "data_status": "historical" if historical else "unavailable",
        "measurement": "Historical Headroom proxy records; proxy offline. These records do not establish current Codex desktop compression.",
        "history": [],
    }


def collect_headroom():
    """Check headroom proxy stats endpoint."""
    try:
        # Get version from /health (fast) instead of CLI (3.6s ONNX init)
        version = "unknown"
        try:
            hresp = urlopen(f"{HEADROOM_URL}/health", timeout=2)
            hdata = json.loads(hresp.read().decode())
            version = hdata.get("version", "unknown")
        except (URLError, OSError, json.JSONDecodeError):
            pass  # An optional proxy being stopped is normal.

        try:
            resp = urlopen(f"{HEADROOM_URL}/stats", timeout=2)
            data = json.loads(resp.read().decode())

            # Headroom exposes both session and lifetime metrics. Session tokens reset
            # on inactivity (rollover_inactivity_minutes=60 by default) so display_session
            # rarely matches the headline value users expect. Use lifetime as primary.
            tokens = data.get("tokens", {})
            cache = data.get("compression_cache", {})
            lifetime = data.get("persistent_savings", {}).get("lifetime", {}) or {}
            prefix_totals = data.get("prefix_cache", {}).get("totals", {}) or {}

            data["active"] = True
            data["optional"] = True
            data["data_status"] = "live"
            data["source"] = "proxy_stats"
            data["last_recorded_at"] = datetime.now(timezone.utc).isoformat()
            data["version"] = version or "unknown"

            lifetime_saved = lifetime.get("tokens_saved", 0) or 0
            session_saved = tokens.get("proxy_compression_saved", tokens.get("saved", 0)) or 0
            data["total_saved"] = lifetime_saved if lifetime_saved > 0 else session_saved
            data["session_saved"] = session_saved
            data["lifetime_saved"] = lifetime_saved
            data["lifetime_savings_usd"] = round(lifetime.get("compression_savings_usd", 0) or 0, 2)
            data["lifetime_requests"] = lifetime.get("requests", 0) or 0
            data["requests_total"] = (data.get("requests") or {}).get("total", 0)
            data["measurement"] = "Headroom-reported reductions for requests sent to this optional proxy. A running proxy does not establish Codex desktop routing; not billed savings or ChatGPT quota."

            # Prefix cache stats are SDK/provider-side hits (cache_read_tokens). Headroom
            # surfaces them so we can attribute the dollar discount.
            data["cache_hit_rate"] = prefix_totals.get("hit_rate")
            data["cache_savings_usd"] = round(prefix_totals.get("savings_usd", 0) or 0, 2)

            data["sessions"] = cache.get("active_sessions", 0)
            data["avg_savings_pct"] = round(tokens.get("proxy_savings_percent", tokens.get("savings_percent", 0)), 1)
            data["compression_ratio"] = data["avg_savings_pct"]

            # Sparkline uses session deltas (current activity), not lifetime.
            global _headroom_last_total, _headroom_history
            current_total = session_saved
            if _headroom_last_total > 0 and current_total > _headroom_last_total:
                delta = current_total - _headroom_last_total
                _headroom_history.append({
                    "time": datetime.now(timezone.utc).isoformat(),
                    "tool": "headroom",
                    "cmd": f"compressed {delta:,} tokens",
                    "saved_tokens": delta,
                    "saved_pct": data["avg_savings_pct"],
                })
                _headroom_history = _headroom_history[-100:]
            _headroom_last_total = current_total
            data["history"] = list(_headroom_history)

            return data
        except (URLError, OSError, json.JSONDecodeError):
            return _headroom_offline(version or "unknown")
    except Exception:
        return _headroom_offline()


def collect_jcodemunch():
    """Read jcodemunch savings and index stats."""
    try:
        index_dir = JCODEMUNCH_INDEX_DIR
        if not os.path.isdir(index_dir):
            return None

        savings_path = os.path.join(index_dir, "_savings.json")
        total_tokens_saved = 0
        if os.path.exists(savings_path):
            with open(savings_path) as f:
                data = json.load(f)
            total_tokens_saved = data.get("total_tokens_saved", 0)

        # Count .db files and sum sizes
        db_files = glob.glob(os.path.join(index_dir, "*.db"))
        repos_indexed = len(db_files)
        index_size_bytes = sum(os.path.getsize(f) for f in db_files if os.path.exists(f))
        index_size_mb = round(index_size_bytes / (1024 * 1024), 1)

        version = _cached_versions.get("jcodemunch") or "unknown"

        # Detect activity via the newest mtime across session_stats.json, _savings.json,
        # and all per-repo .db files. jcodemunch-mcp flushes these at different times
        # (neither file updates on every MCP call), so watching the max catches more events.
        global _jcodemunch_last_total, _jcodemunch_last_mtime, _jcodemunch_history
        stats_path = os.path.join(index_dir, "session_stats.json")
        watched_paths = [stats_path, savings_path, *db_files]
        newest_mtime = max(
            (os.path.getmtime(p) for p in watched_paths if os.path.exists(p)),
            default=0,
        )
        if newest_mtime > _jcodemunch_last_mtime and _jcodemunch_last_mtime > 0:
            if total_tokens_saved > _jcodemunch_last_total and _jcodemunch_last_total > 0:
                delta = total_tokens_saved - _jcodemunch_last_total
                _jcodemunch_history.append({
                    "time": datetime.now(timezone.utc).isoformat(),
                    "tool": "jcodemunch",
                    "cmd": f"indexed/queried -- saved {delta:,} tokens",
                    "saved_tokens": delta,
                    "saved_pct": 0,
                })
            else:
                _jcodemunch_history.append({
                    "time": datetime.now(timezone.utc).isoformat(),
                    "tool": "jcodemunch",
                    "cmd": f"query across {repos_indexed} repos ({index_size_mb}MB indexed)",
                    "saved_tokens": 0,
                    "saved_pct": 0,
                })
            _jcodemunch_history = _jcodemunch_history[-100:]
        _jcodemunch_last_mtime = newest_mtime
        _jcodemunch_last_total = total_tokens_saved

        # Freshness: 100% if active in last 5 min, decays to 0% over 60 min
        if newest_mtime > 0:
            elapsed_min = (time.time() - newest_mtime) / 60
            freshness = max(0, round(100 - (elapsed_min / 60 * 100)))
        else:
            freshness = 0

        if freshness > 0:
            if elapsed_min < 1:
                freshness_label = "just now"
            elif elapsed_min < 60:
                freshness_label = f"{int(elapsed_min)}m ago"
            else:
                freshness_label = f"{int(elapsed_min / 60)}h ago"
        else:
            freshness_label = "idle"

        return {
            "active": repos_indexed > 0 or total_tokens_saved > 0,
            "total_saved": total_tokens_saved,
            "repos_indexed": repos_indexed,
            "index_size_mb": index_size_mb,
            "version": version or "unknown",
            "history": list(_jcodemunch_history),
            "freshness": freshness,
            "freshness_label": freshness_label,
        }
    except Exception:
        return None


def collect_jdatamunch():
    global _jdatamunch_last_total, _jdatamunch_last_mtime, _jdatamunch_history
    try:
        index_dir = JDATAMUNCH_INDEX_DIR
        if not os.path.isdir(index_dir):
            return {
                "active": False,
                "total_saved": 0,
                "datasets_indexed": 0,
                "index_size_mb": 0,
                "version": _cached_versions.get("jdatamunch") or "unknown",
                "history": [],
                "freshness": 0,
                "freshness_label": "no datasets yet",
            }

        savings_path = os.path.join(index_dir, "_savings.json")
        total_tokens_saved = 0
        if os.path.exists(savings_path):
            with open(savings_path) as f:
                data = json.load(f)
            total_tokens_saved = data.get("total_tokens_saved", 0)

        index_files = glob.glob(os.path.join(index_dir, "local", "*.json"))
        index_files += glob.glob(os.path.join(index_dir, "*.db"))
        datasets_indexed = len(index_files)
        index_size_mb = round(sum(os.path.getsize(f) for f in index_files if os.path.exists(f)) / (1024 * 1024), 1)

        version = _cached_versions.get("jdatamunch") or "unknown"

        savings_mtime = os.path.getmtime(savings_path) if os.path.exists(savings_path) else 0
        idx_mtime = max(
            (os.path.getmtime(f) for f in index_files if os.path.exists(f)),
            default=0,
        )
        newest_mtime = max(savings_mtime, idx_mtime)

        if newest_mtime > _jdatamunch_last_mtime and _jdatamunch_last_mtime > 0:
            delta = total_tokens_saved - _jdatamunch_last_total
            if delta > 0:
                _jdatamunch_history.append({
                    "time": datetime.now(timezone.utc).isoformat(),
                    "tool": "jdatamunch",
                    "cmd": f"indexed/queried -- saved {delta:,} tokens",
                    "saved_tokens": delta,
                    "saved_pct": 0,
                })
            else:
                _jdatamunch_history.append({
                    "time": datetime.now(timezone.utc).isoformat(),
                    "tool": "jdatamunch",
                    "cmd": f"query across {datasets_indexed} datasets ({index_size_mb}MB indexed)",
                    "saved_tokens": 0,
                    "saved_pct": 0,
                })
            _jdatamunch_history = _jdatamunch_history[-100:]
        _jdatamunch_last_mtime = newest_mtime
        _jdatamunch_last_total = total_tokens_saved

        if newest_mtime > 0:
            elapsed_min = (time.time() - newest_mtime) / 60
            freshness = max(0, round(100 - (elapsed_min / 60 * 100)))
        else:
            freshness = 0

        if freshness > 0:
            if elapsed_min < 1:
                freshness_label = "just now"
            elif elapsed_min < 60:
                freshness_label = f"{int(elapsed_min)}m ago"
            else:
                freshness_label = f"{int(elapsed_min / 60)}h ago"
        else:
            freshness_label = "idle"

        return {
            "active": datasets_indexed > 0 or total_tokens_saved > 0,
            "total_saved": total_tokens_saved,
            "datasets_indexed": datasets_indexed,
            "index_size_mb": index_size_mb,
            "version": version,
            "history": list(_jdatamunch_history),
            "freshness": freshness,
            "freshness_label": freshness_label,
        }
    except Exception:
        return None


def collect_jdocmunch():
    global _jdocmunch_last_total, _jdocmunch_last_mtime, _jdocmunch_history
    try:
        index_dir = JDOCMUNCH_INDEX_DIR
        if not os.path.isdir(index_dir):
            return None

        savings_path = os.path.join(index_dir, "_savings.json")
        total_tokens_saved = 0
        if os.path.exists(savings_path):
            with open(savings_path) as f:
                data = json.load(f)
            total_tokens_saved = data.get("total_tokens_saved", 0)

        index_files = [f for f in glob.glob(os.path.join(index_dir, "local", "*.json"))]
        docs_indexed = len(index_files)
        index_size_mb = round(sum(os.path.getsize(f) for f in index_files) / (1024 * 1024), 1)

        # Version (cached at startup)
        version = _cached_versions.get("jdocmunch") or "unknown"

        # _savings.json updates on every get_section call (token savings).
        # Index JSON files update on re-index. Check both for activity.
        savings_mtime = os.path.getmtime(savings_path) if os.path.exists(savings_path) else 0
        idx_mtime = max(
            (os.path.getmtime(f) for f in index_files),
            default=0,
        )
        newest_mtime = max(savings_mtime, idx_mtime)

        if newest_mtime > _jdocmunch_last_mtime and _jdocmunch_last_mtime > 0:
            delta = total_tokens_saved - _jdocmunch_last_total
            if delta > 0:
                _jdocmunch_history.append({
                    "time": datetime.now(timezone.utc).isoformat(),
                    "tool": "jdocmunch",
                    "cmd": f"indexed/queried -- saved {delta:,} tokens",
                    "saved_tokens": delta,
                    "saved_pct": 0,
                })
            else:
                _jdocmunch_history.append({
                    "time": datetime.now(timezone.utc).isoformat(),
                    "tool": "jdocmunch",
                    "cmd": f"query across {docs_indexed} docs ({index_size_mb}MB indexed)",
                    "saved_tokens": 0,
                    "saved_pct": 0,
                })
            _jdocmunch_history = _jdocmunch_history[-100:]
        _jdocmunch_last_mtime = newest_mtime
        _jdocmunch_last_total = total_tokens_saved

        # Freshness: 100% if active in last 5 min, decays to 0% over 60 min
        if newest_mtime > 0:
            elapsed_min = (time.time() - newest_mtime) / 60
            freshness = max(0, round(100 - (elapsed_min / 60 * 100)))
        else:
            freshness = 0

        if freshness > 0:
            if elapsed_min < 1:
                freshness_label = "just now"
            elif elapsed_min < 60:
                freshness_label = f"{int(elapsed_min)}m ago"
            else:
                freshness_label = f"{int(elapsed_min / 60)}h ago"
        else:
            freshness_label = "idle"

        return {
            "active": docs_indexed > 0 or total_tokens_saved > 0,
            "total_saved": total_tokens_saved,
            "docs_indexed": docs_indexed,
            "index_size_mb": index_size_mb,
            "version": version,
            "history": list(_jdocmunch_history),
            "freshness": freshness,
            "freshness_label": freshness_label,
        }
    except Exception:
        return None


def _read_oauth_token():
    """Credential access is disabled in this Codex installation."""
    return None


def _reset_in_future(iso_ts):
    """True iff iso_ts is a parseable ISO-8601 timestamp strictly in the future (UTC).

    Used to decide whether a cached pct/reset pair still refers to a live window.
    Anthropic rate-limits the usage endpoint and we serve stale cache on 429/network
    errors; once the reset timestamp has passed, the cached utilisation refers to a
    dead window and must be scrubbed before it reaches the UI.
    """
    if not iso_ts:
        return False
    try:
        return datetime.fromisoformat(iso_ts) > datetime.now(timezone.utc)
    except (ValueError, TypeError):
        return False


# Single source of truth for Anthropic usage windows. Each tuple is
# (pct_key, reset_key, api_block) — the API block name is the key on the
# /oauth/usage response that carries the window's utilisation + resets_at.
# Adding a fourth window (monthly, etc.) requires one edit here; both
# collect_claude_usage and _scrub_stale_windows consume this constant.
_USAGE_WINDOW_KEYS = (
    ("session_pct", "session_reset", "five_hour"),
    ("weekly_pct", "weekly_reset", "seven_day"),
    ("sonnet_pct", "sonnet_reset", "seven_day_sonnet"),
)


def _scrub_stale_windows(usage):
    """Null out pct+reset pairs whose reset has passed. Mutates in place and returns usage.

    Prevents the ghost-window bug: when Anthropic rate-limits /oauth/usage, collect_claude_usage
    serves stale cache. Once the reset timestamp has passed, the cached utilisation is
    meaningless and must be scrubbed before it reaches the UI.

    Intentionally sets reset_key to None once the window expires — collect_all's weekly
    rotation keys off weekly_reset and will not rotate when it is None. That is the
    correct behaviour: a dead window must not rotate a baseline it can no longer verify.
    Callers needing rotation must read from a live (unscrubbed) source.

    Idempotent: a second call on an already-scrubbed dict is a no-op.
    """
    if usage is None:
        return None
    for pct_key, reset_key, _api_block in _USAGE_WINDOW_KEYS:
        if usage.get(reset_key) and not _reset_in_future(usage[reset_key]):
            # Only null pct_key if it was present — preserves absence symmetry
            # (reset absent + pct present leaves pct untouched; reset present +
            # pct absent should leave pct absent rather than materialising it).
            if pct_key in usage:
                usage[pct_key] = None
            usage[reset_key] = None
    return usage


def _scrubbed_cache_snapshot():
    """Return a scrubbed COPY of _usage_cache (never mutates the shared dict).

    Defence-in-depth against partial-snapshot reads from concurrent threads:
    scrub runs over a fresh dict so readers never observe _usage_cache mid-scrub.
    """
    if _usage_cache is None:
        return None
    return _scrub_stale_windows(dict(_usage_cache))


def _usage_from_headroom():
    """Read subscription window from Headroom /stats — no OAuth, no 429 risk.

    Headroom polls /oauth/usage and caches the result. When Headroom is reachable
    we prefer its cached snapshot over a direct API call: no token required and
    the 429 budget stays untouched.
    """
    try:
        resp = urlopen(f"{HEADROOM_URL}/stats", timeout=2)
        data = json.loads(resp.read().decode())
        latest = (data.get("subscription_window") or {}).get("latest") or {}
        if not latest:
            return None
        result = {"active": True, "source": "headroom"}
        for pct_key, reset_key, api_block in _USAGE_WINDOW_KEYS:
            block = latest.get(api_block) or {}
            # Headroom mirrors the API field as utilization_pct (renamed) — fall back
            # to utilization for older Headroom builds.
            pct = block.get("utilization_pct")
            if pct is None:
                pct = block.get("utilization")
            result[pct_key] = pct
            result[reset_key] = block.get("resets_at")
        # Result is meaningful only if at least one window has a percentage.
        if any(result.get(k) is not None for k, _, _ in _USAGE_WINDOW_KEYS):
            return result
        return None
    except (URLError, OSError, json.JSONDecodeError, KeyError):
        return None


def collect_claude_usage():
    """Claude account usage is not collected by this Codex installation."""
    return None


def _load_weekly_cache():
    """Load weekly savings snapshot from disk."""
    path = os.path.join(WEEKLY_CACHE_DIR, "weekly.json")
    try:
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_weekly_cache(data):
    """Save weekly savings snapshot to disk atomically.

    Writes a temp file in the same directory then os.replace()s it onto
    weekly.json. A crash or container stop mid-write can therefore never leave
    a truncated file: _load_weekly_cache would discard a corrupt file and
    return {}, silently resetting the weekly baseline and last-week total.
    """
    os.makedirs(WEEKLY_CACHE_DIR, exist_ok=True)
    path = os.path.join(WEEKLY_CACHE_DIR, "weekly.json")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _group_history(entries):
    """Collapse consecutive same-tool, same-prefix entries within 10s."""
    if not entries:
        return entries

    grouped = []
    i = 0
    while i < len(entries):
        entry = entries[i]
        # Never collapse entries that saved >1000 tokens
        if entry.get("saved_tokens", 0) > 1000:
            grouped.append(entry)
            i += 1
            continue

        # Extract command prefix (first word)
        cmd_parts = (entry.get("cmd") or "").split()
        prefix = cmd_parts[0] if cmd_parts else ""
        tool = entry.get("tool", "")
        entry_time = entry.get("time", "")

        # Collect consecutive entries with same tool + prefix within 10s
        batch = [entry]
        j = i + 1
        while j < len(entries):
            next_entry = entries[j]
            # Don't absorb high-savings entries into a group
            if next_entry.get("saved_tokens", 0) > 1000:
                break
            next_parts = (next_entry.get("cmd") or "").split()
            next_prefix = next_parts[0] if next_parts else ""
            next_tool = next_entry.get("tool", "")

            if next_tool != tool or next_prefix != prefix:
                break

            # Check time gap (entries are sorted descending, so earlier entries are later in list)
            try:
                t1 = datetime.fromisoformat(entry_time)
                t2 = datetime.fromisoformat(next_entry.get("time", ""))
                if abs((t1 - t2).total_seconds()) > 10:
                    break
            except (ValueError, TypeError):
                break

            batch.append(next_entry)
            j += 1

        if len(batch) == 1:
            grouped.append(entry)
        else:
            total_saved = sum(e.get("saved_tokens", 0) for e in batch)
            total_pct_weighted = 0
            total_weight = 0
            for e in batch:
                s = e.get("saved_tokens", 0)
                total_pct_weighted += e.get("saved_pct", 0) * max(s, 1)
                total_weight += max(s, 1)
            avg_pct = round(total_pct_weighted / total_weight, 1) if total_weight > 0 else 0

            grouped.append({
                "time": batch[0].get("time"),
                "tool": tool,
                "cmd": f"{len(batch)}x {prefix}",
                "saved_tokens": total_saved,
                "saved_pct": avg_pct,
                "count": len(batch),
                "grouped": True,
            })

        i = j

    return grouped


def collect_all():
    """Collect from all tools, maintain sparklines and fallbacks."""
    global _last_good

    collectors = {
        "rtk": collect_rtk,
        "headroom": collect_headroom,
    }

    results = {}
    for name, fn in collectors.items():
        data = fn()
        if data is not None:
            results[name] = dict(data)
            if data.get("records_readable", data.get("active")):
                _last_good[name] = dict(data)
                _last_collect_success[name] = time.time()
        else:
            results[name] = dict(_last_good.get(name, {"version": "unknown", "total_saved": None, "history": []}))
            results[name]["active"] = False
            results[name]["records_readable"] = False
            results[name]["data_status"] = "historical" if name in _last_good else "unavailable"

    now_ts = time.time()
    for name in collectors:
        last_ok = _last_collect_success.get(name, 0)
        if name == "headroom" and not results[name].get("active"):
            results[name]["health"] = "inactive"
            results[name]["optional"] = True
        elif results[name].get("records_readable", results[name].get("active")) and last_ok > 0 and (now_ts - last_ok) < 60:
            results[name]["health"] = "ok"
        elif last_ok > 0:
            results[name]["health"] = "stale"
        else:
            results[name]["health"] = "error"

    # Collector health describes readable measurements, not active compression.
    overall_health = results["rtk"].get("health", "error")
    desktop_headroom = collect_desktop_headroom()
    try:
        components = collect_components({'rtk': results['rtk'], 'desktop_headroom': desktop_headroom})
        overall_health = components.get('overall_health') or overall_health
    except Exception:
        components = {'components': [], 'overall_health': 'error', 'error': 'Component status could not be read.'}
        overall_health = 'error'

    # Claude-account weekly tracking and combined sums are unsupported in Codex.
    # Keep the JSON fields null for older clients, without reading/writing a cache.

    # Update sparkline buffers with cumulative totals
    now = time.time()
    for name in collectors:
        tool_data = results[name]
        if not tool_data.get("active"):
            continue
        cumulative = tool_data.get("total_saved", 0)
        _sparkline_buffers[name].append((now, cumulative))

    # Compute deltas and sparkline points
    sparklines = {}
    for name in collectors:
        buf = _sparkline_buffers[name]
        entries = list(buf)

        # Delta: diff of last 2 entries
        if len(entries) >= 2:
            delta = entries[-1][1] - entries[-2][1]
        else:
            delta = 0

        # Sparkline points: diffs of consecutive entries
        points = []
        for i in range(1, len(entries)):
            points.append(entries[i][1] - entries[i - 1][1])

        sparklines[name] = {
            "delta": delta if results[name].get("active") else 0,
            "points": points if results[name].get("active") else [],
        }

    # Merge history from all tools that have it
    history = []
    if "history" in results.get("rtk", {}):
        history.extend(results["rtk"]["history"])
    if "history" in results.get("headroom", {}):
        history.extend(results["headroom"]["history"])
    if "history" in results.get("jcodemunch", {}):
        history.extend(results["jcodemunch"]["history"])
    if "history" in results.get("jdocmunch", {}):
        history.extend(results["jdocmunch"]["history"])
    if "history" in results.get("jdatamunch", {}):
        history.extend(results["jdatamunch"]["history"])

    # Sort by time descending, collapse bursts, limit to 100
    history.sort(key=lambda x: x.get("time", ""), reverse=True)
    history = _group_history(history)
    history = history[:100]

    timestamp = datetime.now(timezone.utc).isoformat()

    return {
        "timestamp": timestamp,
        "combined_saved": None,
        "combined_saved_usd": None,
        "measurement_note": "RTK output estimates and Headroom context reductions have different scopes and may overlap. Do not add them or interpret them as billed savings or subscription quota.",
        "connection_note": "Headroom request compression handles eligible content across Codex model requests when enabled below. RTK and local Headroom tools provide additional output reduction.",
        "overall_health": overall_health,
        "components": components,
        "rtk": results["rtk"],
        "headroom": results["headroom"],
        "desktop_headroom": desktop_headroom,
        "jcodemunch": {"active": False, "disabled": True},
        "jdocmunch": {"active": False, "disabled": True},
        "jdatamunch": {"active": False, "disabled": True},
        "sparklines": sparklines,
        "history": history,
        "claude_usage": {"active": False, "disabled": True},
        "weekly": {
            "this_week": None,
            "last_week": None,
            "burn_rate_daily": None,
            "reset_display": "",
            "week_is_fresh": False,
            "disabled": True,
        },
    }


class DashboardCollector(threading.Thread):
    """Background daemon that ticks COLLECTOR_INTERVAL seconds.

    On each tick: runs the four tool collectors via collect_all() and
    stores the resulting payload as a shared snapshot under a lock.
    Version strings are resolved once at startup and cached in
    _cached_versions so the hot path does no subprocess work.
    """

    def __init__(self):
        super().__init__(daemon=True, name="DashboardCollector")
        self._lock = threading.Lock()
        self._snapshot = None

    def run(self):
        try:
            resolve_versions_once()
        except Exception as exc:
            print(f"[collector] version resolution failed: {exc}", flush=True)

        while True:
            try:
                payload = collect_all()
                with self._lock:
                    self._snapshot = payload
            except Exception as exc:
                # Never die; next tick will retry. Print for journalctl.
                print(f"[collector] tick failed: {exc}", flush=True)
            time.sleep(COLLECTOR_INTERVAL)

    def snapshot(self):
        """Return the most recent snapshot (or None if not yet collected)."""
        with self._lock:
            return self._snapshot


_collector = DashboardCollector()
_collector.start()


# --- HTML Frontend ---

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Codex Token Saver</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>⚡</text></svg>">
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { height: 100%; overflow: hidden; overflow-y: auto; }
body {
    background: #0a0a1a;
    font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', 'Courier New', monospace;
    font-size: 14px;
    line-height: 1.5;
    -webkit-font-smoothing: antialiased;
    color: #ccc;
    padding: 24px;
    display: flex;
    flex-direction: column;
}

/* Header */
.header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-bottom: 1px solid #1a1a2e;
    margin-bottom: 20px;
    padding-bottom: 12px;
}
.header-left {
    display: flex;
    align-items: center;
    gap: 10px;
    text-decoration: none;
}
.header-left:hover .header-title {
    text-shadow: 0 0 6px #00ff88;
}
.pulse-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #00ff88;
    animation: pulse 2s infinite;
    transition: background 0.3s, box-shadow 0.3s;
}
.pulse-dot.health-stale {
    background: #ffaa00;
    animation: pulse-stale 2s infinite;
}
.pulse-dot.health-error {
    background: #ff5577;
    animation: pulse-error 1.2s infinite;
}
@keyframes pulse {
    0%, 100% { opacity: 1; box-shadow: 0 0 4px #00ff88; }
    50% { opacity: 0.4; box-shadow: 0 0 1px #00ff88; }
}
@keyframes pulse-stale {
    0%, 100% { opacity: 1; box-shadow: 0 0 4px #ffaa00; }
    50% { opacity: 0.4; box-shadow: 0 0 1px #ffaa00; }
}
@keyframes pulse-error {
    0%, 100% { opacity: 1; box-shadow: 0 0 6px #ff5577; }
    50% { opacity: 0.5; box-shadow: 0 0 2px #ff5577; }
}
.header-title {
    color: #00ff88;
    font-size: 16px;
    letter-spacing: 3px;
    font-weight: bold;
}
.header-centre {
    color: #aaa;
    font-size: 13px;
}
.header-centre span {
    color: #00ff88;
    font-weight: bold;
}
.header-right {
    color: #9aa;
    font-size: 13px;
}

/* Cards grid */
.cards {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 10px;
    margin-bottom: 12px;
}
.card {
    background: #111;
    border: 1px solid #1a1a2e;
    padding: 14px;
    border-radius: 4px;
    transition: opacity 0.3s;
    min-width: 0;
}
/* Don't use opacity for inactive — it halves contrast and pushes every text
   colour in the card below AA. The empty state ("no datasets yet" subtitle,
   "--" value, no sparkline) already telegraphs inactivity. Border desaturation
   keeps the visual cue without crushing readability. */
.card.inactive { border-color: #14141e; }
.card.inactive .card-value { color: #555; }
.card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
    position: relative;
}
.card-name {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    font-weight: bold;
    color: #999;
    text-decoration: none;
}
.card-name:hover { color: #fff; }
.card-version {
    color: #9aa;
    font-size: 11px;
}
.card-value {
    font-size: 28px;
    font-weight: bold;
    margin-bottom: 2px;
    line-height: 1.1;
}
.card-sub {
    font-size: 12px;
    color: #aaa;
    margin-bottom: 10px;
}
.progress-track {
    height: 3px;
    background: #0a0a0a;
    border-radius: 2px;
    margin-bottom: 12px;
}
.progress-fill {
    height: 100%;
    border-radius: 2px;
    transition: width 0.6s ease;
}
.card-stats {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 10px;
    font-size: 11px;
    margin-bottom: 8px;
}
.card-stats .label { color: #9aa; }
.card-stats .val { color: #cdd; }
.sparkline-container { margin-bottom: 6px; }
.sparkline-container svg { width: 100%; height: 35px; }
.card-delta {
    font-size: 12px;
    color: #9aa;
}
.card-delta.active {
    color: #00ff88;
    animation: flash 0.5s;
}
@keyframes flash {
    0% { opacity: 0.3; }
    100% { opacity: 1; }
}

/* Tool colours */
.clr-rtk { color: #00ff88; }
.fill-rtk { background: #00ff88; }
.stroke-rtk { stroke: #00ff88; }
.area-rtk { fill: rgba(0, 255, 136, 0.1); }

.clr-headroom { color: #00bfff; }
.fill-headroom { background: #00bfff; }
.stroke-headroom { stroke: #00bfff; }
.area-headroom { fill: rgba(0, 191, 255, 0.1); }

.clr-jcodemunch { color: #ff9f43; }
.fill-jcodemunch { background: #ff9f43; }
.stroke-jcodemunch { stroke: #ff9f43; }
.area-jcodemunch { fill: rgba(255, 159, 67, 0.1); }
.clr-jdocmunch { color: #a55eea; }
.fill-jdocmunch { background: #a55eea; }
.stroke-jdocmunch { stroke: #a55eea; }
.area-jdocmunch { fill: rgba(165, 94, 234, 0.1); }
.clr-jdatamunch { color: #1dd1a1; }
.fill-jdatamunch { background: #1dd1a1; }
.stroke-jdatamunch { stroke: #1dd1a1; }
.area-jdatamunch { fill: rgba(29, 209, 161, 0.1); }
.health-dot {
    width: 5px;
    height: 5px;
    border-radius: 50%;
    position: absolute;
    left: -14px;
    top: 50%;
    transform: translateY(-50%);
}
.health-ok {
    background: #00ff88;
    animation: pulse 2s infinite;
}
.health-stale {
    background: #ffcc00;
}
.health-error {
    background: #ff4444;
}
.health-inactive {
    background: #8a96a8;
}

/* Feed */
.feed-container {
    background: #111;
    border: 1px solid #1a1a2e;
    border-radius: 4px;
    flex: 1;
    display: flex;
    flex-direction: column;
    min-height: 0;
}
.feed-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 16px;
    border-bottom: 1px solid #1a1a2e;
}
.feed-title {
    color: #999;
    font-size: 12px;
    text-transform: uppercase;
    font-weight: bold;
    letter-spacing: 2px;
}
.feed-count {
    color: #9aa;
    font-size: 12px;
}
.feed-area {
    flex: 1;
    overflow-y: auto;
    scrollbar-width: thin;          /* Firefox */
    scrollbar-color: #2a2a2a #0a0a0a;
    min-height: 0;
    font-size: 13px;
    line-height: 2.1;
    padding: 10px 16px;
}
/* Scrollable region must be focusable for keyboard users (WCAG 2.1.1 A).
   tabindex=0 in markup; this gives them a visible focus ring. */
.feed-area:focus-visible {
    outline: 2px solid #00ff88;
    outline-offset: -2px;
}
/* Mobile: stack the command text below the timestamp+tool row so it doesn't
   compress to zero width. Without this, the cmd column at <480px is invisible. */
@media (max-width: 480px) {
    .feed-line {
        flex-wrap: wrap;
        column-gap: 8px;
        row-gap: 2px;
        padding: 6px 0 6px 14px;
        line-height: 1.5;
    }
    .feed-cmd {
        flex-basis: 100%;
        order: 5;             /* render after time + tool + savings */
        color: #cdd;
        font-size: 12px;
    }
}
.feed-area::-webkit-scrollbar {
    width: 6px;
}
.feed-area::-webkit-scrollbar-track {
    background: #0a0a0a;
}
.feed-area::-webkit-scrollbar-thumb {
    background: #2a2a2a;
    border-radius: 3px;
}
.feed-area::-webkit-scrollbar-thumb:hover {
    background: #3a3a3a;
}
.feed-line {
    display: flex;
    gap: 16px;
    align-items: center;
    border-left: 2px solid transparent;
    padding-left: 14px;
}
.feed-time {
    color: #9aa;
    min-width: 128px;
    flex-shrink: 0;
}
.feed-tool {
    font-weight: bold;
    min-width: 95px;
    flex-shrink: 0;
}
.feed-cmd {
    color: #999;
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.feed-savings {
    min-width: 160px;
    text-align: right;
    flex-shrink: 0;
}
.feed-savings.positive { color: #00ff88; }
.feed-savings.zero { color: #888; }
.feed-savings.info { color: #aaa; }
/* "Muted" rows are no-savings entries — visually de-emphasised, but they must
   still meet WCAG AA contrast for screen-reader and low-vision users. Use a
   smaller font size + de-saturated colour tokens instead of opacity, which
   blends with the background and crushes contrast. */
.feed-line.muted {
    font-size: 12px;
}
.feed-line.muted .feed-time { color: #8898a0; }
.feed-line.muted .feed-cmd  { color: #a8b0b8; }
.feed-line.muted .feed-savings.zero,
.feed-line.muted .feed-savings.info { color: #a8b0b8; }
.feed-line.highlight {
    border-left-color: currentColor;
}
.feed-line.grouped {
    border-left-color: currentColor;
    font-style: italic;
}

@media (max-width: 1200px) {
    .cards { grid-template-columns: repeat(3, 1fr); }
}
@media (max-width: 800px) {
    .cards { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 500px) {
    .cards { grid-template-columns: 1fr; }
}
/* Stats ticker */
.ticker {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-wrap: wrap;
    gap: 6px 8px;
    padding: 6px 0;
    margin-bottom: 16px;
    font-size: 13px;
    color: #aab;
}
.ticker .sep {
    color: #889;
}
/* Screen-reader-only utility class so axe-core / SRs see a document h1 even
   though the visible design intentionally uses the "CODEX TOKEN SAVER" wordmark
   as a link rather than a heading. */
.sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
}
.ticker .tv {
    color: #00bfff;
    font-weight: bold;
}
.ticker .pct-green { color: #00ff88; }
.ticker .pct-yellow { color: #ffcc00; }
.ticker .pct-red { color: #ff4444; }
@media (max-width: 600px) {
    .ticker { font-size: 11px; gap: 3px 5px; }
    .header { flex-wrap: wrap; justify-content: center; gap: 4px; }
    .header-left { width: 100%; justify-content: center; }
    .header-centre { font-size: 12px; }
    .header-right { font-size: 12px; }
    html, body { overflow: auto; height: auto; }
}
#ticker, #jcodemunch-card, #jdocmunch-card, #jdatamunch-card { display: none !important; }
.cards { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.measurement-note { color: #bbc4d2; margin: 0 0 18px; line-height: 1.5; font-size: 13px; }
.connection-note { color: #d2dae6; background: #141d2b; border: 1px solid #314158; border-radius: 4px; padding: 10px 14px; margin-bottom: 12px; }
@media (max-width: 900px) { .cards { grid-template-columns: 1fr; } }
.updates-panel { background: #111; border: 1px solid #314158; border-radius: 4px; margin: 0 0 12px; flex-shrink: 0; }
.updates-panel summary { padding: 12px 16px; cursor: pointer; color: #d2dae6; font-weight: bold; }
.updates-panel summary span { float: right; color: #9aa; font-size: 12px; font-weight: normal; }
.updates-body { padding: 0 16px 16px; font-size: 12px; line-height: 1.5; }
.updates-body p { margin: 8px 0; }
.updates-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin: 12px 0; }
.updates-button { padding: 8px 12px; background: #152438; border: 1px solid #467095; border-radius: 4px; color: #e7f1ff; font: inherit; cursor: pointer; }
.updates-button:hover:enabled { background: #203b57; }
.updates-button:disabled { color: #85919e; background: #151a20; border-color: #35404a; cursor: default; }
.updates-button:focus-visible, .updates-panel summary:focus-visible { outline: 2px solid #00bfff; outline-offset: 3px; }
.updates-libraries { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.updates-library { border: 1px solid #293544; border-radius: 4px; padding: 12px; min-width: 0; }
.updates-library h2 { font-size: 14px; color: #e7f1ff; margin: 0; }
.updates-library a { color: #79caff; }
.updates-versions { display: flex; flex-wrap: wrap; gap: 6px 20px; color: #aebccd; }
.updates-versions strong { color: #e7f1ff; }
.updates-muted { color: #aebccd; }
.updates-error { color: #ffb1bf; overflow-wrap: anywhere; }
.updates-restart { background: #242313; border: 1px solid #655b29; color: #f0dda0; padding: 10px; border-radius: 4px; }
#updates-progress { width: 130px; accent-color: #00bfff; }
@media (max-width: 650px) { .updates-libraries { grid-template-columns: 1fr; } .updates-panel summary span { float: none; display: block; margin: 4px 0 0 15px; } }
</style>
<meta name="bundle-update-token" content="__BUNDLE_UPDATE_CSRF__">
<link rel="stylesheet" href="/static/components.css">
</head>
<body>
<!-- Header -->
<header class="header" role="banner">
    <h1 class="sr-only">Codex Token Saver</h1>
    <a class="header-left" href="https://github.com/patrickstrauss/Codex-Token-Saver" target="_blank" rel="noopener noreferrer" title="View source on GitHub">
        <div class="pulse-dot" id="health-pulse" title="All collectors healthy"></div>
        <div class="header-title">CODEX TOKEN SAVER</div>
    </a>
    <div class="header-centre" id="combined">LOCAL COMPRESSION ACTIVITY</div>
    <div class="header-right" id="clock">--:--:-- &blacksquare; -- --- ----</div>
</header>
<main role="main" aria-label="Tool savings dashboard">

<p class="connection-note">Headroom request compression handles eligible content across Codex model requests when enabled below. RTK and local Headroom tools provide additional output reduction.</p>
<p class="measurement-note">RTK estimates terminal-output tokens avoided. Headroom local output counts local file/stdout reductions before Codex truncation, including returned text and retrieval costs. These separate counters may overlap. They do not measure your ChatGPT quota or bill.</p>
<!-- Stats Ticker -->
<div class="ticker" id="ticker">
    <span title="Tokens saved by all tools since your weekly Claude reset">Saved This Week: <span class="tv" id="tk-this-week">--</span></span>
    <span class="sep">|</span>
    <span title="Total estimated tokens avoided during the previous weekly period">Saved Last Week: <span class="tv" id="tk-last-week">--</span></span>
    <span class="sep">|</span>
    <span title="Average daily token savings this week">Avg: ~<span class="tv" id="tk-burn">--</span>/day</span>
    <span class="sep">|</span>
    <span title="When your Claude weekly usage allocation resets">Reset: <span class="tv" id="tk-reset">--</span></span>
    <span class="sep">|</span>
    <span title="Claude usage in your current 5-hour rolling window">5-Hour Window: <span id="tk-session-pct" class="tv">--</span></span>
    <span class="sep">|</span>
    <span title="Claude usage across your 7-day rolling period">Weekly: <span id="tk-weekly-pct" class="tv">--</span></span>
    <span class="sep">|</span>
    <span title="Sonnet-only usage across your 7-day rolling period">Sonnet: <span id="tk-sonnet-pct" class="tv">--</span></span>
    <span class="sep">|</span>
    <span title="Headroom lifetime dollar savings (compression + provider prefix-cache discount)">Saved $: <span class="tv" id="tk-combined-usd">--</span></span>
</div>

<!-- Cards -->
__COMPONENTS_PANEL__
__REQUEST_PROXY_PANEL__
<div class="cards">
    <!-- RTK -->
    <div class="card" id="rtk-card">
        <div class="card-header">
            <span class="health-dot health-error" id="rtk-health"></span><a href="https://github.com/rtk-ai/rtk" target="_blank" class="card-name">RTK</a>
            <span class="card-version" id="rtk-version">--</span>
        </div>
        <div class="card-value clr-rtk" id="rtk-value">--</div>
        <label class="rtk-window" for="rtk-window">Window <select class="bundle-select" id="rtk-window" onchange="renderRtk(lastRtk)"><option value="today">Today</option><option value="seven_days">7 days</option><option value="lifetime">Lifetime</option></select></label>
        <div class="card-sub" id="rtk-sub">estimated tokens avoided</div>
        <div class="progress-track"><div class="progress-fill fill-rtk" id="rtk-bar" style="width:0%"></div></div>
        <div class="card-stats" id="rtk-stats">
            <span><span class="label">efficiency</span> <span class="val">--%</span></span>
        </div>
        <div class="sparkline-container"><svg id="rtk-sparkline" viewBox="0 0 200 35" preserveAspectRatio="none"></svg></div>
        <div class="card-delta" id="rtk-delta"></div>
        <p class="rtk-note" id="rtk-recent"></p>
        <p class="rtk-note" id="rtk-lifetime"></p>
        <p class="rtk-note" id="rtk-outlier"></p>
    </div>

    <!-- Headroom local output -->
    <div class="card" id="desktop-headroom-card">
        <div class="card-header">
            <a href="https://github.com/headroomlabs-ai/headroom" target="_blank" rel="noopener noreferrer" class="card-name">Headroom local output</a>
            <span class="card-version" id="desktop-headroom-version">--</span>
        </div>
        <div class="card-value clr-headroom" id="desktop-headroom-value">--</div>
        <div class="card-sub" id="desktop-headroom-sub">net content tokens avoided (estimate)</div>
        <div class="card-sub" id="desktop-headroom-check"></div>
        <div class="card-sub" id="desktop-headroom-outcomes"></div>
        <div class="card-sub" id="desktop-headroom-scope">This counter covers local files and selected command outputs; request savings are tracked separately below.</div>
        <div class="card-stats" id="desktop-headroom-stats">Desktop tool records loading</div>
        <div class="card-sub" id="desktop-headroom-detail"></div>
        <div class="card-sub" id="desktop-headroom-status">Configuration loading</div>
        <div class="card-sub" id="desktop-headroom-skips"></div>
        <div class="card-delta" id="desktop-headroom-recorded"></div>
    </div>

    <!-- Optional Headroom CLI proxy -->
    <div class="card" id="headroom-card">
        <div class="card-header">
            <span class="health-dot health-inactive" id="headroom-health"></span><a href="https://github.com/headroomlabs-ai/headroom" target="_blank" class="card-name">Headroom CLI proxy</a>
            <span class="card-version" id="headroom-version">--</span>
        </div>
        <div class="card-value clr-headroom" id="headroom-value">--</div>
        <div class="card-sub" id="headroom-sub">optional proxy status loading</div>
        <div class="progress-track"><div class="progress-fill fill-headroom" id="headroom-bar" style="width:0%"></div></div>
        <div class="card-stats" id="headroom-stats">
            <span><span class="label">experimental CLI sessions only</span></span>
        </div>
        <div class="sparkline-container"><svg id="headroom-sparkline" viewBox="0 0 200 35" preserveAspectRatio="none"></svg></div>
        <div class="card-delta" id="headroom-delta"></div>
    </div>

    <!-- jCodeMunch -->
    <div class="card" id="jcodemunch-card">
        <div class="card-header">
            <span class="health-dot health-error" id="jcodemunch-health"></span><a href="https://github.com/jgravelle/jcodemunch-mcp" target="_blank" class="card-name">jCodeMunch</a>
            <span class="card-version" id="jcodemunch-version">--</span>
        </div>
        <div class="card-value clr-jcodemunch" id="jcodemunch-value">--</div>
        <div class="card-sub" id="jcodemunch-sub">estimated tokens avoided</div>
        <div class="progress-track"><div class="progress-fill fill-jcodemunch" id="jcodemunch-bar" style="width:0%"></div></div>
        <div class="card-stats" id="jcodemunch-stats">
            <span><span class="label">repos</span> <span class="val">--</span></span>
        </div>
        <div class="sparkline-container"><svg id="jcodemunch-sparkline" viewBox="0 0 200 35" preserveAspectRatio="none"></svg></div>
        <div class="card-delta" id="jcodemunch-delta"></div>
    </div>

    <!-- jDocMunch -->
    <div class="card" id="jdocmunch-card">
        <div class="card-header">
            <span class="health-dot health-error" id="jdocmunch-health"></span><a href="https://github.com/jgravelle/jdocmunch-mcp" target="_blank" class="card-name">jDocMunch</a>
            <span class="card-version" id="jdocmunch-version">--</span>
        </div>
        <div class="card-value clr-jdocmunch" id="jdocmunch-value">--</div>
        <div class="card-sub" id="jdocmunch-sub">estimated tokens avoided</div>
        <div class="progress-track"><div class="progress-fill fill-jdocmunch" id="jdocmunch-bar" style="width:0%"></div></div>
        <div class="card-stats" id="jdocmunch-stats">
            <span><span class="label">docs</span> <span class="val">--</span></span>
        </div>
        <div class="sparkline-container"><svg id="jdocmunch-sparkline" viewBox="0 0 200 35" preserveAspectRatio="none"></svg></div>
        <div class="card-delta" id="jdocmunch-delta"></div>
    </div>

    <!-- jDataMunch -->
    <div class="card" id="jdatamunch-card">
        <div class="card-header">
            <span class="health-dot health-error" id="jdatamunch-health"></span><a href="https://github.com/jgravelle/jdatamunch-mcp" target="_blank" class="card-name">jDataMunch</a>
            <span class="card-version" id="jdatamunch-version">--</span>
        </div>
        <div class="card-value clr-jdatamunch" id="jdatamunch-value">--</div>
        <div class="card-sub" id="jdatamunch-sub">estimated tokens avoided</div>
        <div class="progress-track"><div class="progress-fill fill-jdatamunch" id="jdatamunch-bar" style="width:0%"></div></div>
        <div class="card-stats" id="jdatamunch-stats">
            <span><span class="label">datasets</span> <span class="val">--</span></span>
        </div>
        <div class="sparkline-container"><svg id="jdatamunch-sparkline" viewBox="0 0 200 35" preserveAspectRatio="none"></svg></div>
        <div class="card-delta" id="jdatamunch-delta"></div>
    </div>

</div>

<details class="updates-panel" id="library-updates">
    <summary>Library updates <span id="updates-summary">Bundle runtimes</span></summary>
    <div class="updates-body">
        <p class="updates-muted">Update installed bundle runtimes with compatibility checks and rollback. Local model files are not automatically replaced.</p>
        <div class="updates-actions">
            <button type="button" class="updates-button" id="updates-check">Check for updates</button>
            <span class="updates-muted" id="updates-checked">No release check yet</span>
            <progress id="updates-progress" aria-label="Library update in progress" hidden></progress>
            <span class="updates-muted" id="updates-stage"></span>
        </div>
        <p id="updates-message" role="status" aria-live="polite">Check manually when you want newer releases.</p>
        <p id="updates-error" class="updates-error" role="alert" hidden></p>
        <div class="updates-libraries">
            <section class="updates-library" aria-label="Headroom library updates">
                <h2>Headroom</h2>
                <p class="updates-versions"><span>Installed core <strong id="update-headroom-current">Loading</strong></span><span>Latest core <strong id="update-headroom-latest">Not checked</strong></span></p>
                <p class="updates-muted">When the core is current, refresh its compatible Python dependencies. Changes are validated before switching.</p>
                <div class="updates-actions">
                    <button type="button" class="updates-button" id="update-headroom-install" disabled>Update Headroom</button>
                    <button type="button" class="updates-button" id="update-headroom-rollback" disabled>Rollback</button>
                    <a href="https://github.com/headroomlabs-ai/headroom/releases" target="_blank" rel="noopener noreferrer">Releases</a>
                </div>
                <p id="update-headroom-error" class="updates-error"></p>
            </section>
            <section class="updates-library" aria-label="RTK library updates">
                <h2>RTK</h2>
                <p class="updates-versions"><span>Installed <strong id="update-rtk-current">Loading</strong></span><span>Latest <strong id="update-rtk-latest">Not checked</strong></span></p>
                <div class="updates-actions">
                    <button type="button" class="updates-button" id="update-rtk-install" disabled>Update RTK</button>
                    <button type="button" class="updates-button" id="update-rtk-rollback" disabled>Rollback</button>
                    <a href="https://github.com/rtk-ai/rtk/releases" target="_blank" rel="noopener noreferrer">Releases</a>
                </div>
                <p id="update-rtk-error" class="updates-error"></p>
            </section>
            <section class="updates-library" aria-label="Serena library updates">
                <h2>Serena</h2>
                <p class="updates-versions"><span>Installed <strong id="update-serena-current">Loading</strong></span><span>Latest <strong id="update-serena-latest">Not checked</strong></span></p>
                <div class="updates-actions"><button type="button" class="updates-button" id="update-serena-install" disabled>Update Serena</button><button type="button" class="updates-button" id="update-serena-rollback" disabled>Rollback</button><a href="https://github.com/oraios/serena/releases" target="_blank" rel="noopener noreferrer">Releases</a></div>
                <p id="update-serena-error" class="updates-error"></p>
            </section>
            <section class="updates-library" aria-label="LangMem library updates">
                <h2>LangMem</h2>
                <p class="updates-versions"><span>Installed <strong id="update-langmem-current">Loading</strong></span><span>Latest <strong id="update-langmem-latest">Not checked</strong></span></p>
                <div class="updates-actions"><button type="button" class="updates-button" id="update-langmem-install" disabled>Update LangMem</button><button type="button" class="updates-button" id="update-langmem-rollback" disabled>Rollback</button><a href="https://github.com/langchain-ai/langmem/releases" target="_blank" rel="noopener noreferrer">Releases</a></div>
                <p id="update-langmem-error" class="updates-error"></p>
            </section>
            <section class="updates-library" aria-label="llama.cpp library updates">
                <h2>llama.cpp</h2>
                <p class="updates-versions"><span>Installed <strong id="update-llama_cpp-current">Loading</strong></span><span>Latest <strong id="update-llama_cpp-latest">Not checked</strong></span></p>
                <div class="updates-actions"><button type="button" class="updates-button" id="update-llama_cpp-install" disabled>Update llama.cpp</button><button type="button" class="updates-button" id="update-llama_cpp-rollback" disabled>Rollback</button><a href="https://github.com/ggml-org/llama.cpp/releases" target="_blank" rel="noopener noreferrer">Releases</a></div>
                <p id="update-llama_cpp-error" class="updates-error"></p>
            </section>
        </div>
        <p id="updates-restart" class="updates-restart" hidden></p>
        <p class="updates-muted">Checks and installs run only when you click. Progress is recorded locally; a failed request is never retried automatically.</p>
        <p id="updates-log" class="updates-muted"></p>
    </div>
</details>

<!-- Activity Feed -->
<div class="feed-container">
    <div class="feed-header">
        <span class="feed-title">LIVE ACTIVITY</span>
        <span class="feed-count">showing last 0</span>
    </div>
    <div class="feed-area" id="feed" tabindex="0" role="log" aria-live="polite" aria-label="Live activity feed: recent token-saving events"></div>
</div>
</main>

<script>
function formatTokens(n, withUnit) {
    var neg = n < 0 ? '-' : '';
    var a = Math.abs(n);
    if (a >= 1e9) return neg + (a / 1e9).toFixed(1) + 'B';
    if (a >= 1e6) return neg + (a / 1e6).toFixed(1) + 'M';
    if (a >= 1e3) return neg + (a / 1e3).toFixed(1) + 'K';
    if (withUnit) return n + ' tokens';
    return String(n);
}

function formatTime(ms) {
    var s = ms / 1000;
    if (s >= 60) return (s / 60).toFixed(1) + 'min';
    return s.toFixed(1) + 's';
}

function shortTime(t) {
    if (!t) return '';
    // Keep the date visible so retained historical entries never look like today's work.
    var d = new Date(t);
    if (!Number.isNaN(d.getTime())) return d.toLocaleString(undefined, {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'});
    return String(t).substring(0, 19).replace('T', ' ');
}

function shortVersion(v) {
    if (!v || v === 'unknown') return '--';
    // "rtk 0.34.1" -> "0.34.1", "headroom, version 0.5.9" -> "0.5.9"
    var clean = v.replace(/,/g, '').trim();
    var parts = clean.split(' ');
    return parts[parts.length - 1];
}

function pctClass(n) {
    if (n == null) return 'tv';
    if (n > 80) return 'pct-red';
    if (n > 50) return 'pct-yellow';
    return 'pct-green';
}

var TOOLS = ['rtk', 'headroom'];
var TOOL_COLOURS = {
    rtk: '#00ff88',
    headroom: '#00bfff',
    jcodemunch: '#ff9f43',
    jdocmunch: '#a55eea',
    jdatamunch: '#1dd1a1'
};

function renderSparkline(svgEl, points, tool) {
    if (!points || points.length < 2) {
        svgEl.innerHTML = '';
        return;
    }
    var max = Math.max.apply(null, points);
    if (max === 0) { svgEl.innerHTML = ''; return; }

    var w = 200, hMin = 5, hMax = 30;
    var stepX = w / (points.length - 1);
    var pathParts = [];
    var areaParts = [];

    for (var i = 0; i < points.length; i++) {
        var x = (i * stepX).toFixed(1);
        var y = (hMax - (points[i] / max) * (hMax - hMin)).toFixed(1);
        pathParts.push((i === 0 ? 'M' : 'L') + x + ',' + y);
        areaParts.push((i === 0 ? 'M' : 'L') + x + ',' + y);
    }

    var lastX = ((points.length - 1) * stepX).toFixed(1);
    areaParts.push('L' + lastX + ',35');
    areaParts.push('L0,35');
    areaParts.push('Z');

    svgEl.innerHTML =
        '<path d="' + areaParts.join(' ') + '" class="area-' + tool + '" stroke="none"/>' +
        '<path d="' + pathParts.join(' ') + '" class="stroke-' + tool + '" fill="none" stroke-width="1.5"/>';
}

var lastRtk = {};
function renderRtk(rtk) {
    lastRtk = rtk;
    var choice = document.getElementById('rtk-window');
    var key = choice && choice.value ? choice.value : 'today';
    var selected = rtk.windows && rtk.windows[key] ? rtk.windows[key] : rtk;
    var readable = rtk.records_readable == null ? !!rtk.active : rtk.records_readable;
    document.getElementById('rtk-card').className = rtk.total_saved != null ? 'card' : 'card inactive';
    document.getElementById('rtk-health').className = 'health-dot health-' + (rtk.health || 'error');
    document.getElementById('rtk-version').textContent = shortVersion(rtk.version);
    document.getElementById('rtk-value').textContent = selected.total_saved != null ? formatTokens(selected.total_saved) : '--';
    document.getElementById('rtk-sub').textContent = readable ? 'estimated output tokens avoided · ' + ({today:'today',seven_days:'last 7 days',lifetime:'lifetime'}[key])
        : (rtk.total_saved != null ? 'last recorded estimate; records unavailable' : 'RTK records unavailable');
    document.getElementById('rtk-bar').style.width = (readable ? Math.max(0, Math.min(100, selected.avg_savings_pct || 0)) : 0) + '%';
    document.getElementById('rtk-stats').textContent = !readable ? 'Unable to read RTK history'
        : selected.total_commands ? (selected.avg_savings_pct || 0) + '% output reduction · ' + selected.total_commands + ' commands · '
            + (selected.optimized_commands == null ? '' : selected.optimized_commands + ' reduced · ')
            + formatTime(selected.total_time_ms / selected.total_commands) + ' average'
        : 'No commands recorded in this window';
    document.getElementById('rtk-recent').textContent = rtk.last_recorded_at
        ? 'Last command: ' + new Date(rtk.last_recorded_at).toLocaleString() + (rtk.recent_use ? ' · used in the last 5 minutes' : ' · no recent use')
        : 'No command activity recorded. A readable database does not mean commands are using RTK.';
    document.getElementById('rtk-lifetime').textContent = rtk.windows ? 'Lifetime estimate: ' + formatTokens(rtk.total_saved || 0)
        + ' across ' + (rtk.total_commands || 0) + ' commands.'
        + ((rtk.windows.lifetime || {}).largest_saved_share_pct >= 50 ? ' One record contributes ' + rtk.windows.lifetime.largest_saved_share_pct + '% of lifetime savings.' : '')
        + ' Collector: ' + new Date(rtk.collected_at).toLocaleTimeString() : '';
    document.getElementById('rtk-outlier').textContent = selected.largest_saved_share_pct >= 50
        ? 'Largest single record contributes ' + selected.largest_saved_share_pct + '% of saved tokens in this window; it can dominate the rate.' : '';
}

function updateDashboard(d) {
    // Combined
    document.getElementById('combined').textContent = 'LOCAL COMPRESSION ACTIVITY';

    // Ticker
    var w = d.weekly || {};
    var cu = d.claude_usage || {};
    document.getElementById('tk-this-week').textContent = w.week_is_fresh ? '--' : (w.this_week != null ? formatTokens(w.this_week, true) : '--');
    document.getElementById('tk-last-week').textContent = w.last_week != null ? (w.last_week === 0 ? '0' : formatTokens(w.last_week, true)) : '--';
    document.getElementById('tk-burn').textContent = w.burn_rate_daily != null ? (w.burn_rate_daily === 0 ? '0' : formatTokens(w.burn_rate_daily, true)) : '--';
    document.getElementById('tk-reset').textContent = w.reset_display || '--';

    var sessionEl = document.getElementById('tk-session-pct');
    var weeklyEl = document.getElementById('tk-weekly-pct');
    if (cu.active && cu.session_pct != null) {
        sessionEl.textContent = cu.session_pct + '%';
        sessionEl.className = pctClass(cu.session_pct);
    } else {
        sessionEl.textContent = '--';
        sessionEl.className = 'tv';
    }
    if (cu.active && cu.weekly_pct != null) {
        weeklyEl.textContent = cu.weekly_pct + '%';
        weeklyEl.className = pctClass(cu.weekly_pct);
    } else {
        weeklyEl.textContent = '--';
        weeklyEl.className = 'tv';
    }
    var sonnetEl = document.getElementById('tk-sonnet-pct');
    if (cu.active && cu.sonnet_pct != null) {
        sonnetEl.textContent = cu.sonnet_pct + '%';
        sonnetEl.className = pctClass(cu.sonnet_pct);
    } else {
        sonnetEl.textContent = '--';
        sonnetEl.className = 'tv';
    }

    // Combined dollar savings (compression + provider prefix-cache discount).
    var combinedUsdEl = document.getElementById('tk-combined-usd');
    if (combinedUsdEl) {
        var usd = d.combined_saved_usd || 0;
        if (usd >= 1000) {
            combinedUsdEl.textContent = '$' + (usd / 1000).toFixed(1) + 'k';
        } else if (usd > 0) {
            combinedUsdEl.textContent = '$' + usd.toFixed(2);
        } else {
            combinedUsdEl.textContent = '--';
        }
        combinedUsdEl.className = 'tv';
    }

    // All requested components contribute to effective health.
    var pulseDot = document.getElementById('health-pulse');
    if (pulseDot) {
        var oh = d.overall_health || 'ok';
        pulseDot.className = 'pulse-dot' + (oh !== 'ok' ? ' health-' + oh : '');
        pulseDot.title = oh === 'ok'
            ? ((d.components || {}).unverified_count ? 'No reported component faults; Codex task tool loading is unverified'
                : 'Selected bundle components are ready; readiness is not proof of recent use')
            : 'A selected component needs attention. Check Bundle controls.';
    }

    renderRtk(d.rtk || {});

    // Desktop tool counters are historical data, never a runtime-health claim.
    var desktop = d.desktop_headroom || {};
    document.getElementById('desktop-headroom-card').className = desktop.total_saved != null ? 'card' : 'card inactive';
    document.getElementById('desktop-headroom-version').textContent = desktop.configured ? 'Configured' : 'Not configured';
    document.getElementById('desktop-headroom-value').textContent = desktop.total_saved != null ? formatTokens(desktop.total_saved) : '--';
    document.getElementById('desktop-headroom-sub').textContent = 'net content tokens avoided (estimate)';
    document.getElementById('desktop-headroom-scope').textContent = desktop.coverage || 'This counter covers local files and selected command outputs; request savings are tracked separately below.';
    var automation = desktop.automation || {};
    document.getElementById('desktop-headroom-status').textContent = automation.data_status === 'unavailable'
        ? 'Hook observations unavailable.'
        : (automation.observed
        ? 'Recent hook checks: ' + automation.observed + ' checked / ' + automation.rewritten + ' wrapped / ' + (automation.skipped == null ? automation.observed - automation.rewritten : automation.skipped) + ' skipped. Wrapping does not guarantee savings.'
        : (automation.configured
            ? 'RTK filters eligible output automatically. Extra command hook: no events yet; review it in Codex Settings > Hooks.'
            : (desktop.configured ? 'Local file tools configured.' : 'Desktop integration is not configured.')));
    document.getElementById('desktop-headroom-skips').textContent = (automation.top_skip_reasons || []).length
        ? 'Top skips in recent log: ' + automation.top_skip_reasons.map(function(reason) { return reason.label + ' (' + reason.count + ')'; }).join('; ') + '.'
        : '';
    document.getElementById('desktop-headroom-stats').textContent = desktop.data_status === 'recorded'
        ? desktop.read_count + ' reads / ' + (desktop.command_count || 0) + ' commands / ' + desktop.retrieve_count + ' retrievals'
        : (desktop.data_status === 'empty' ? 'no file or command reductions recorded yet' : 'Desktop tool records unavailable');
    document.getElementById('desktop-headroom-detail').textContent = desktop.total_saved != null
        ? formatTokens(desktop.gross_saved || 0) + ' gross reduction; ' + formatTokens(desktop.retrieval_tokens || 0) + ' retrieval tokens (before Codex truncation)'
        : '';
    var commandResults = {
        disabled: ['filter Off', 'local filtering Off; original kept'],
        compressed: ['compressed', 'output reduced'],
        small_output: ['too small', 'original kept; output too small'],
        no_reduction: ['no further reduction', 'original kept; no further reduction'],
        command_failed: ['failed', 'command failed; original output kept'],
        compression_unavailable: ['compression unavailable', 'compression unavailable; original output kept'],
        compression_timeout: ['compression timed out', 'compression timed out; original output kept'],
        streaming_timeout: ['streamed directly', 'output streamed directly; buffering time limit reached'],
        inherited_pipe: ['child process output', 'child process kept output open; output streamed directly'],
        interactive_passthrough: ['interactive commands', 'interactive command; output passed through'],
        exact_requested: ['exact requested', 'exact output requested; original kept'],
        size_limit: ['over size limit', 'original kept; over size limit'],
        binary_output: ['binary output', 'original kept; binary output'],
        non_utf8: ['unsupported encoding', 'original kept; unsupported encoding'],
        other: ['other', 'other or unknown result']
    };
    var lastResult = Object.prototype.hasOwnProperty.call(commandResults, desktop.last_command_status)
        ? commandResults[desktop.last_command_status][1] : commandResults.other[1];
    document.getElementById('desktop-headroom-check').textContent = desktop.data_status === 'unavailable'
        ? 'Output-check records unavailable.'
        : (desktop.command_attempt_count
            ? 'Last output check: ' + (desktop.last_command_check ? shortTime(desktop.last_command_check) : 'time unavailable') + ' - ' + lastResult + '.'
            : 'No command output checks recorded yet.');
    var commandStatuses = desktop.command_statuses || {};
    var outcomes = Object.keys(commandResults).filter(function(status) { return commandStatuses[status] > 0; })
        .map(function(status) { return commandStatuses[status] + ' ' + commandResults[status][0]; });
    document.getElementById('desktop-headroom-outcomes').textContent = desktop.data_status !== 'unavailable' && desktop.command_attempt_count
        ? desktop.command_attempt_count + ' outputs checked' + (outcomes.length ? ': ' + outcomes.join(' / ') : '') + '.'
        : '';
    document.getElementById('desktop-headroom-recorded').textContent = desktop.last_recorded_at
        ? 'Last savings ledger event: ' + shortTime(desktop.last_recorded_at)
        : '';

    // Optional Headroom CLI proxy
    var hr = d.headroom || {};
    var hrCard = document.getElementById('headroom-card');
    hrCard.className = hr.total_saved != null ? 'card' : 'card inactive';
    var hrHealth = hr.health || 'inactive';
    var hrDot = document.getElementById('headroom-health');
    if (hrDot) hrDot.className = 'health-dot health-' + hrHealth;
    document.getElementById('headroom-version').textContent = shortVersion(hr.version);
    if (hr.active) {
        document.getElementById('headroom-value').textContent = formatTokens(hr.total_saved || 0);
        var sub = 'reported proxy reductions; optional proxy running';

        document.getElementById('headroom-sub').textContent = sub;
        document.getElementById('headroom-bar').style.width = (hr.compression_ratio || hr.avg_savings_pct || 0) + '%';
        var hrStats = '<span><span class="label">proxy requests</span> <span class="val">' + (hr.requests_total || 0) + '</span></span>';
        if (hr.cache_hit_rate != null) {
            hrStats += '<span><span class="label">cache hit</span> <span class="val">' + hr.cache_hit_rate + '%</span></span>';
        }

        document.getElementById('headroom-stats').innerHTML = hrStats;
    } else {
        document.getElementById('headroom-value').textContent = hr.total_saved != null ? formatTokens(hr.total_saved) : '--';
        document.getElementById('headroom-sub').textContent = hr.data_status === 'historical' ? 'last recorded reductions; proxy offline' : 'optional proxy offline; no recorded data';
        document.getElementById('headroom-bar').style.width = '0%';
        document.getElementById('headroom-stats').textContent = hr.last_recorded_at
            ? 'Historical record: ' + shortTime(hr.last_recorded_at) + ' (' + (hr.source || 'local records') + ')'
            : 'Experimental CLI sessions only';
    }

    // jCodeMunch
    var jc = d.jcodemunch || {};
    var jcCard = document.getElementById('jcodemunch-card');
    jcCard.className = jc.active ? 'card' : 'card inactive';
    var jcHealth = jc.health || 'error';
    var jcDot = document.getElementById('jcodemunch-health');
    if (jcDot) jcDot.className = 'health-dot health-' + jcHealth;
    document.getElementById('jcodemunch-version').textContent = shortVersion(jc.version);
    document.getElementById('jcodemunch-value').textContent = jc.active ? formatTokens(jc.total_saved || 0) : '--';
    document.getElementById('jcodemunch-sub').textContent = 'estimated tokens avoided';
    document.getElementById('jcodemunch-bar').style.width = (jc.freshness || 0) + '%';
    if (jc.active) {
        document.getElementById('jcodemunch-stats').innerHTML =
            '<span><span class="label">repos</span> <span class="val">' + (jc.repos_indexed || 0) + '</span></span>' +
            '<span><span class="label">indexed</span> <span class="val">' + (jc.index_size_mb || 0) + 'MB</span></span>' +
            '<span><span class="label">active</span> <span class="val">' + (jc.freshness_label || 'idle') + '</span></span>';
    }

    // jDocMunch
    var jd = d.jdocmunch || {};
    var jdCard = document.getElementById('jdocmunch-card');
    jdCard.className = jd.active ? 'card' : 'card inactive';
    var jdHealth = jd.health || 'error';
    var jdDot = document.getElementById('jdocmunch-health');
    if (jdDot) jdDot.className = 'health-dot health-' + jdHealth;
    document.getElementById('jdocmunch-version').textContent = shortVersion(jd.version);
    document.getElementById('jdocmunch-value').textContent = jd.active ? formatTokens(jd.total_saved || 0) : '--';
    document.getElementById('jdocmunch-sub').textContent = 'estimated tokens avoided';
    document.getElementById('jdocmunch-bar').style.width = (jd.freshness || 0) + '%';
    if (jd.active) {
        document.getElementById('jdocmunch-stats').innerHTML =
            '<span><span class="label">docs</span> <span class="val">' + (jd.docs_indexed || 0) + '</span></span>' +
            '<span><span class="label">indexed</span> <span class="val">' + (jd.index_size_mb || 0) + 'MB</span></span>' +
            '<span><span class="label">active</span> <span class="val">' + (jd.freshness_label || 'idle') + '</span></span>';
    }

    // jDataMunch
    var jdt = d.jdatamunch || {};
    var jdtCard = document.getElementById('jdatamunch-card');
    if (jdtCard) {
        jdtCard.className = jdt.active ? 'card' : 'card inactive';
        var jdtHealth = jdt.health || 'error';
        var jdtDot = document.getElementById('jdatamunch-health');
        if (jdtDot) jdtDot.className = 'health-dot health-' + jdtHealth;
        document.getElementById('jdatamunch-version').textContent = shortVersion(jdt.version);
        document.getElementById('jdatamunch-value').textContent = jdt.active ? formatTokens(jdt.total_saved || 0) : '--';
        document.getElementById('jdatamunch-sub').textContent = 'estimated tokens avoided';
        document.getElementById('jdatamunch-bar').style.width = (jdt.freshness || 0) + '%';
        if (jdt.active) {
            document.getElementById('jdatamunch-stats').innerHTML =
                '<span><span class="label">datasets</span> <span class="val">' + (jdt.datasets_indexed || 0) + '</span></span>' +
                '<span><span class="label">indexed</span> <span class="val">' + (jdt.index_size_mb || 0) + 'MB</span></span>' +
                '<span><span class="label">active</span> <span class="val">' + (jdt.freshness_label || 'idle') + '</span></span>';
        }
    }

    // Sparklines
    if (d.sparklines) {
        for (var i = 0; i < TOOLS.length; i++) {
            var t = TOOLS[i];
            var sp = d.sparklines[t];
            var pts = sp ? (sp.points || sp) : [];
            renderSparkline(document.getElementById(t + '-sparkline'), pts, t);

            var deltaEl = document.getElementById(t + '-delta');
            var delta = sp ? (sp.delta || 0) : 0;
            if (delta > 0) {
                deltaEl.textContent = '+' + formatTokens(delta);
                deltaEl.className = 'card-delta active';
            } else {
                deltaEl.textContent = '';
                deltaEl.className = 'card-delta';
            }
        }
    }

    // Feed
    var feedEl = document.getElementById('feed');
    // Pause the live rebuild while the user has scrolled down to read older
    // entries. The feed is newest-first, so scrollTop near 0 means "viewing
    // latest"; a full innerHTML replace each tick would otherwise snap them
    // back to the top and they could never read history.
    var feedPaused = feedEl && feedEl.scrollTop > 8;
    var hist = d.history || [];
    var lines = [];
    for (var j = 0; j < hist.length && j < 100; j++) {
        var h = hist[j];
        var toolClr = TOOL_COLOURS[h.tool] || '#888';
        var savingsClass = 'info';
        var savingsText = '';
        if (h.saved_tokens > 0) {
            savingsClass = 'positive';
            savingsText = '-' + formatTokens(h.saved_tokens) + ' tokens (' + (h.saved_pct || 0) + '%)';
        } else if (h.saved_tokens === 0 && h.saved_pct === 0) {
            savingsClass = 'zero';
            savingsText = 'no savings';
        } else {
            savingsText = formatTokens(h.saved_tokens || 0) + ' tokens';
        }
        var lineClasses = 'feed-line';
        if (h.saved_tokens === 0 && (h.saved_pct === 0 || !h.saved_pct)) {
            lineClasses += ' muted';
        } else if (h.saved_tokens > 0) {
            lineClasses += ' highlight';
        }
        if (h.grouped) {
            lineClasses += ' grouped';
        }
        lines.push(
            '<div class="' + lineClasses + '"' + (lineClasses.indexOf('highlight') >= 0 || lineClasses.indexOf('grouped') >= 0 ? ' style="border-color:' + toolClr + '"' : '') + '>' +
            '<span class="feed-time">' + shortTime(h.time) + '</span>' +
            '<span class="feed-tool" style="color:' + toolClr + '">' + (h.tool || '') + '</span>' +
            '<span class="feed-cmd">' + escHtml(h.cmd || '') + '</span>' +
            '<span class="feed-savings ' + savingsClass + '">' + savingsText + '</span>' +
            '</div>'
        );
    }
    var countEl = document.querySelector('.feed-count');
    if (feedPaused) {
        if (countEl) { countEl.textContent = 'paused: scroll up to resume'; }
        return;
    }
    feedEl.innerHTML = lines.join('');
    if (countEl) {
        countEl.textContent = 'showing last ' + Math.min(hist.length, 100);
    }
}

function escHtml(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// Clock
function updateClock() {
    var now = new Date();
    var h = String(now.getHours()).padStart(2, '0');
    var m = String(now.getMinutes()).padStart(2, '0');
    var s = String(now.getSeconds()).padStart(2, '0');
    var months = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'];
    var day = String(now.getDate()).padStart(2, '0');
    var mon = months[now.getMonth()];
    var yr = now.getFullYear();
    document.getElementById('clock').textContent = h + ':' + m + ':' + s + ' \u25aa ' + day + ' ' + mon + ' ' + yr;
}
setInterval(updateClock, 1000);
updateClock();

// SSE
var source = new EventSource('/events');
var lastMsgTs = Date.now();

function setConnState(state, title) {
    var dot = document.getElementById('health-pulse');
    if (!dot) return;
    dot.className = 'pulse-dot' + (state !== 'ok' ? ' health-' + state : '');
    dot.title = title;
}

source.onmessage = function(e) {
    lastMsgTs = Date.now();
    try {
        var d = JSON.parse(e.data);
        updateDashboard(d);   // resets the pulse-dot from overall_health, clearing any disconnect state
    } catch (err) {
        console.error('SSE parse error:', err);
    }
};
source.onerror = function() {
    console.debug('SSE connection lost, will retry...');
    setConnState('error', 'Live feed disconnected, reconnecting');
};

// Staleness watchdog: flag a frozen board even when the connection stays open
// but no message has arrived for several push intervals.
setInterval(function() {
    var age = Date.now() - lastMsgTs;
    if (age > 15000) {
        setConnState('error', 'Live feed stale: no update for ' + Math.round(age / 1000) + 's');
    }
}, 5000);
</script>
<script src="/static/updates.js"></script>
<script src="/static/proxy.js"></script>
<script src="/static/components.js"></script>
</body>
</html>"""


# --- Prometheus metrics ---

_PROM_TOOLS = ("rtk", "headroom", "jcodemunch", "jdocmunch", "jdatamunch")
_HEALTH_VALUE = {"ok": 2, "stale": 1, "error": 0, "inactive": -1}


def _num(v):
    """Format a number for Prometheus exposition (ints stay ints, bools -> 0/1)."""
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _render_metrics(snap):
    """Render a collect_all() snapshot as Prometheus text exposition (v0.0.4).

    Pure function so it can be unit-tested without a live collector. Emits
    ctd_up=0 for an empty snapshot (board not yet ticked, or collector dead) so
    a scrape still distinguishes 'no data' from 'target down'.
    """
    lines = []

    def block(name, help_text):
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} gauge")

    if not snap:
        block("ctd_up", "Dashboard liveness (1 = a collector snapshot is available).")
        lines.append("ctd_up 0")
        return "\n".join(lines) + "\n"

    block("ctd_up", "Dashboard liveness (1 = a collector snapshot is available).")
    lines.append("ctd_up 1")

    # Unsupported combined counters are omitted, never exposed as zero or 'None'.

    block("ctd_overall_health", "Selected bundle component health (2=ok, 1=degraded, 0=error).")
    lines.append(f"ctd_overall_health {_HEALTH_VALUE.get(snap.get('overall_health'), 0)}")

    block("ctd_tool_saved_tokens", "Lifetime estimated tokens avoided, per tool.")
    for tool in _PROM_TOOLS:
        td = snap.get(tool)
        if isinstance(td, dict) and td.get("total_saved") is not None:
            lines.append(f'ctd_tool_saved_tokens{{tool="{tool}"}} {_num(td.get("total_saved", 0))}')

    block("ctd_tool_health", "Per-tool collector health (2=ok, 1=stale, 0=error, -1=optional inactive).")
    for tool in _PROM_TOOLS:
        td = snap.get(tool)
        if isinstance(td, dict):
            lines.append(f'ctd_tool_health{{tool="{tool}"}} {_HEALTH_VALUE.get(td.get("health"), 0)}')

    usage = snap.get("claude_usage") or {}
    live = [(w, usage.get(k)) for w, k in
            (("session", "session_pct"), ("weekly", "weekly_pct"), ("sonnet", "sonnet_pct"))
            if usage.get(k) is not None]
    if live:
        block("ctd_claude_usage_pct", "Claude subscription window utilisation percentage.")
        for w, v in live:
            lines.append(f'ctd_claude_usage_pct{{window="{w}"}} {_num(v)}')

    # No combined weekly savings or subscription-account metrics in Codex.

    ts = snap.get("timestamp")
    if ts:
        try:
            epoch = datetime.fromisoformat(ts).timestamp()
            block("ctd_snapshot_timestamp_seconds", "Unix time the current snapshot was produced.")
            lines.append(f"ctd_snapshot_timestamp_seconds {_num(round(epoch, 3))}")
        except (ValueError, TypeError):
            pass

    return "\n".join(lines) + "\n"


# --- Routes ---

@app.route("/")
def index():
    panel = Path(__file__).with_name('components.html').read_text(encoding='utf-8')
    return _update_routes.page(HTML.replace('__REQUEST_PROXY_PANEL__', REQUEST_PROXY_PANEL_HTML)
                              .replace('__COMPONENTS_PANEL__', panel))


@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "codex-token-saver-dashboard"})


@app.route("/api/stats")
def api_stats():
    """Pull-style JSON snapshot. Same shape as SSE payloads, single response.

    For programmatic consumers (Gotify scripts, Prometheus exporters, status bars)
    that don't want to hold an SSE connection open. Snapshot age is bounded by
    COLLECTOR_INTERVAL (~0.25s by default).
    """
    payload = _collector.snapshot() or {}
    return jsonify(payload)


@app.route("/metrics")
def metrics():
    """Prometheus text exposition of the current snapshot. No extra deps.

    Lets a homelab monitoring stack scrape token savings, per-tool health,
    Claude usage windows, and snapshot freshness without holding an SSE
    connection open or re-parsing the /api/stats JSON.
    """
    body = _render_metrics(_collector.snapshot() or {})
    return Response(body, mimetype="text/plain; version=0.0.4; charset=utf-8")


@app.route("/events")
def events():
    def stream():
        while True:
            payload = _collector.snapshot() or {}
            yield f"data: {json.dumps(payload)}\n\n"
            time.sleep(SSE_INTERVAL)

    return Response(
        stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    app.run(host=HOST, port=PORT, debug=False, threaded=True)
