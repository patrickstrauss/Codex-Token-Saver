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

### Overall effectiveness with automatic paths enabled

The [combined effectiveness report](benchmarks/effectiveness-windows.md) is the
primary end-to-end result. Two repetitions of five frozen synthetic tasks produced
10 paired attempts, not ten independent workloads. Native and bundle each passed
all 10 attempts, including the independent hidden code-fix oracle.

The bundle used **71.10% more input**, **25.86% more uncached input**, **70.86% more
input plus output**, and **26.21% more uncached input plus output**. Runtime was
74.30% longer. The current configuration fails its token-reduction objective on
this workload. No account quota or billing reduction was measured.

Both full runs use the same tasks, prompts, source hashes, model, reasoning and
permissions. Only the randomized arm-order seed changes. Every attempt is included;
there are no manual retries within either frozen study. See
[run 1 and its chart](benchmarks/overall-windows.md),
[run 2 and its chart](benchmarks/overall-repeat-windows.md), and the linked raw JSON
and manifests. The aggregator verifies compatible manifests/source metadata,
rejects duplicate study seeds and recomputes totals from every attempt.

Treatment enables the three explicit MCP gateways, automatic Headroom request
compression and the exact reviewed production command hook. Each bundle run uses
a separate temporary production relay on loopback and the already-running warm
Headroom backend. Own relay counters and hook events are attributed to benchmark
chats; the shared dashboard savings ledger is not used for net token calculations.
A routed connection does not prove positive compression. Relay failure counters
can include abrupt client WebSocket shutdown; they do not prove failed model
tasks or network retries. No component-level cause of overhead is established.

The full-study symbol prompt explicitly specifies unqualified function names and
a project-relative forward-slash path before freezing either run. This resolves
an exact-output ambiguity in the earlier pilot. That pilot uses different prompts
and configuration and is therefore excluded from the aggregate.

### Earlier explicit-tool pilot

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
the complete configuration showed overhead. These data do not isolate whether
registration, startup, tool choice or another component caused it.

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
python scripts\benchmark_codex_e2e.py --configuration full --output coding-plan.json
```

Use the installed Headroom Python and an explicit compatible native Codex executable
for a budgeted run. These arguments refer to your chosen installation/executable;
do not paste placeholder paths literally:

```powershell
python scripts\benchmark_codex_e2e.py --run --configuration full --seed 20261019 --installed PATH --codex PATH_TO_NATIVE_EXE --model gpt-6.1-sol --token-budget 1500000 --max-pairs 1 --output coding-result.json
python scripts\benchmark_codex_e2e.py --run --resume --configuration full --seed 20261019 --installed PATH --codex PATH_TO_NATIVE_EXE --model gpt-6.1-sol --token-budget 1500000 --max-pairs 5 --output coding-result.json
python scripts\publish_codex_e2e.py coding-result.json coding-result.md --manifest-name coding-result.manifest.json --chart-name coding-result.png
.\scripts\Plot-CodexBenchmark.ps1 -InputJson coding-result.json -OutputPng coding-result.png
```

Use seed `20261020` and a separate output filename for the second repetition.
Do not retry completed attempts or edit tasks after seeing results. Combine only
compatible full runs with `scripts/summarize_codex_effectiveness.py`:

```powershell
python scripts\summarize_codex_effectiveness.py docs\benchmarks\overall-windows.json docs\benchmarks\overall-repeat-windows.json --output docs\benchmarks\effectiveness-windows.json --markdown docs\benchmarks\effectiveness-windows.md
```

Charts use Windows/.NET built-in charting; no plotting package is installed.
`--configuration explicit` remains available for new explicit-only experiments.
The historical pilot's exact runner is preserved in commit `85630e5`; later runner
changes add full-stack support and the prompt clarification. Source hashes in
each report identify its actual runner, fixtures and installed components.

Default execution uses `workspace-write`. The measured Windows run explicitly used
`--sandbox danger-full-access` in **both** arms because this CLI's unelevated
restricted-token sandbox refused the temporary split write roots. Full access
does not provide OS isolation: use it only for reviewed synthetic fixtures on a
trusted host. It is opt-in, never enabled in daily configuration by the runner.
VM testing remains paused. No laptop restart is required for these scripts.

The runner copies an existing native ChatGPT login into a temporary OS profile,
removes it after each call, checks the original auth/config are unchanged, and
uses fresh ephemeral chats and separate identical Git fixtures. Native has no
bundle MCP/proxy/hook. Full treatment adds the production MCP gateways, documented
guidance, temporary relay and reviewed hook. Only that exact hook bypasses trust
in temporary CLI profiles; daily hook trust is unchanged. Plugins, connected apps
and subagents are off in both.
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
ten explicit-tool invocations and twenty full-configuration invocations. Their
[sanitized accounting](benchmarks/coding-pilots.json)
is separate: they consumed 238,515 reported input and 650 output tokens, including
the failed native sandbox checks. They are not hidden retries or savings samples.
No global authentication, routing or CLI installation was changed.

This study supports improving selective tool exposure/startup costs before
claiming general efficiency. A broader preregistered study should use larger
repositories, a semantic grading rubric, browser tasks and component ablations
that isolate lean tool exposure and automatic-only configurations. No additional
live model calls are required to regenerate the published aggregate or charts.
Keep future results distinct from this small repeated workload and offline
per-tool avoided-token estimates.

Account weekly percentages are coarse, shared across chats and affected by
caching/model policy. They are not a reliable per-task token meter. Do not convert
local avoided-token estimates to a claimed weekly quota reduction. Do not count
the same output at the RTK, local Headroom and request-proxy layers more than once.
Only publish non-private fixtures and redacted aggregate results. Paid model runs
require a separately agreed test budget; none are performed by the offline test.
