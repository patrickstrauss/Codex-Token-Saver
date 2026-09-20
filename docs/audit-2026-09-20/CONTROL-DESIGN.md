# Component controls and reliability: draft for development resumption

Date: 2026-09-20. Status: proposed, not implemented or enabled by this audit.

## Intended interface

Keep the existing tray app and dashboard. Each component row has an On/Off control, effective status, last actual use, recent savings, and an explanation when it is bypassed. Installed version and Update/Rollback remain beside that component. A saved preference must never be displayed as proof that the running integration is active.

| Component | Meaning of Off | Dependency / timing |
| --- | --- | --- |
| RTK command filtering | Supported external commands produce original output; preserve arguments, stderr, exit code and streaming. Keep RTK administrative commands available. | Apply to the next invocation. Use a validated mapping or upstream passthrough, not indiscriminately stripping `rtk` from arbitrary commands. |
| Headroom local output | Return original local file/command content; bypass further filtering of RTK output. | Independent of RTK and the request proxy. Exact retrieval stays available for existing references. |
| Headroom request compression | Use the existing managed Pause/Restore Direct behavior. | Show pending/restart state for already-open Codex connections; never terminate active work or claim old WebSockets changed immediately. |
| Serena | Stop offering new bundle-managed symbol-tool work. | Off must also be enforced by the loaded wrapper, not solely by deleting future MCP configuration. Explain any Codex reload requirement; finish in-flight reads safely. |
| LangMem local summaries | Do not start new summary jobs. Existing summary files remain readable. | Experimental and explicit task selection only. Native Codex compaction stays enabled. |
| llama.cpp local inference | Do not load the local model or start inference. | LangMem summaries require it. If Off, show summaries as unavailable with the dependency reason. Allow cancelling an owned active job; do not kill unrelated model servers. |

Expose these controls rather than separate switches for every transitive Python dependency. LangMem and llama.cpp remain visible individually because the model runtime also consumes local resources. Keep a single convenient "Local summaries" action while making its prerequisites clear.

## State and interaction rules

- Distinguish Off, Ready, In use, Bypassed, Needs restart and Error. Show the last successful operation and last error separately.
- Use one small, atomically written bundle preference file and the existing guarded dashboard POST mechanism. Keep managed routing logic in its existing controller; do not invent another configuration owner.
- Read preferences at invocation/request boundaries so loaded integrations respect Off. Configuration changes alone cannot disable tools already loaded in an existing task.
- Disabling Headroom local output must not silently disable RTK; disabling RTK must not silently enable another lossy layer. Explain the remaining enabled components.
- Preserve a way to retrieve originals after disabling compression. Remove already-created references only through an explicit retention policy, not an Off switch.
- Do not turn failed readiness into an automatic enable. Use bounded recovery for the owned backend, original/direct fallback when safe, and a visible degraded status.
- Do not replay a model request after it has been dispatched. Service restarts and updates must respect active requests and original-content retention.

## Honest measurement

Default to a recent window (Today / 7 days), with Lifetime secondary. Show attempts, optimized operations, exact bypasses, unsupported operations, failures, last activity and collector freshness. "No recent use" is different from "not installed" or "broken."

Keep RTK, local Headroom and request savings separate. They measure different stages and may overlap; request history can be counted repeatedly. Label token numbers as estimates, not verified reductions of the user's Codex weekly quota or invoice. Show cached input and actual reported usage separately where available; leave unavailable quantities unknown.

Count retrieval cost, compression latency and fallback rate. Record only the delivered result. Keep synthetic validation in a separate test ledger. Large outliers should be visible as contributors rather than silently dominating a headline rate.

## Quality acceptance before enabling changes

Lossy compression cannot promise identical answers for every task. The practical goal is measurable task correctness with exact-content escape routes and automatic raw fallback when checks fail.

1. Compare unchanged output, RTK alone, Headroom alone, and both on the same representative fixtures. Include build failures, test failures, search results, diffs, JSON/CSV, large logs, Unicode/CRLF, binary data, exact source retrieval and content expiry.
2. Require byte-for-byte original delivery for exact requests, machine-parsed output, unsupported formats and protected errors. Preserve process arguments, working directory, stderr, exit status and cancellation behavior.
3. Verify removed content is retrievable through the same advertised reference, protected from recompression, and retained long enough for the session that references it. A missing original must produce an explicit error; never fabricate it.
4. Preserve tool-call/result pairing, identifiers, authentication, model and reasoning settings, streaming order and encrypted native compaction items. Validate complete request fixtures, not just token counts.
5. Evaluate representative task outcomes against known answers (for example, locating every seeded failure and producing a patch that passes the same checks). A higher savings percentage alone is not a release gate.
6. Report net estimated input reduction together with retrieval overhead, latency and failure rate. Agree on performance thresholds before rollout; do not increase compression aggressiveness to satisfy a headline target.
7. Validate restart, crash recovery, update/rollback, and every meaningful on/off combination without changing live user sessions. Then perform a small supervised deployment through existing bundle controls.

## Smallest implementation sequence when development resumes

1. Onboard source and tests into the supplied repository with explicit exclusions for secrets, request/session histories, databases, models, downloaded binaries and virtual environments. Record dependency versions and reproducible installation instructions.
2. Repair the confirmed backend/supervisor reliability issue and replace misleading health indicators with observed state. Add regression coverage for the actual failure mode.
3. Wire independent controls through current launchers/controllers and reuse dashboard security. Do not add a new frontend framework or service manager solely for these switches.
4. Make recent-window savings and coverage visible; protect originals and verify the combined pipeline.
5. Finish and validate the previously paused Serena/local-summary work, then expose their controls and updates. Keep experimental summaries opt-in.

The audit consumes part of the user's shared 10-percentage-point weekly allowance. Recheck the account meter before implementation and periodically during it; preserve room for validation and stop before exceeding the observed allowance. The meter is rounded and account-wide, so exact attribution is unavailable.
