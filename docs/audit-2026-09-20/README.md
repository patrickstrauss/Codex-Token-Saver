# Bundle reliability audit

2026-09-20, approximately 13:05–13:14 Asia/Bangkok. Audit and design only; development remains paused at the user's request.

## Findings

| Priority | Confirmed finding | Implication |
| --- | --- | --- |
| First | Headroom relay is online, compression backend is offline, supervisor is absent. | Enabled requests currently bypass compression. Repair recovery before adding more optimization. |
| First | Proxy original-content retrieval depends on the missing backend. | The earlier exact-retrieval fix loaded historically, but is not currently available through that backend. |
| Next | RTK executes and records new commands, but pre-audit history stops September 16. | No current RTK crash was reproduced. The dashboard is not enough to establish automatic use. |
| Next | RTK health is derived from database readability; overall dashboard health uses RTK alone. | Green status can coexist with stale RTK activity and an offline Headroom backend. |
| Next | The optional hook only invokes Headroom; all 3,000 recent pre-audit checks were skipped. | It provides no automatic RTK coverage and little recent Headroom command coverage. |
| Next | One large search accounts for 97.61% of RTK's cumulative estimated savings. | Lifetime 95.06% reduction is unrepresentative. Excluding that event gives 32.18%. |
| Next | Request freshness uses retained history instead of newer lifetime activity. | Headroom's last-activity display can be stale even when the ledger progressed. |

These are token/output estimates, not measured reductions of Codex quota. The existing dashboard already avoids summing overlapping totals; preserve that behavior.

The supervisor's termination cause is unknown. Its scheduled task reports 0xC000013A, but available logs do not identify what stopped it. Do not claim a specific crash cause or that a restart alone permanently repairs it.

## Evidence and proposed work

- [RTK evidence and source references](rtk.md)
- [Headroom evidence and source references](headroom.md)
- [Proposed controls, quality checks and implementation sequence](CONTROL-DESIGN.md)
- [Wayfinder decision map](../../.scratch/reliable-bundle/map.md)

Ponytail directs reuse of the current tray/dashboard, launchers, guarded update routes and managed proxy controller. Wayfinder separates established evidence from the remaining control/quality decisions. No new framework is proposed.

Proposed controls cover RTK, Headroom local output, Headroom requests, Serena, LangMem summaries and llama.cpp. Each distinguishes saved preference from effective state, displays dependency/reload requirements, and preserves exact retrieval after disabling compression. These controls are not implemented by this audit.

Quality validation must compare representative tasks with no filtering, each filter separately, and both together. Protect exact content, error details, tool identities and original retrieval. Lower token counts alone are not proof of equal task quality.

## Repository and budget

GitHub CLI verified that [patrickstrauss/Codex-Token-Saver](https://github.com/patrickstrauss/Codex-Token-Saver) is private and empty. The installed bundle is not a Git checkout. Prepare a source-only repository when development resumes, excluding credentials, private histories, databases, models, binaries and environments. No remote issues, commits or uploads were made.

Codex's weekly meter reported 0% used at the audit baseline and 1% at the final check: an observed increase of one percentage point, shared with all account activity. These rounded account-wide readings are not precise task attribution. The agreed allowance is 10 percentage points for the whole effort, including this audit, in the same weekly window (reset timestamp 1790488833). Approximately nine percentage points of the observed allowance remain. Recheck before resuming; leave room for validation and stop conservatively before the observed allowance is exhausted.

Only local research/design documents were added. Services, routing, installed libraries, Codex settings and executable application code were unchanged. No workload benchmark or production repair was performed.
