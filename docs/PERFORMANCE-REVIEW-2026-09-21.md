# Real-task performance review — 21 September 2026

The installed ci-7 dashboard and managed request proxy are healthy. RTK is running, Serena is used implicitly, and no new proxy connection failures appeared relative to the previous audit (the cumulative count remains 53). Local summaries and llama.cpp remain off.

## Evidence

The real-task snapshot covers one active coding task and one observed child over approximately 46 minutes. The task remained active; later activity is excluded. Task names and identifiers are omitted.

| Module | Observed result |
| --- | --- |
| Serena | 24 calls; one missing-file error with actionable native fallback. This is a navigation miss, not a stopped server. |
| Headroom tools | 13 exact file reads and 31 request-proxy original retrievals; zero recorded errors. Median invocation times: 13 ms and 37 ms respectively. |
| RTK | Four successful git-status commands. The global ledger records 108 estimated input tokens, 106 output tokens and two avoided tokens for these calls. Small output explains the small reduction. |
| Native commands | All 25 observed native search fragments used pipelines; nine git rev-parse calls consumed machine-readable output. They should retain complete output. A few display-only git-status fragments could use RTK more consistently. |

Separately, the global proxy savings ledger for approximately 165 minutes between the upgrade and the pre-audit cutoff contains 45 positive-savings events, 6,629,570 estimated input tokens and 449,474 estimated avoided tokens. These are all-task counters, not attributable solely to the task above. The 6.78% reduction applies only to those recorded events.

Seven local file-read events in that same pre-audit global window added 1,000 estimated tokens in exact-response overhead. This counter is separate from proxy-original retrieval and request compression. Preserving exact source before editing is intentional; stronger compression is not justified to make this counter increase. Prefer targeted Serena bodies or native ranges where appropriate.

## Fix applied

Headroom 0.37's upstream ledger rejects nonpositive savings, and its proxy emitter only records positive events. The recent dashboard incorrectly called these entries requests and displayed an unqualified reduction percentage. It now labels them **savings events**, qualifies the percentage as within recorded events, and explains the omitted zero-savings requests and expansions. Lifetime counters retain their separate source.

The regression assertion failed before the change; all 35 focused UI, request-window and routing tests passed afterward. Independent review found no blockers. The static dashboard correction was installed locally with a backup and its served bytes verified. Refresh the dashboard to load it. No service restart or routing change was performed. The source fix accompanies this report.

## Remaining maintenance and limitations

The backend is still running an older receipt-publication implementation. Its stale runtime receipt points to an exited competing process; the already-installed fix publishes the receipt only after serving traffic. The old/new source difference changes receipt publication only, not original-content protection. Sixteen isolated preservation/receipt tests passed. Reload the managed backend at an idle maintenance point and verify receipt ownership afterward; active requests were left uninterrupted. This is an attestation gap, not demonstrated content loss.

These observations do not prove unchanged LLM answer quality or actual Codex quota savings. Invocation latency includes useful work, not just added overhead. Do not add local, RTK and request estimates together. Evidence is retained locally under `logs/performance-20260921/`; raw project content and credentials are excluded from this report.
