# Benchmark methodology

Two different comparisons are needed. Local output reduction can be reproduced
without any model call. It does not establish equal task quality or account quota
savings. A native Codex A/B study must measure those separately.

## Offline, reproducible comparison

Run from the source tree or installation with the installed Headroom Python:

```powershell
& "$env:USERPROFILE\CodexTokenSaver\headroom\.venv\Scripts\python.exe" scripts\benchmark_modules.py --installed "$env:USERPROFILE\CodexTokenSaver" --repeats 5 --output benchmark.json
python scripts\publish_benchmark.py benchmark.json benchmark.md
```

Use the active Headroom runtime's Python if a library update selected a newer
runtime. The dashboard's diagnostics identify the selected runtime. The benchmark
does not change that selection. Git must be installed for the RTK case.

The fixtures are generated in a temporary directory: JSON records with an error,
repetitive logs with a critical failure, a small text file, and a Git diff changing
timeout/retry values. Compare native file/command output with Headroom or RTK
separately. Hash the original, check every declared critical fact in the overview,
and compare retrieved originals byte for byte. RTK recovery repeats native Git
against the unchanged fixture; it does not promise a stored original.

Warm each Headroom case once, then report five paired samples' median latency,
first-call cost and retrieval latency in raw JSON. Token counts use the installed
local tokenizer and include returned headers. Publish the signed reduction before
and after full retrieval, including negative results. The benchmark isolates RTK
history and Headroom caches/ledgers, blocks network access in compression calls,
and makes zero model requests. Never add the per-tool estimates together.

The [checked-in sample](benchmarks/offline-windows.md) includes raw data. It is one
machine's synthetic workload, not an expected percentage for everyone's work.
CI publishes a fresh measurement and runtime inventory from each clean install.
The checked-in 19 October sample used Headroom 0.37.0, tiktoken 0.14.0, Python
3.13.14 and Windows build 26200 x64. It is an existing-install sample, not a
claim that these are the candidate's dependency versions. Log compression and
latency vary with dependency/configuration changes; use a candidate's attached
JSON and inventory when evaluating that candidate. Offline estimates are separate
from the tool-using study below; neither establishes Codex quota savings.

## Opt-in native context pilot

`scripts/benchmark_codex_context.py` generates five deterministic log-diagnosis
fixtures with preregistered answers. It defaults to a plan with zero model calls:

```powershell
python scripts\benchmark_codex_context.py --output context-plan.json
```

An explicitly budgeted run needs `--run --installed PATH --codex PATH_TO_NATIVE_EXE
--model MODEL --output context-result.json`. Use the installed Headroom Python.
`--pairs 1` makes at most two CLI invocations for a pilot. `--token-budget` stops
between tasks using reported input/output usage; it cannot cap one task or measure
internal network retries. The CLI must support `exec --ephemeral --json
--output-schema`. See the [official noninteractive CLI guide](https://developers.openai.com/codex/noninteractive/).

The runner copies an existing native ChatGPT login into a temporary OS profile,
keeps global configuration/authentication unchanged, uses fresh ephemeral sessions
and removes the temporary profile afterward. It never publishes credentials,
prompts or raw CLI diagnostics. Do not run it on an untrusted host. Local Headroom
compression is offline; model diagnosis uses the native provider. No paid calls
are part of CI. Treat its exact-answer rubric as a small context experiment, not
a whole-bundle coding benchmark or test of autonomous tool selection.

The [19 October pilot report](benchmarks/native-context-pilot.json) records one
failed native CLI invocation (CLI 0.117.0, requested `gpt-6.1-sol`). It reported no
usage or valid answer; the treatment arm was not run. The failure is unclassified,
the daily auth file remained unchanged and no manual retry was made. This is not
evidence of model availability, equivalent answer quality, or token/quota savings.
No global authentication, routing or CLI installation was changed to repair the pilot.

## Tool-using native Codex study

The [19 October results](benchmarks/coding-windows.md),
[raw JSON](benchmarks/coding-windows.json) and
[frozen manifest](benchmarks/coding-windows.manifest.json) cover five paired tasks:
log diagnosis, symbol tracing, structural search, a tested code fix and Git patch
review. The model investigates files and edits/tests code using real tools.
This is an end-to-end test of **explicit tool availability**, not the automatic
request proxy, RTK hook, browser flow or every component's individual effectiveness.

The bundle used **19.28% more reported input tokens** and **35.81% more wall time**.
Native and bundle each passed **4/5** strict checks. Both failed the exact-answer
symbol rubric; both passed the independent hidden code-fix oracle and preserved
the immutable fixtures. No task was discarded or retried within the frozen study.
The result does not establish semantic equivalence: exact-answer failures can
include formatting differences, and candidate answers were not retained for
manual regrading. A future study should preregister accepted qualified-name/path
variants and retain sanitized synthetic answers before making quality claims.

Three successful MCP calls occurred: Serena activation/symbol lookup and Laya
structural search. Headroom and RTK were available but no direct call to either
was recorded in the measured pairs. Native command fallback remained available.
Their automatic paths were disabled; this study cannot evaluate their savings.
Registering tools does not make Codex select every tool. On these short tasks,
registration/context and startup costs outweighed any measured benefit.

Hardware: Intel Core Ultra 7 258V, 8 cores/logical processors, 31.5 GiB usable RAM,
Windows build 26200 x64. Requested model `gpt-6.1-sol`, low reasoning, desktop CLI
0.163.0-alpha.10.2. Component versions and source hashes are in the raw report.
Five synthetic pairs on one machine are insufficient for statistical conclusions
or predictions about large repositories. Prefix caches and shared workers were
not flushed; report cached and uncached input separately. Latency includes CLI/MCP
startup. Total input includes cached input; output is reported separately.

### Reproduce without changing a daily profile

Generate the task plan first; this makes zero model calls:

```powershell
python scripts\benchmark_codex_e2e.py --output coding-plan.json
```

Use the installed Headroom Python and an explicit compatible native Codex executable
for a budgeted run. These arguments refer to your chosen installation/executable;
do not paste placeholder paths literally:

```powershell
python scripts\benchmark_codex_e2e.py --run --installed PATH --codex PATH_TO_NATIVE_EXE --model gpt-6.1-sol --token-budget 1500000 --max-pairs 1 --output coding-result.json
python scripts\benchmark_codex_e2e.py --run --resume --installed PATH --codex PATH_TO_NATIVE_EXE --model gpt-6.1-sol --token-budget 1500000 --max-pairs 5 --output coding-result.json
python scripts\publish_codex_e2e.py coding-result.json coding-result.md --manifest-name coding-result.manifest.json
```

Default execution uses `workspace-write`. The measured Windows run explicitly used
`--sandbox danger-full-access` in **both** arms because this CLI's unelevated
restricted-token sandbox refused the temporary split write roots. Full access
does not provide OS isolation: use it only for reviewed synthetic fixtures on a
trusted host. It is opt-in, never enabled in daily configuration by the runner.
VM testing remains paused. No laptop restart is required for these scripts.

The runner copies an existing native ChatGPT login into a temporary OS profile,
removes it after each call, checks the original auth/config are unchanged, and
uses fresh ephemeral chats and separate identical Git fixtures. Native has no
bundle MCP/proxy/hook. Treatment adds the three production MCP gateways and
documented tool guidance. Plugins, connected apps and subagents are off in both.
Enabled host tools are required; the runner never turns them on automatically.
Local bundle calls are tagged diagnostic; shared runtime aggregates can still
change. Temporary directories are not a VM or an authentication security boundary.

The seed fixes randomized arm order. The manifest freezes prompts, fixture hashes,
expected answers, schemas and the hidden oracle hash. The grader is programmatic
and identical across arms. Each row records input/cached/output usage, wall time,
tool calls, command failures and quality. Missing usage is not fabricated. Resume
refuses changed runner, fixtures, model, CLI or bundle metadata; completed rows
are not repeated. Exit 1 for a complete study with failed checks is expected and
does not mean its measurements should be discarded. Raw output/credentials and
tool arguments are not published. Internal provider retries are not measured.

The token stop threshold is checked **between** tasks, including cached input;
it cannot cap one task or measure account quota. Model calls are opt-in and are
never run in CI; CI only checks fixtures, grading, privacy and report consistency.

### Diagnostic pilots and interpretation

The older CLI 0.117.0 context pilot above remains a failed, unclassified attempt.
With the current desktop CLI, five further validation invocations preceded the
ten measured invocations. Their [sanitized accounting](benchmarks/coding-pilots.json)
is separate: they consumed 238,515 reported input and 650 output tokens, including
the failed native sandbox checks. They are not hidden retries or savings samples.
No global authentication, routing or CLI installation was changed.

This study supports improving selective tool exposure/startup costs before
claiming general efficiency. A broader preregistered study should use larger
repositories, an explicit semantic grading rubric, browser tasks and separately
controlled automatic compression/hooks. Keep those results distinct from this
small configuration and from offline per-tool avoided-token estimates.

Account weekly percentages are coarse, shared across chats and affected by
caching/model policy. They are not a reliable per-task token meter. Do not convert
local avoided-token estimates to a claimed weekly quota reduction. Do not count
the same output at the RTK, local Headroom and request-proxy layers more than once.
Only publish non-private fixtures and redacted aggregate results. Paid model runs
require a separately agreed test budget; none are performed by the offline test.
