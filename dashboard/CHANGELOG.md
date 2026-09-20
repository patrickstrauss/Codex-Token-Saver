# Changelog

All notable changes to this project are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.5.0] - 2026-05-30

### Added

- **Prometheus `/metrics` endpoint.** Text exposition (v0.0.4) of combined and
  per-tool token savings, per-tool collector health (`ctd_tool_health`), Claude
  subscription usage percentages, weekly savings, daily burn rate, and a
  `ctd_snapshot_timestamp_seconds` gauge for staleness alerting. Pure formatting
  over the existing snapshot, no new dependencies; complements `/api/stats` for
  scrapers that prefer the Prometheus format.
- **`HOST` environment variable** (default `0.0.0.0`) for the bind address. Set
  `127.0.0.1` to expose the dashboard only behind a reverse proxy.

### Fixed

- **Live activity feed no longer snaps to the top every push.** A full
  `innerHTML` rebuild on each SSE tick discarded the user's scroll position, so
  older entries could never be read. The feed now pauses its rebuild while the
  user has scrolled down (showing a "scroll up to resume" hint) and resumes when
  they return to the top.
- **SSE disconnects are now visible.** When the event stream drops, the header
  pulse-dot turns red with a "Live feed disconnected" tooltip instead of the
  board silently freezing on stale data under a green "healthy" dot. A staleness
  watchdog also flags a frozen board when no message arrives for 15 s even if the
  connection stays open. State clears automatically on reconnect.
- **`Saved Last Week` showed `--` for a genuine zero.** A truthy check treated a
  real `0` as "no data"; it now distinguishes `0` from missing, matching the
  adjacent burn-rate field.
- **`formatTokens` mangled negative values**, emitting an unscaled raw integer
  (e.g. `-1500000`) inconsistent with every other figure. It now scales on the
  magnitude and re-applies the sign (`-1.5M`).
- **`_save_weekly_cache` is now atomic.** It wrote `weekly.json` in place, so a
  crash or container stop mid-write left a truncated file that
  `_load_weekly_cache` discarded, silently resetting the weekly baseline and
  last-week total to zero. The snapshot is now written to a temp file and
  `os.replace()`d into place.
- **Time-bomb test fixture.** `TestUsageFromHeadroom` hardcoded reset timestamps
  that lapsed into the past, so `collect_claude_usage`'s stale-window scrub
  started failing the suite after the dates passed. The fixture now derives
  resets relative to now.

### Changed

- Removed a redundant duplicate assignment in `collect_jcodemunch`.
- Pinned runtime dependencies (`flask>=3.0,<4`, `python-dotenv>=1.0,<2`) for
  reproducible builds.

### Docs

- Corrected the `SSE_INTERVAL` default in the README and `.env.example` (was
  documented as `30`, lowered to `2` back in v1.2.0).
- Documented the previously-missing `HOST`, `JDOCMUNCH_BIN`,
  `JDATAMUNCH_INDEX_DIR`, `JDATAMUNCH_BIN`, and `COLLECTOR_INTERVAL` environment
  variables; added jDataMunch to "What it shows" and the architecture overview;
  added `/api/stats` and `/metrics` to the API table.
- Restored `CHANGELOG` version link-reference definitions (had stopped at 1.2.0).

### Tests

- 12 new tests: Prometheus exposition rendering and route behaviour; atomic
  weekly-cache write (round-trip, no temp-file leak, prior file survives a failed
  write). Total suite: 81 -> 93 passing.

## [1.4.0] - 2026-05-16

### Fixed

- **"Saved Last Week: -5,072,457,996 tokens" production bug** (closes #3).
  When a baseline value stored by an older dashboard version was larger than
  the current `combined_saved`, the weekly rotation arithmetic produced a
  giant negative number that was displayed to the user as if real. Two
  guards:
  - rotation clamps `last_week_savings = max(0, combined_saved - baseline)`
  - per-tick clamp re-snapshots the baseline whenever the running delta
    goes negative, so a legacy cache file with a -5B value heals on the
    next tick instead of leaking forever
- **WCAG 2 AA colour-contrast across the whole UI** — header centre/right,
  card version, card subtitle, card stats, feed time/cmd/count, and ticker
  separator all moved from 2.5-4.2:1 grays to 4.5:1+ tokens (`#9aa`, `#aab`,
  `#cdd`, `#aaa`). axe-core scan: 5 violations -> 0.
- **Inactive cards no longer crush their own contrast.** Was `opacity: 0.5`
  on `.card.inactive` which halved the rendered luminance of every text in
  the card (e.g. jDataMunch's "JDATAMUNCH" label rendered at 2.48:1 on
  `#0e0e16`). Replaced with a desaturated border + explicit dimmer value
  colour, so the inactive cue stays visible without breaking AA.
- **Muted feed rows** had the same `opacity: 0.6` issue, dropping feed time,
  tool labels, and saving values below AA. Same treatment: opacity gone,
  dimmer colour tokens applied per element.
- **Live activity feed is now keyboard-accessible.** `#feed` had
  `overflow: auto` but no `tabindex`, so keyboard-only users couldn't scroll
  through history. Added `tabindex="0"`, `role="log"`, `aria-live="polite"`,
  and a `:focus-visible` outline. WCAG 2.1.1 A.
- **Mobile feed (≤480px) is now readable.** Previously the command column
  compressed to zero width on phones, so users saw timestamps + tool labels
  but no command text. Rows now wrap with the command on its own line.

### Added

- **Document landmarks for screen readers.** Visually-hidden `<h1>`, wrapped
  body in `<main role="main">`, header is now `<header role="banner">`. Axe's
  `landmark-one-main`, `page-has-heading-one`, and `region` violations cleared.

### Changed

- `formatTokens()` now formats billions as `5.1B` instead of `5078.0M`.
  Headroom's lifetime number was wrapping past three significant digits.

### Tests

- 3 new tests for weekly-savings clamping (rotation never negative, per-tick
  baseline re-snapshot, legacy negative cache file is healed on read).
  Total suite: 78 -> 81 passing.

### Notes

- Findings sourced from a live audit of https://tools.lucknet.uk/ on
  2026-05-16. Audit checkpoint at /tmp/ui-audit-ctd-1747438800.md;
  consolidated report filed as Gitea issue #3 with before/after screenshots.

## [1.3.0] - 2026-05-16

### Fixed

- **Headroom card was understating savings by 5 orders of magnitude.** The
  card read `tokens.saved` from `/stats`, which is the **session-only**
  counter that resets after 60 minutes of inactivity. The dashboard's
  headline metric is token savings, but Headroom's lifetime contribution
  (`persistent_savings.lifetime.tokens_saved`) was ignored — so a typical
  user saw ~20K tokens displayed when the real lifetime value was ~5B.
  Now reads lifetime as the headline; session is exposed as `session_saved`
  for consumers that want it.

### Added

- **Headroom card now shows real dollar savings.** Pulls
  `persistent_savings.lifetime.compression_savings_usd` (compression discount)
  and `prefix_cache.totals.savings_usd` (provider cache-read discount, the
  90%-off line on Anthropic's pricing page). On a moderately active homelab
  this surfaces tens of thousands of dollars of accumulated savings that
  were previously invisible.
- **Header pulse-dot reflects worst-tool health.** Was always green; now
  turns amber on "stale" and red on "error" so glanceable status works.
- **Cache-hit-rate stat on Headroom card.** Surfaces
  `prefix_cache.totals.hit_rate` alongside sessions. Useful for diagnosing
  CacheAligner effectiveness without `curl /stats`.
- **Saved $ chip in the stats ticker.** Sums Headroom compression + cache
  savings into one headline figure (k-formatted at >=$1000).
- **`/api/stats` pull endpoint.** Returns the same snapshot SSE emits,
  as a one-shot JSON response. For Gotify scripts, status bars, and
  Prometheus exporters that don't want to hold an SSE connection open.
- **jDataMunch tile** (5th tool card; merged from 1.2.3-Unreleased). Mirrors
  jCodeMunch / jDocMunch: reads `~/.data-index/_savings.json`, counts
  indexed datasets (JSON + DB files), tracks freshness, and feeds the shared
  sparkline and activity feed pipeline. Teal accent (`#1dd1a1`).
- `JDATAMUNCH_INDEX_DIR` and `JDATAMUNCH_BIN` env vars (defaults
  `~/.data-index` and `jdatamunch-mcp`).
- Version resolution falls back to `pipx list --short` because
  jdatamunch-mcp 0.8.4 prints argparse usage on `--version` and exits
  non-zero.
- "no datasets yet" placeholder so the card renders cleanly with the
  correct version label even before the first MCP call creates the index dir.

### Changed

- **`collect_claude_usage` now prefers Headroom over a direct Anthropic API
  call.** Headroom already polls `/oauth/usage` on a tight schedule and
  caches the result in `subscription_window.latest`. Reading from there
  means: no OAuth token needed, no 429 risk, fresher data. The direct call
  is now a fallback for when Headroom is unreachable. Each response carries
  a `source: "headroom" | "anthropic"` field so the origin is auditable.

### Tests

- 12 new tests covering the lifetime accounting fix, the Headroom
  subscription window fallback, the overall-health rollup, and the
  new `/api/stats` endpoint. Total suite: 78 passing.

## [1.2.2] - 2026-04-17

Round-2 follow-ups from the 1.2.1 code review (issue #2) plus release
automation adopted from the iplayer-arr template. No behaviour change
to the SSE payload; internal tightening, additional test coverage, and
a full GitHub Actions CI + release pipeline.

### Release automation

- `.github/workflows/ci.yml` runs the pytest suite on every push and PR.
- `.github/workflows/release.yml` builds multi-arch Docker images
  (linux/amd64 + linux/arm64), pushes to GHCR and Docker Hub, syncs the
  README to the Hub description, and publishes a GitHub Release using
  the tag annotation as the body — all triggered by pushing a `v*` tag.
- Dockerfile accepts `VERSION` and `BUILD_DATE` build args, stamps OCI
  labels, and exports `APP_VERSION` / `APP_BUILD_DATE` env vars.
- README badge block widened to the 8-badge standard (CI, Release,
  Licence, GHCR, Docker Hub, Pulls, Image Size, Platforms).

### Added

- Module constant `_USAGE_WINDOW_KEYS` — single source of truth for the
  Anthropic usage windows. Each tuple is `(pct_key, reset_key, api_block)`
  and is consumed by both `collect_claude_usage` (result build) and
  `_scrub_stale_windows` (iteration). Adding a fourth window now requires
  one edit instead of two.
- `_scrubbed_cache_snapshot()` helper — returns a scrubbed **copy** of
  `_usage_cache` so mutation stays off the shared dict. Readers can no
  longer observe `_usage_cache` mid-scrub.
- Legacy OpenAI key regex: `\bsk-[A-Za-z0-9]{32,}\b` catches classic
  `sk-<48 alphanumeric>` keys with no provider segment.
- Eleven new tests: SHA / `sha256:` redaction pins, legacy OpenAI key
  coverage, `sk-<UPPERCASE>-…` provider rule, `_scrub_stale_windows`
  idempotence, asymmetric absence symmetry, end-to-end cache-hit scrubbing
  (x2), weekly-rotation halt when `weekly_reset=None`. Total: 66 tests.

### Changed

- `sk-<provider>-` rule now accepts both cases (`[A-Za-z]{2,}` instead of
  `[a-z]{2,}`) so `sk-OR-…` matches alongside `sk-or-…`.
- `_scrub_stale_windows` now guards `usage[pct_key] = None` with
  `if pct_key in usage`. Previously a stale reset with an absent pct key
  would materialise the pct key as None; now absence is preserved.
- `collect_claude_usage` returns a scrubbed **copy** of the cache on every
  path; the authoritative `_usage_cache` dict is never mutated by scrubbing.

### Documented

- Explicit inline comment on the naked-hex rule acknowledging that full
  40-char git SHAs and `sha256:…` digests are redacted as a side effect of
  catching Gitea-style opaque tokens. Behaviour is pinned by tests.
- `_scrub_stale_windows` docstring explains the intentional interaction
  with `collect_all`'s weekly rotation: a dead window with `weekly_reset`
  scrubbed to None will not rotate a baseline it cannot verify.

## [1.2.1] - 2026-04-17

Correctness & secrets-safety upgrade. Two bug fixes and a test suite
bootstrap. SSE payload schema unchanged; no user-visible UI changes.

### Added

- Test suite bootstrap: `pytest.ini`, `requirements-dev.txt`, `tests/test_app.py`
  with 55 tests across four groups — regression net for existing
  `_SECRET_PATTERNS`, coverage for new patterns, property-based hypothesis
  test on long hex tokens (200 examples), `_reset_in_future`,
  `_scrub_stale_windows`, `_group_history` burst-collapse, weekly cache
  rotation.
- Seven new regex rules in `_SECRET_PATTERNS` covering GitHub prefixes
  (`ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`), GitLab (`glpat-`), Slack
  (`xox[bpar]-`), generalised `sk-<provider>-` keys, URL-embedded
  credentials, JSON-shaped secret values, and naked hex tokens >=32
  chars. The 32-char threshold preserves 7 and 8 char git SHAs.
- `_reset_in_future(iso_ts)` helper: true iff the timestamp is parseable
  ISO-8601 strictly in the future (UTC). Returns False for None, empty,
  or unparseable input.
- `_scrub_stale_windows(usage)` helper: nulls out pct/reset pairs whose
  reset has passed. Applied at every return path in
  `collect_claude_usage`.
- `.dockerignore` entries for `tests/`, `.pytest_cache/`, `.hypothesis/`,
  `requirements-dev.txt`.

### Fixed

- Ghost-window bug: `collect_claude_usage` served the last successful
  cache indefinitely during Anthropic rate-limit (HTTP 429) events. Once
  the cached `weekly_reset` / `session_reset` / `sonnet_reset` timestamp
  passed, the cached pct value referred to a dead window but still
  displayed as live data. Every return path now scrubs stale pct/reset
  pairs before handing them to the caller. `_usage_cache` still holds
  the raw fetched data so a subsequent successful fetch re-populates.
- Security gap in `_sanitise_cmd`: naked opaque tokens without a keyword
  prefix could reach the public dashboard feed unredacted. Examples that
  now get caught: 40-char Gitea-style hex tokens, GitHub `ghp_...` tokens
  pasted into commands, URL-embedded `user:password@host` credentials,
  JSON bodies with `"api_key": "..."`-style secrets. Existing patterns
  remain unchanged and continue to catch their cases.

### Follow-ups queued

- `_sanitise_cmd` round 2: classic OpenAI `sk-<48char>` (no provider
  prefix), uppercase provider in `sk-<prov>-`, negative tests pinning
  current false-positive behaviour (full 40-char SHAs and `sha256:`
  digests do get redacted — acceptable trade-off but worth pinning).
- `_scrub_stale_windows` round 2: hoist pct/reset key tuple to a module
  constant, use `dict(_usage_cache)` copy at cache-hit returns for
  thread-safety defence-in-depth, add cache-hit end-to-end and
  idempotence tests, document interaction with `collect_all` weekly
  rotation.

## [1.2.0] - 2026-04-09

Activity feed realtime rewrite. The LIVE ACTIVITY feed now updates within
~2 seconds of the underlying tool running, holds up to 100 scrollable items,
and no longer lets bursty rtk activity push jcodemunch and jdocmunch entries
out of the viewable window.

### Added

- `DashboardCollector` background daemon thread that ticks every 250 ms and
  stores the latest payload as a shared snapshot under a lock. The `/events`
  SSE endpoint became a thin reader on a 2 s heartbeat, decoupling data
  freshness from transmission cadence.
- `_group_history()` pass wired into `collect_all()` with a 10 s burst window
  to collapse consecutive same-tool same-prefix entries so rtk bursts do not
  dominate the 100-slot feed.
- Thin dark scrollbar on the activity feed, matching the terminal aesthetic.
- Dynamic `showing last N` feed count label that reflects the actual
  rendered row count.
- `CLAUDE TOOLS` header is now a link to the project source on GitHub.
- Cold-start guard on the COMBINED banner so it reads `0` instead of
  `undefined` for the first ~2 s after service restart.
- Three new `_sanitise_cmd` regex patterns for HTTP auth headers
  (`Authorization: token/Bearer/Basic`), `X-*-Key` / `X-*-Token` custom
  headers, and `curl -u user:pass`.

### Changed

- `SSE_INTERVAL` default lowered from 30 s to 2 s. Now only a heartbeat,
  not a data-freshness bound.
- All history caps bumped from 20 to 100: RTK SQLite query limit,
  headroom / jcodemunch / jdocmunch in-memory rings, `collect_all` merged
  trim, and the frontend render loop.
- `collect_rtk`, `collect_jcodemunch`, `collect_jdocmunch` now read version
  strings from a cache populated once at collector startup instead of
  spawning version subprocesses on every SSE poll.
- `collect_jcodemunch` now watches the max mtime across `session_stats.json`,
  `_savings.json`, and all `local-*.db` files (previously only
  `session_stats.json`), catching more jcodemunch activity between the
  upstream tool's periodic flushes.

### Fixed

- Pre-existing security gap: `_sanitise_cmd` only redacted `KEY=value` style
  env vars and Anthropic `sk-ant-*` keys. HTTP auth headers from rtk-wrapped
  curl commands were passed through unredacted. The 20 to 100 cap bump made
  this more visible because older commands stayed in the viewable feed for
  longer. Patterns extended to cover the common auth header shapes. The
  historical rtk SQLite database on the running host was also scrubbed of
  leaked values.

## [1.1.0] - 2026-03-31

Dashboard improvement pass: feed grouping, progress bars, health indicators,
visual polish.

### Added

- Tool health indicator dots in card headers (ok / stale / error).
- Progress bars repurposed: RTK efficiency, headroom compression ratio,
  jcodemunch and jdocmunch freshness (decays linearly over 60 minutes of
  inactivity).
- Smart activity feed grouping in `collect_all` to collapse bursty command
  sequences into single grouped entries (see v1.2.0 for the final wiring).

### Changed

- Feed noise reduction and updated styling for grouped entries.

### Fixed

- Ticker readability, unicode clock, and desktop overflow issues.
- Corrected the RTK repository link to `rtk-ai/rtk`.

## [1.0.0] - 2026-03-31

Initial public release.

### Added

- Single-file Flask dashboard (`app.py`) with embedded HTML / CSS / JS.
- SSE-backed live update of token savings for rtk, headroom, jcodemunch,
  and jdocmunch, with per-tool cards, sparklines, and a live activity feed.
- Weekly savings tracker with current week, last week, daily burn rate,
  and reset countdown derived from the Anthropic usage API.
- `/health` endpoint for service monitoring.

### Fixed

- Mobile viewport scrolling.

[1.5.0]: https://github.com/Will-Luck/claude-tools-dashboard/releases/tag/v1.5.0
[1.4.0]: https://github.com/Will-Luck/claude-tools-dashboard/releases/tag/v1.4.0
[1.3.0]: https://github.com/Will-Luck/claude-tools-dashboard/releases/tag/v1.3.0
[1.2.2]: https://github.com/Will-Luck/claude-tools-dashboard/releases/tag/v1.2.2
[1.2.1]: https://github.com/Will-Luck/claude-tools-dashboard/releases/tag/v1.2.1
[1.2.0]: https://github.com/Will-Luck/claude-tools-dashboard/releases/tag/v1.2.0
[1.1.0]: https://github.com/Will-Luck/claude-tools-dashboard/releases/tag/v1.1.0
[1.0.0]: https://github.com/Will-Luck/claude-tools-dashboard/releases/tag/v1.0.0
