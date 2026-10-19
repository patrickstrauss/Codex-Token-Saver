# Native Codex / Token Saver: full coding configuration

Run started 2026-10-19T13:46:13.823166+00:00. Five synthetic paired tasks on one Windows laptop.
Requested model: `gpt-6.1-sol`; reasoning: `low`;
CLI: `codex-cli 0.163.0-alpha.10.2`; Windows: `10.0.26200` (AMD64).

[Raw results](overall-windows.json) · [Frozen tasks, hashes and rubric](overall-windows.manifest.json)

Configuration: **Full coding configuration**.

## Results

![Full coding configuration: reported model input, runtime and strict-check counts](overall-windows.png)

| Task | Native grade | Bundle grade | Native input | Bundle input | Native seconds | Bundle seconds |
|---|---|---|---:|---:|---:|---:|
| log-diagnosis | Pass | Pass | 43,513 | 55,316 | 12.209 | 22.296 |
| symbol-tracing | Pass | Pass | 40,540 | 66,766 | 14.226 | 35.316 |
| structural-audit | Pass | Pass | 54,633 | 46,843 | 14.073 | 18.931 |
| tested-code-fix | Pass | Pass | 41,703 | 100,168 | 32.584 | 54.613 |
| patch-review | Pass | Pass | 26,923 | 55,996 | 7.674 | 18.887 |

| Total | Native | Bundle |
|---|---:|---:|
| Passed tasks | 5 | 5 |
| Input tokens (including cached) | 207,312 | 325,089 |
| Cached input tokens | 107,904 | 209,920 |
| Uncached input tokens | 99,408 | 115,169 |
| Output tokens | 1,682 | 2,314 |
| Wall seconds | 80.766 | 150.043 |

Signed input-token reduction: **-56.81%** (negative means more input with the bundle).
This is reported model input, including cached tokens, across all attempts; failed tasks remain included.
No weekly quota or billing reduction was measured.

## Tool use and quality

The bundle made 7 MCP calls; 0 reported failures.
Native commands remain available in both arms. Tool availability does not imply a call to every component.

Uncached input change: **+15.85%**.
Wall time change: **+85.77%**.
Cache mix differs between arms; these percentages are not interchangeable with cost or quota.


The fixed rubric checks exact structured answers and unchanged fixtures; the code fix also passes
an independent hidden oracle. Final answer prose, command output and credentials are not published.
Exact-answer failures do not, by themselves, prove a semantic error or a bundle regression.

## Scope and limitations

- Explicit tools, automatic Headroom request compression and the reviewed command hook enabled. Browser tasks and other clients excluded.
- Fresh native-provider sessions and separate identical Git fixtures; deterministic randomized arm order.
- Same model, reasoning setting and permissions in both arms. Plugins, connected apps and multi-agent work disabled.
- Execution mode: `danger-full-access`. Temporary synthetic directories are not a VM or security boundary.
- Reported latency includes CLI/MCP startup and model time. Shared workers and provider caches were not flushed.
- All attempts are retained; zero manual retries within this frozen study. Internal network retries are not measured.
- This small sample cannot establish statistical equivalence or predict savings on larger real repositories.
- Daily authentication/configuration unchanged: `True`. VM tests remain paused.

Component versions: headroom `0.40.0`, serena `2.0.0`, laya `0.4.6`, rtk `rtk 1.0.0`, ast-grep `ast-grep 0.50.0`.

## Automatic-path evidence

5 connections routed to Headroom; 36 direct connections; 5 relay failures.
Command hook: 1 rewrites and 8 skips attributed to the benchmark chats.
A routed connection is not proof of a positive compression event. Direct connections can include metadata requests.
Relay failure counts can include abrupt client socket shutdown; they do not prove failed model tasks or request retries.
Shared-backend savings estimates are not attributed to these tasks or added to model usage.
The temporary production relay used a separate loopback port and the existing warm backend.
Only the reviewed production hook bypassed trust in temporary CLI profiles; no daily hook trust was changed.
