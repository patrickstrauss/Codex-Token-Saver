# Library Updater Implementation Plan

**Goal:** Let the user check, update, and roll back the core token-saving libraries from the existing dashboard.

**Architecture:** A background update manager stages verified candidates, validates them independently, then activates a version manifest or replaces the RTK binary atomically. A runtime selector loads the selected Headroom packages for fresh tool processes. A separate Flask route module exposes fixed actions through guarded local endpoints.

**Tech Stack:** Python, Windows virtual environments, uv, Flask, existing dashboard JavaScript, official PyPI/GitHub release metadata.

**Spec:** `docs/superpowers/specs/2026-09-13-library-updater.md`

## Constraints

- Keep Codex's direct connection, model, reasoning, authentication, hook trust, and savings data unchanged.
- Keep downloads and tests separate from active libraries until validation passes.
- Manual checks and installs only. One operation at a time across app instances.
- Report actual progress, failure, rollback availability, and restart needs.
- Scope the updater to Headroom desktop runtime/dependencies and RTK. Preserve custom integration code.

## Work

- [x] Add and test `runtime_selection.py`; bootstrap it before third-party imports in `desktop_mcp.py` and `desktop_headroom.py`. Validate containment, fallback, candidate interpreters, and process pinning.
- [x] Add and test `bundle_updates.py`: fixed release discovery, safe archives, checksum/version checks, uv staging, isolated validation, atomic activation, rollback, persisted progress, and cross-process lock.
- [x] Add guarded `dashboard/update_routes.py` and an Updates panel in `dashboard/app.py`, with readable version/status/progress and per-component actions.
- [x] Bundle the existing uv tool and license notices without modifying global installations.
- [x] Exercise install and rollback of current official releases in an isolated bundle; leave production current versions selected.
- [x] Run relevant core/dashboard regressions, inspect actual browser behavior, and verify configuration hashes and savings isolation.
- [x] Document usage, limitations, recovery, evidence, and the final installed state.
