"""Tests for app.py correctness and secrets handling.

Four test groups:
  1. TestSanitiseCmd — _sanitise_cmd + _SECRET_PATTERNS hardening
  2. TestGhostWindow — _reset_in_future + _scrub_stale_windows
  3. TestGroupHistory — _group_history burst-collapse logic
  4. TestWeeklyCache — weekly cache rotation in collect_all
"""

import time

import app
from hypothesis import given, strategies as st, settings


def test_import_app():
    """Smoke: the app module imports cleanly and exposes its Flask app."""
    assert hasattr(app, "app")
    assert callable(app.app)


# ======================================================================
# TestSanitiseCmd — existing patterns (regression net)
# ======================================================================


class TestSanitiseCmdExistingPatterns:
    """Lock in the current six patterns so we don't break them during hardening."""

    def test_docker_env_flag_short(self):
        result = app._sanitise_cmd("docker run -e SECRET_KEY=hunter2 myimg")
        assert "hunter2" not in result
        assert "-e SECRET_KEY=***" in result

    def test_docker_env_flag_long(self):
        result = app._sanitise_cmd("docker run --env API_TOKEN=abc123 myimg")
        assert "abc123" not in result
        assert "--env API_TOKEN=***" in result

    def test_keyword_env_var(self):
        result = app._sanitise_cmd("export PASSWORD=letmein")
        assert "letmein" not in result
        assert "PASSWORD=***" in result

    def test_keyword_env_var_case_insensitive(self):
        result = app._sanitise_cmd("export MyApiKey=supersecret")
        assert "supersecret" not in result

    def test_sk_ant_anthropic_key(self):
        result = app._sanitise_cmd("echo sk-ant-abc123def456ghi789")
        assert "sk-ant-abc123def456ghi789" not in result
        assert "sk-ant-***" in result

    def test_authorization_bearer(self):
        result = app._sanitise_cmd("curl -H 'Authorization: Bearer eyJhbGciOi123' api.com")
        assert "eyJhbGciOi123" not in result

    def test_authorization_token(self):
        result = app._sanitise_cmd("curl -H 'Authorization: Token abc123xyz' api.com")
        assert "abc123xyz" not in result

    def test_authorization_basic(self):
        result = app._sanitise_cmd("curl -H 'Authorization: Basic dXNlcjpwYXNz' api.com")
        assert "dXNlcjpwYXNz" not in result

    def test_x_api_key_header(self):
        result = app._sanitise_cmd("curl -H 'X-API-Key: sekrit123' api.com")
        assert "sekrit123" not in result

    def test_x_auth_token_header(self):
        result = app._sanitise_cmd("curl -H 'X-Auth-Token: token99' api.com")
        assert "token99" not in result

    def test_curl_u_credentials(self):
        result = app._sanitise_cmd("curl -u admin:hunter2 https://example.com")
        assert "hunter2" not in result

    def test_benign_command_unchanged(self):
        cmd = "git status && docker ps && ls -la /tmp"
        assert app._sanitise_cmd(cmd) == cmd

    def test_none_input(self):
        assert app._sanitise_cmd(None) is None

    def test_empty_string(self):
        assert app._sanitise_cmd("") == ""


# ======================================================================
# TestSanitiseCmd — new patterns (will fail until Task 5 implements them)
# ======================================================================


class TestSanitiseCmdNewPatterns:
    """Secrets that currently slip through. These fail until _SECRET_PATTERNS is extended."""

    def test_github_personal_token(self):
        cmd = "gh auth login --with-token ghp_abcdefghij1234567890abcdefghij1234567890"
        result = app._sanitise_cmd(cmd)
        assert "ghp_abcdefghij1234567890abcdefghij1234567890" not in result

    def test_github_oauth_token(self):
        cmd = "echo gho_abcdefghij1234567890abcdefghij1234567890"
        result = app._sanitise_cmd(cmd)
        assert "gho_abcdefghij1234567890abcdefghij1234567890" not in result

    def test_gitlab_personal_token(self):
        cmd = "curl -H 'PRIVATE-TOKEN: glpat-xxxxxxxxxxxxxxxxxxxx' gitlab.com"
        result = app._sanitise_cmd(cmd)
        assert "glpat-xxxxxxxxxxxxxxxxxxxx" not in result

    def test_slack_bot_token(self):
        cmd = "curl -d token=xoxb-1234567890-abcdefghij slack.com/api/chat"
        result = app._sanitise_cmd(cmd)
        assert "xoxb-1234567890-abcdefghij" not in result

    def test_slack_user_token(self):
        cmd = "echo xoxp-1234567890-abcdefghij"
        result = app._sanitise_cmd(cmd)
        assert "xoxp-1234567890-abcdefghij" not in result

    def test_generalised_sk_provider_key(self):
        cmd = "curl -H 'X-Key: sk-or-abcdef1234567890xyz' api.openrouter.ai"
        result = app._sanitise_cmd(cmd)
        assert "sk-or-abcdef1234567890xyz" not in result

    def test_url_embedded_credentials(self):
        cmd = "git clone https://will:hunter2@github.com/repo.git"
        result = app._sanitise_cmd(cmd)
        assert "hunter2" not in result
        assert "will" in result  # username preserved; only password redacted

    def test_json_api_key(self):
        cmd = 'curl -d \'{"api_key": "sk_live_abc123xyz789"}\' example.com'
        result = app._sanitise_cmd(cmd)
        assert "sk_live_abc123xyz789" not in result

    def test_json_access_token(self):
        cmd = 'curl -d \'{"access_token":"eyJhbGci1234567890"}\' example.com'
        result = app._sanitise_cmd(cmd)
        assert "eyJhbGci1234567890" not in result

    def test_naked_hex_40_char(self):
        """The Gitea-token shape we saw in session: 40-char hex, no prefix."""
        cmd = "rtk proxy curl -H 'Authorization: token 81d89def1444595593923933845b56581a3aa8a3' gitea"
        result = app._sanitise_cmd(cmd)
        assert "81d89def1444595593923933845b56581a3aa8a3" not in result

    def test_naked_hex_32_char(self):
        cmd = "echo abcdef01234567890abcdef0123456789"
        result = app._sanitise_cmd(cmd)
        assert "abcdef01234567890abcdef0123456789" not in result

    def test_short_git_sha_preserved(self):
        """7-char SHAs must survive — they're useful and not secrets."""
        cmd = "git show a1b2c3d"
        assert app._sanitise_cmd(cmd) == cmd

    def test_eight_char_git_sha_preserved(self):
        cmd = "git log a1b2c3d4..HEAD"
        assert app._sanitise_cmd(cmd) == cmd

    def test_full_git_sha_is_redacted_side_effect(self):
        """Trade-off pin: the 32+ hex rule redacts full 40-char git SHAs as a side
        effect of catching Gitea-style opaque tokens. Locked in so a future tweak
        (e.g. adding a negative lookbehind) is a conscious choice."""
        sha = "a1b2c3d4e5f67890a1b2c3d4e5f67890abcdef01"
        cmd = f"git show {sha}"
        assert sha not in app._sanitise_cmd(cmd)

    def test_sha256_digest_is_redacted_side_effect(self):
        """Trade-off pin: sha256:... docker image digests are redacted. The 64-char
        hex body matches the naked-hex rule. Tightening would need negative
        lookbehind or a dedicated sha256: passthrough rule."""
        digest = "sha256:1111111111111111111111111111111111111111111111111111111111111111"
        cmd = f"docker pull myimage@{digest}"
        assert "1111111111111111111111111111111111111111111111111111111111111111" not in app._sanitise_cmd(cmd)

    def test_legacy_openai_key_no_provider(self):
        """Classic OpenAI sk-<48 alphanumeric> with no provider segment."""
        key = "sk-" + "A" * 48
        cmd = f"curl -H 'X-Key: {key}' api.openai.com"
        assert key not in app._sanitise_cmd(cmd)

    def test_legacy_openai_key_mixed_alphanumeric(self):
        """Legacy OpenAI keys mix upper, lower, and digits with no dashes."""
        key = "sk-abcDEF123" + "X" * 40
        cmd = f"echo {key}"
        assert key not in app._sanitise_cmd(cmd)

    def test_sk_provider_uppercase_segment(self):
        """sk-OR-... (uppercase provider) must match the generalised sk-<prov>- rule."""
        key = "sk-OR-" + "a" * 20
        cmd = f"curl -H 'X-Key: {key}' api.openrouter.ai"
        assert key not in app._sanitise_cmd(cmd)


# ======================================================================
# TestSanitiseCmd — property-based on long hex tokens
# ======================================================================


class TestSanitiseCmdProperty:
    """Hypothesis: any all-lowercase hex token ≥32 chars, embedded in any command,
    must not survive _sanitise_cmd."""

    @given(
        hex_token=st.text(alphabet="abcdef0123456789", min_size=32, max_size=80),
        before=st.sampled_from(["", "echo ", "curl -H 'X: ", "rtk proxy curl "]),
        after=st.sampled_from(["", "' api.com", " done", " && echo ok"]),
    )
    @settings(max_examples=200, deadline=None)
    def test_long_hex_tokens_always_redacted(self, hex_token, before, after):
        cmd = before + hex_token + after
        result = app._sanitise_cmd(cmd)
        assert hex_token not in result, f"Hex token survived in: {result!r}"


# ======================================================================
# TestGhostWindow — _reset_in_future + _scrub_stale_windows
# ======================================================================

from datetime import datetime, timedelta, timezone


class TestResetInFuture:
    """_reset_in_future(iso_ts) → True iff iso_ts is a parseable ISO-8601 in the future (UTC)."""

    def test_future_timestamp_returns_true(self):
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        assert app._reset_in_future(future) is True

    def test_past_timestamp_returns_false(self):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        assert app._reset_in_future(past) is False

    def test_none_returns_false(self):
        assert app._reset_in_future(None) is False

    def test_empty_string_returns_false(self):
        assert app._reset_in_future("") is False

    def test_garbage_returns_false(self):
        assert app._reset_in_future("not-a-date") is False

    def test_very_far_future(self):
        far_future = "2099-01-01T00:00:00+00:00"
        assert app._reset_in_future(far_future) is True

    def test_exact_now_returns_false(self):
        # Strict > comparison: an exact now timestamp (no future delta) should be False.
        # We construct a timestamp a microsecond in the past to avoid flake.
        just_past = (datetime.now(timezone.utc) - timedelta(microseconds=1)).isoformat()
        assert app._reset_in_future(just_past) is False


class TestScrubStaleWindows:
    """_scrub_stale_windows nulls out pct+reset pairs whose reset is in the past."""

    def _future(self, hours=1):
        return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()

    def _past(self, hours=1):
        return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    def test_none_input_returns_none(self):
        assert app._scrub_stale_windows(None) is None

    def test_empty_dict_unchanged(self):
        assert app._scrub_stale_windows({}) == {}

    def test_all_fresh_windows_untouched(self):
        usage = {
            "session_pct": 45,
            "session_reset": self._future(),
            "weekly_pct": 62,
            "weekly_reset": self._future(),
            "sonnet_pct": 28,
            "sonnet_reset": self._future(),
            "active": True,
        }
        result = app._scrub_stale_windows(usage)
        assert result["session_pct"] == 45
        assert result["weekly_pct"] == 62
        assert result["sonnet_pct"] == 28

    def test_stale_weekly_scrubbed(self):
        usage = {
            "session_pct": 45,
            "session_reset": self._future(),
            "weekly_pct": 62,
            "weekly_reset": self._past(),
            "sonnet_pct": 28,
            "sonnet_reset": self._future(),
        }
        result = app._scrub_stale_windows(usage)
        assert result["session_pct"] == 45
        assert result["weekly_pct"] is None
        assert result["weekly_reset"] is None
        assert result["sonnet_pct"] == 28

    def test_all_stale_scrubbed(self):
        usage = {
            "session_pct": 45,
            "session_reset": self._past(),
            "weekly_pct": 62,
            "weekly_reset": self._past(),
            "sonnet_pct": 28,
            "sonnet_reset": self._past(),
        }
        result = app._scrub_stale_windows(usage)
        assert result["session_pct"] is None
        assert result["weekly_pct"] is None
        assert result["sonnet_pct"] is None

    def test_reset_missing_pct_preserved(self):
        # If reset key is absent entirely, pct stays untouched (no way to verify staleness).
        usage = {"session_pct": 45, "weekly_pct": 62}
        result = app._scrub_stale_windows(usage)
        assert result["session_pct"] == 45
        assert result["weekly_pct"] == 62

    def test_pct_absent_reset_stale_does_not_materialise_pct(self):
        # Asymmetric-case pin: a stale reset with no corresponding pct key must
        # NOT create the pct key. The scrub preserves absence symmetry.
        usage = {"weekly_reset": self._past()}
        result = app._scrub_stale_windows(usage)
        assert "weekly_pct" not in result
        assert result["weekly_reset"] is None

    def test_pct_absent_reset_fresh_does_not_materialise_pct(self):
        # Control: fresh reset with absent pct leaves both alone (no materialisation).
        usage = {"weekly_reset": self._future()}
        result = app._scrub_stale_windows(usage)
        assert "weekly_pct" not in result
        assert result["weekly_reset"] == usage["weekly_reset"]

    def test_scrub_is_idempotent(self):
        # Locking in implicit idempotence so a future "optimisation" can't break it.
        usage = {
            "session_pct": 45,
            "session_reset": self._future(),
            "weekly_pct": 62,
            "weekly_reset": self._past(),
            "sonnet_pct": 28,
            "sonnet_reset": self._past(),
        }
        once = app._scrub_stale_windows(dict(usage))
        twice = app._scrub_stale_windows(app._scrub_stale_windows(dict(usage)))
        assert once == twice


# ======================================================================
# TestCollectClaudeUsageCacheScrub — end-to-end scrub on cache hit
# ======================================================================


class TestDisabledAccountUsage:
    """Codex must not serve account-usage caches inherited from upstream."""

    def test_account_cache_is_ignored(self, monkeypatch):
        monkeypatch.setattr(app, "_usage_cache", {"active": True, "session_pct": 50})
        monkeypatch.setattr(app, "_usage_cache_time", time.time())
        assert app.collect_claude_usage() is None


# ======================================================================
# TestGroupHistory — burst-collapse logic
# ======================================================================


def _ts(seconds_ago):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


class TestGroupHistory:
    """_group_history collapses consecutive same-tool same-prefix entries within 10s."""

    def test_empty_input_returns_empty(self):
        assert app._group_history([]) == []

    def test_single_entry_passes_through(self):
        entry = {"time": _ts(0), "tool": "rtk", "cmd": "git status", "saved_tokens": 100, "saved_pct": 50}
        assert app._group_history([entry]) == [entry]

    def test_two_same_prefix_within_10s_collapse(self):
        entries = [
            {"time": _ts(0), "tool": "rtk", "cmd": "git status", "saved_tokens": 100, "saved_pct": 50},
            {"time": _ts(3), "tool": "rtk", "cmd": "git diff", "saved_tokens": 200, "saved_pct": 60},
        ]
        result = app._group_history(entries)
        assert len(result) == 1
        assert result[0]["cmd"] == "2x git"
        assert result[0]["saved_tokens"] == 300
        assert result[0]["count"] == 2
        assert result[0]["grouped"] is True

    def test_two_same_prefix_beyond_10s_not_collapsed(self):
        entries = [
            {"time": _ts(0), "tool": "rtk", "cmd": "git status", "saved_tokens": 100, "saved_pct": 50},
            {"time": _ts(15), "tool": "rtk", "cmd": "git diff", "saved_tokens": 200, "saved_pct": 60},
        ]
        result = app._group_history(entries)
        assert len(result) == 2

    def test_different_tools_not_collapsed(self):
        entries = [
            {"time": _ts(0), "tool": "rtk", "cmd": "git status", "saved_tokens": 100, "saved_pct": 50},
            {"time": _ts(2), "tool": "headroom", "cmd": "git status", "saved_tokens": 200, "saved_pct": 60},
        ]
        assert len(app._group_history(entries)) == 2

    def test_high_savings_breaks_batch(self):
        entries = [
            {"time": _ts(0), "tool": "rtk", "cmd": "git diff HEAD", "saved_tokens": 50, "saved_pct": 20},
            {"time": _ts(2), "tool": "rtk", "cmd": "git diff", "saved_tokens": 1500, "saved_pct": 90},
            {"time": _ts(4), "tool": "rtk", "cmd": "git diff", "saved_tokens": 60, "saved_pct": 25},
        ]
        result = app._group_history(entries)
        # High-savings entry stays separate. The surrounding low-savings entries should be
        # returned as-is because the high-entry breaks them into singletons.
        assert len(result) == 3
        assert result[1]["saved_tokens"] == 1500
        assert "grouped" not in result[1]

    def test_weighted_average_pct(self):
        entries = [
            {"time": _ts(0), "tool": "rtk", "cmd": "git a", "saved_tokens": 100, "saved_pct": 10},
            {"time": _ts(2), "tool": "rtk", "cmd": "git b", "saved_tokens": 200, "saved_pct": 50},
            {"time": _ts(4), "tool": "rtk", "cmd": "git c", "saved_tokens": 300, "saved_pct": 30},
        ]
        result = app._group_history(entries)
        # Weights are max(saved, 1): 100, 200, 300 → weighted pct = (10*100 + 50*200 + 30*300)/600 = 33.3
        assert len(result) == 1
        assert result[0]["saved_pct"] == 33.3
        assert result[0]["saved_tokens"] == 600

    def test_three_entry_burst(self):
        entries = [
            {"time": _ts(0), "tool": "rtk", "cmd": "git a", "saved_tokens": 100, "saved_pct": 10},
            {"time": _ts(2), "tool": "rtk", "cmd": "git b", "saved_tokens": 100, "saved_pct": 10},
            {"time": _ts(4), "tool": "rtk", "cmd": "git c", "saved_tokens": 100, "saved_pct": 10},
        ]
        result = app._group_history(entries)
        assert len(result) == 1
        assert result[0]["cmd"] == "3x git"
        assert result[0]["count"] == 3

    def test_unparseable_timestamp_breaks_batch(self):
        entries = [
            {"time": _ts(0), "tool": "rtk", "cmd": "git a", "saved_tokens": 100, "saved_pct": 10},
            {"time": "garbage", "tool": "rtk", "cmd": "git b", "saved_tokens": 200, "saved_pct": 20},
        ]
        result = app._group_history(entries)
        assert len(result) == 2

    def test_singleton_between_groups(self):
        entries = [
            {"time": _ts(0), "tool": "rtk", "cmd": "git a", "saved_tokens": 100, "saved_pct": 10},
            {"time": _ts(2), "tool": "rtk", "cmd": "git b", "saved_tokens": 100, "saved_pct": 10},
            {"time": _ts(3), "tool": "rtk", "cmd": "docker ps", "saved_tokens": 100, "saved_pct": 10},
            {"time": _ts(5), "tool": "rtk", "cmd": "docker ls", "saved_tokens": 100, "saved_pct": 10},
        ]
        result = app._group_history(entries)
        # git burst → "2x git", then docker burst → "2x docker"
        assert len(result) == 2
        assert result[0]["cmd"] == "2x git"
        assert result[1]["cmd"] == "2x docker"


# ======================================================================
# TestWeeklyCache — rotation in collect_all
# ======================================================================

import json
import os


class TestDisabledCombinedWeeklyTracking:
    """Different-scope savings cannot become an aggregate weekly figure."""

    def test_no_combined_weekly_totals_or_account_cache_access(self, monkeypatch):
        monkeypatch.setattr(app, "collect_rtk", lambda: {"active": True, "total_saved": 100, "history": []})
        monkeypatch.setattr(app, "collect_headroom", lambda: {"active": True, "total_saved": 200, "history": []})

        def forbidden(*args):
            raise AssertionError("Account/weekly tracking must stay disabled")

        monkeypatch.setattr(app, "collect_claude_usage", forbidden)
        monkeypatch.setattr(app, "_load_weekly_cache", forbidden)
        monkeypatch.setattr(app, "_save_weekly_cache", forbidden)
        result = app.collect_all()
        assert result["combined_saved"] is None
        assert result["combined_saved_usd"] is None
        assert result["weekly"]["disabled"] is True
        assert result["weekly"]["this_week"] is None
        assert result["weekly"]["last_week"] is None
        assert result["weekly"]["burn_rate_daily"] is None


# ======================================================================
# TestHeadroomLifetime — v1.3.0: Headroom shows lifetime, not session
# ======================================================================


class FakeResp:
    """Minimal context-manager that mimics urlopen()."""

    def __init__(self, payload):
        import json as _json
        self._body = _json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def read(self):
        return self._body


class TestHeadroomLifetime:
    """Pre-v1.3.0 the card read tokens.saved (session only). v1.3.0 reads lifetime."""

    def _payload(self, lifetime_tokens, lifetime_usd, hit_rate, cache_usd, session_tokens):
        return {
            "tokens": {"saved": session_tokens, "savings_percent": 6.2},
            "compression_cache": {"active_sessions": 1},
            "persistent_savings": {
                "lifetime": {
                    "tokens_saved": lifetime_tokens,
                    "compression_savings_usd": lifetime_usd,
                    "requests": 29520,
                }
            },
            "prefix_cache": {
                "totals": {"hit_rate": hit_rate, "savings_usd": cache_usd}
            },
        }

    def _patch_urls(self, monkeypatch, stats_payload):
        # Two urlopen() calls: /health then /stats. First returns version, second
        # returns the rich stats payload.
        calls = {"i": 0}

        def fake_urlopen(url, timeout=2):
            calls["i"] += 1
            if calls["i"] == 1:
                return FakeResp({"version": "0.5.25", "status": "healthy"})
            return FakeResp(stats_payload)

        monkeypatch.setattr(app, "urlopen", fake_urlopen)

    def test_lifetime_overrides_session(self, monkeypatch):
        """total_saved must come from persistent_savings.lifetime when populated."""
        self._patch_urls(monkeypatch, self._payload(5_072_499_735, 25324.61, 89.4, 13.66, 23236))
        app._headroom_last_total = 0
        app._headroom_history = []
        result = app.collect_headroom()
        assert result["active"] is True
        assert result["total_saved"] == 5_072_499_735
        assert result["lifetime_saved"] == 5_072_499_735
        assert result["lifetime_savings_usd"] == 25324.61
        assert result["session_saved"] == 23236
        assert result["cache_hit_rate"] == 89.4
        assert result["cache_savings_usd"] == 13.66

    def test_fallback_to_session_when_lifetime_empty(self, monkeypatch):
        """Fresh Headroom install: lifetime is zero, so use session value."""
        self._patch_urls(monkeypatch, self._payload(0, 0, None, 0, 23236))
        app._headroom_last_total = 0
        app._headroom_history = []
        result = app.collect_headroom()
        assert result["total_saved"] == 23236
        assert result["lifetime_saved"] == 0
        assert result["session_saved"] == 23236

    def test_cache_hit_rate_can_be_null(self, monkeypatch):
        """If Headroom hasn't seen a cache hit yet, hit_rate is None — not 0."""
        self._patch_urls(monkeypatch, self._payload(100, 1.0, None, 0, 50))
        app._headroom_last_total = 0
        app._headroom_history = []
        result = app.collect_headroom()
        assert result["cache_hit_rate"] is None


# ======================================================================
# TestUsageFromHeadroom — v1.3.0: skip Anthropic API when Headroom has the data
# ======================================================================


class TestUsageFromHeadroom:
    """_usage_from_headroom() avoids a redundant call to /oauth/usage."""

    def _stats_with_window(self, fh_pct, sd_pct, sonnet_pct):
        # Resets must stay in the future or collect_claude_usage's
        # _scrub_stale_windows nulls the percentages. Compute them relative to
        # now rather than hardcoding dates (which become a time-bomb the moment
        # they pass).
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        return {
            "subscription_window": {
                "latest": {
                    "five_hour": {"utilization_pct": fh_pct, "resets_at": future},
                    "seven_day": {"utilization_pct": sd_pct, "resets_at": future},
                    "seven_day_sonnet": {"utilization_pct": sonnet_pct, "resets_at": None},
                }
            }
        }

    def test_reads_subscription_window(self, monkeypatch):
        payload = self._stats_with_window(7.0, 28.0, 0.0)
        monkeypatch.setattr(app, "urlopen", lambda *a, **k: FakeResp(payload))
        result = app._usage_from_headroom()
        assert result is not None
        assert result["source"] == "headroom"
        assert result["session_pct"] == 7.0
        assert result["weekly_pct"] == 28.0
        assert result["sonnet_pct"] == 0.0

    def test_returns_none_when_no_subscription_data(self, monkeypatch):
        monkeypatch.setattr(app, "urlopen", lambda *a, **k: FakeResp({}))
        assert app._usage_from_headroom() is None

    def test_returns_none_when_urlopen_fails(self, monkeypatch):
        def boom(*a, **k):
            raise OSError("connection refused")
        monkeypatch.setattr(app, "urlopen", boom)
        assert app._usage_from_headroom() is None

    def test_collect_usage_disabled_even_when_headroom_available(self, monkeypatch):
        """When Headroom is reachable, no OAuth call is made."""
        payload = self._stats_with_window(7.0, 28.0, 5.0)
        monkeypatch.setattr(app, "urlopen", lambda *a, **k: FakeResp(payload))

        def must_not_call(*a, **k):
            raise AssertionError("OAuth fallback was used despite Headroom being available")

        monkeypatch.setattr(app, "_read_oauth_token", must_not_call)
        app._usage_cache = {}
        app._usage_cache_time = 0
        result = app.collect_claude_usage()
        assert result is None


# ======================================================================
# TestOverallHealth — v1.3.0: header pulse-dot reflects worst-tool health
# ======================================================================


class TestOverallHealth:
    """Smoke: collect_all() emits overall_health derived from per-tool health.

    Per-tool health is computed from _last_collect_success timestamps inside collect_all:
      - ok:    active AND last_success > 0 AND age < 60s
      - stale: last_success > 0 but stale OR active=False
      - error: last_success == 0 (never succeeded)
    """

    def _stub_all_collectors(self, monkeypatch, active=True):
        """Return active stubs so collect_all populates results without network."""
        stub = lambda: {"active": active, "total_saved": 0, "history": []}
        for name in ("rtk", "headroom", "rtk", "jdocmunch", "rtk"):
            monkeypatch.setattr(app, f"collect_{name}", stub)
        monkeypatch.setattr(app, "collect_claude_usage", lambda: {"active": False})

    def test_all_ok(self, monkeypatch):
        self._stub_all_collectors(monkeypatch, active=True)
        result = app.collect_all()
        assert result["overall_health"] == "ok"

    def test_any_stale_yields_stale(self, monkeypatch):
        """active=False with prior success → stale per the function logic."""
        self._stub_all_collectors(monkeypatch, active=True)
        # Force one tool to be inactive but with prior success in the past
        import time as _time
        app._last_collect_success["rtk"] = _time.time() - 5
        monkeypatch.setattr(
            app, "collect_rtk",
            lambda: {"active": False, "total_saved": 0, "history": []},
        )
        result = app.collect_all()
        assert result["overall_health"] == "stale"

    def test_any_error_yields_error(self, monkeypatch):
        """Collector returns None AND has no prior success → error."""
        self._stub_all_collectors(monkeypatch, active=True)
        # Reset the success ledger to make rtk look brand-new and broken
        app._last_collect_success.pop("rtk", None)
        monkeypatch.setattr(app, "collect_rtk", lambda: None)
        # _last_good must also be empty so it falls back to default-inactive shape
        app._last_good.pop("rtk", None)
        result = app.collect_all()
        assert result["overall_health"] == "error"


# ======================================================================
# TestApiStats — v1.3.0: /api/stats returns snapshot JSON
# ======================================================================


class TestApiStats:
    """The new pull-style JSON endpoint."""

    def test_api_stats_returns_dict(self, monkeypatch):
        # Pre-populate the collector snapshot so we don't need a live tick.
        app._collector._snapshot = {
            "combined_saved": 12345,
            "combined_saved_usd": 1.23,
            "overall_health": "ok",
            "timestamp": "2026-05-16T00:00:00+00:00",
        }
        client = app.app.test_client()
        resp = client.get("/api/stats")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["combined_saved"] == 12345
        assert body["combined_saved_usd"] == 1.23
        assert body["overall_health"] == "ok"

    def test_api_stats_empty_snapshot(self, monkeypatch):
        app._collector._snapshot = None
        client = app.app.test_client()
        resp = client.get("/api/stats")
        assert resp.status_code == 200
        assert resp.get_json() == {}


# ======================================================================
# TestWeeklySavingsClamp — v1.4.0: negative weekly totals are impossible
# ======================================================================


# Combined weekly figures are disabled; covered by TestDisabledCombinedWeeklyTracking.


# ---------------------------------------------------------------------------
# Atomic weekly-cache write (a crash mid-write must not corrupt weekly.json).
# ---------------------------------------------------------------------------
class TestWeeklyCacheAtomic:
    def test_round_trip(self, tmp_path, monkeypatch):
        monkeypatch.setattr(app, "WEEKLY_CACHE_DIR", str(tmp_path))
        data = {"current_week_baseline": 42, "last_week_savings": 7}
        app._save_weekly_cache(data)
        assert app._load_weekly_cache() == data

    def test_no_temp_file_left_after_success(self, tmp_path, monkeypatch):
        monkeypatch.setattr(app, "WEEKLY_CACHE_DIR", str(tmp_path))
        app._save_weekly_cache({"x": 1})
        leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
        assert leftovers == []

    def test_existing_file_survives_failed_write(self, tmp_path, monkeypatch):
        # json.dump raises while filling the temp file; os.replace never runs, so
        # the previous good weekly.json is left intact rather than truncated.
        monkeypatch.setattr(app, "WEEKLY_CACHE_DIR", str(tmp_path))
        app._save_weekly_cache({"good": 1})

        class Unserialisable:
            pass

        try:
            app._save_weekly_cache({"bad": Unserialisable()})
        except TypeError:
            pass
        else:
            raise AssertionError("expected json.dump to raise on unserialisable input")

        assert app._load_weekly_cache() == {"good": 1}


# ---------------------------------------------------------------------------
# Prometheus /metrics exposition.
# ---------------------------------------------------------------------------
class TestRenderMetrics:
    def _snap(self):
        return {
            "timestamp": "2026-05-30T12:00:00+00:00",
            "combined_saved": 5_000_000,
            "combined_saved_usd": 12.34,
            "overall_health": "stale",
            "rtk": {"total_saved": 100, "health": "ok", "active": True},
            "jdatamunch": {"total_saved": 0, "health": "error", "active": False},
            "claude_usage": {"active": True, "session_pct": 7.0, "weekly_pct": None, "sonnet_pct": 5},
            "weekly": {"this_week": 200, "last_week": 0, "burn_rate_daily": 28.5},
        }

    def test_empty_snapshot_reports_down(self):
        out = app._render_metrics({})
        assert "ctd_up 0" in out
        assert "ctd_combined_saved_tokens" not in out

    def test_help_and_type_lines_present(self):
        out = app._render_metrics(self._snap())
        assert "# HELP ctd_tool_saved_tokens" in out
        assert "# TYPE ctd_tool_saved_tokens gauge" in out

    def test_core_values(self):
        out = app._render_metrics(self._snap())
        assert "ctd_up 1" in out
        assert "ctd_combined_saved_tokens" not in out
        assert "ctd_combined_saved_usd" not in out
        assert "ctd_overall_health 1" in out  # stale -> 1

    def test_per_tool_labels(self):
        out = app._render_metrics(self._snap())
        assert 'ctd_tool_saved_tokens{tool="rtk"} 100' in out
        assert 'ctd_tool_health{tool="rtk"} 2' in out
        assert 'ctd_tool_health{tool="jdatamunch"} 0' in out

    def test_null_usage_window_omitted(self):
        out = app._render_metrics(self._snap())
        assert 'ctd_claude_usage_pct{window="session"} 7' in out
        assert 'ctd_claude_usage_pct{window="sonnet"} 5' in out
        assert 'window="weekly"' not in out  # weekly_pct was None

    def test_unsupported_combined_weekly_metrics_omitted(self):
        out = app._render_metrics(self._snap())
        assert "ctd_weekly_saved_tokens" not in out
        assert "ctd_burn_rate_daily_tokens" not in out

    def test_snapshot_timestamp_epoch(self):
        out = app._render_metrics(self._snap())
        assert "ctd_snapshot_timestamp_seconds 1780142400" in out

    def test_route_returns_text_plain(self, monkeypatch):
        class _Stub:
            def snapshot(self):
                return {"combined_saved": 9, "overall_health": "ok", "weekly": {}}

        monkeypatch.setattr(app, "_collector", _Stub())
        resp = app.app.test_client().get("/metrics")
        assert resp.status_code == 200
        assert resp.mimetype == "text/plain"
        assert b"ctd_combined_saved_tokens" not in resp.data
        assert b"ctd_up 1" in resp.data

    def test_route_empty_snapshot_still_200(self, monkeypatch):
        class _Stub:
            def snapshot(self):
                return None

        monkeypatch.setattr(app, "_collector", _Stub())
        resp = app.app.test_client().get("/metrics")
        assert resp.status_code == 200
        assert b"ctd_up 0" in resp.data
