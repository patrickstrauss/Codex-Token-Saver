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
JSON and inventory when evaluating that candidate. No measured end-to-end Codex
quota or answer-quality claim is currently made.

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

## Native Codex A/B study (not yet measured)

Use identical clean repository snapshots, task prompts, native model/version,
reasoning effort, network policy and success criteria. Run at least five paired
tasks in randomized order, each in a fresh chat with no cross-run memory. Baseline
uses native Codex without bundle tools/hooks/proxy; treatment enables a documented
bundle configuration. Never reuse provider-owned encrypted compaction across
routes. Use isolated profiles/worktrees rather than altering a daily profile.

Keep a preregistered task list: find a symbol/reference, locate a structural call,
diagnose a long log, edit code and pass repository tests, and inspect a browser
flow. Grade artifacts/tests against the same rubric, preferably blind to arm.
Record model-reported input, cached-input and output usage when available, wall
time, completion/failure, retries, tool calls and hardware/versions. State missing
usage explicitly. Report paired results and variability, not just a best example.

Account weekly percentages are coarse, shared across chats and affected by
caching/model policy. They are not a reliable per-task token meter. Do not convert
local avoided-token estimates to a claimed weekly quota reduction. Do not count
the same output at the RTK, local Headroom and request-proxy layers more than once.
Only publish non-private fixtures and redacted aggregate results. Paid model runs
require a separately agreed test budget; none are performed by the offline test.
