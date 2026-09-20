# Reliable bundle implementation plan

> Execution resumed explicitly by the user on 2026-09-20. Use the existing audit/design, Ponytail minimality, meaningful failing regression tests, and parallel agents with disjoint ownership. No further plan approval is needed for this authorized work.

**Goal:** Restore dependable Headroom operation, independent library controls, honest activity metrics, and usable Serena and local summaries in Codex Desktop.

**Architecture:** Reuse the existing Windows tray, Flask dashboard, native command launcher and managed request controller. Store small shared component preferences; preserve the existing request-routing owner. Add the missing local-summary controller/MCP adapter and enforce optional settings at tool invocation boundaries.

**Tech stack:** Python stdlib/Flask/MCP, Windows PowerShell/C#, installed RTK and Headroom, isolated Serena, LangMem and llama.cpp.

**Spec:** ../../audit-2026-09-20/CONTROL-DESIGN.md

## Constraints and review focus

- Preserve active requests, model/reasoning, user configuration, original content and installed histories. Never replay dispatched requests.
- Off must be enforced by already-loaded wrappers; show genuine reload/dependency requirements.
- No overlapping savings sums, fabricated quota savings or synthetic production ledger activity.
- Check malformed preferences, concurrent writes, Windows quoting, stale/reused PIDs, expired original references, partial rollout lines, changed transcript prefixes and cancelled local model jobs.
- Monitor the shared weekly allowance (baseline 0%, implementation starting at 1%, ceiling 10% in the same reset window).

## Work items

- [x] Create source-only checkout and preserve the audit/design.
- [x] Recovery: `desktop_proxy_service.py`, `service_control.py`, startup scripts and `desktop_proxy_control.py`; reproduce stale supervisor state and backend loss with isolated fixtures, add heartbeat/process identity/error reporting, recover the owned supervisor through existing tray maintenance, fix ledger freshness. Run their existing test families.
- [x] Controls: `bundle_preferences.py`, native RTK launcher and local Headroom call sites. API: `load_preferences(root)`, `preference_status(root) -> {values,error}`, `set_preference(root,key,bool)`. File: `settings/components.json`, schema 1; RTK/local defaults true, Serena/summaries/llama defaults false. Test raw stdout/stderr/exit codes and independent switches before implementation.
- [x] Dashboard: guarded `/api/components` GET and POST `{component,enabled}`, existing managed proxy controls for request compression, recent RTK statistics and effective component state. `/api/local-summaries` supports explicit task selection, refresh, cancel and readable output. Test mutation guards, unavailable dependencies, output escaping and recent metrics.
- [x] Optional tools: finish `local_summaries.py`, `local_summary_mcp.py`, gate Serena calls, and extend `bundle_integrations.py` to persist requested state with configuration rollback. `LocalSummaries(root,codex_home=None)` implements `status`, `list_tasks`, `start`, `cancel`, `get_summary`; source transcripts remain read-only, no encrypted/native compaction replacement.
- [x] Validate local LangMem/llama inference on a synthetic factual fixture and Serena symbol/reference queries on isolated source fixtures; verify changes appear and write tools never appear. Native compaction stays enabled.
- [x] Complete library update integration where supported using staged/pinned candidates and explicit validation. Preserve existing RTK/Headroom updater behavior and rollback. Never advertise unsupported updater actions as working.
- [x] Run core/dashboard suites and native launcher tests, inspect the actual dashboard, perform an independent review, and repair findings.
- [x] Back up changed installed source, deploy only verified files, use managed service recovery, verify live backend identity/original retrieval and dashboard controls. Register optional MCP entries and document restart requirements. Commit/publish source without runtime/private data to the supplied repository.

## Shared interfaces

Request compression is absent from the preferences file: `DesktopProxyControl` remains authoritative. `BundleIntegrations.status()` adds requested state to installed/configured/managed state; `set_enabled` writes owned MCP configuration and corresponding optional preference together, rolling back on failure. Summary starts require both `local_summaries` and `llama_cpp`; saved summaries remain readable while disabled. Defaults do not automatically launch a model.

Release evidence and limits: [RELEASE-2026-09-20.md](../../RELEASE-2026-09-20.md).
