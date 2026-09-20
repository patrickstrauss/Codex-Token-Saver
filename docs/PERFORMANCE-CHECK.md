# Check compression quality and overhead

Run this from a source checkout with an existing Windows bundle installation:

```powershell
& "$env:USERPROFILE\CodexTokenSaver\headroom\.venv\Scripts\python.exe" scripts/benchmark_modules.py --installed "$env:USERPROFILE\CodexTokenSaver" --repeats 3
```

The report is written to `logs/performance-benchmark.json`; use `--output` to retain separate runs. The command takes a few seconds, uses installed dependencies, makes no Codex/model calls, and changes no dashboard settings or routing. Temporary Headroom stores, signing keys and RTK history are separate from the app's live records. Test fixtures are synthetic and modest in size.

The benchmark runs the **source checkout's Headroom file adapter** against the installed Headroom library and tokenizer. It compares native reads with compressed JSON/log overviews, requires the declared error facts to remain visible, and retrieves the exact original, including CRLF line endings. The fixture shapes reuse the existing offline SDK acceptance tests. A native read is the reference; overview generation includes local adapter/header/storage costs.

RTK is exercised directly through the installed `tools/rtk.exe`, using a temporary Git repository and private history database. Both old and new configuration values must survive `git diff` filtering. A native re-read must still return the same original diff. This does **not** measure the native launcher, command hook or subsequent Headroom filtering. Short diffs can have no savings while still adding process overhead; that is a valid result.

Each case reports paired latency medians. Headroom gets one initial call before the repeated measurements; the first fixture's `first_call_ms` includes imports and tokenizer setup, while subsequent fixtures share the warm process. Full-original retrieval has its own latency and token cost. `estimated_tokens_avoided_after_full_retrieval` can be negative: always retrieving the complete original after its overview spends more tokens than reading it once. Use targeted ranges when exact detail is needed.

Exit code 0 means all fact/recovery gates passed and both Headroom fixtures compressed. Missing required RTK/Git, changed originals or missing critical facts prevent a successful result. Lower latency or higher compression is never allowed to override these gates.

The Windows package workflow runs this same benchmark against its fresh installation before uploading the deployment artifact. A failed gate stops publication; the workflow log contains the report. Latency is reported without a fixed timing threshold because CI machine load varies.

This is a **regression check**, not proof of unchanged LLM answer quality, actual Codex quota reduction or representative production savings. It does not exercise the request proxy, Serena's language servers, or disabled local summaries. Keep those distinctions when sharing results.

## Optional matched-task comparison

The dashboard's recent request windows use Headroom 0.37's savings ledger, which records only positive-savings events. Their event counts and reduction percentages exclude zero-savings requests and expansions; they are not an overall traffic reduction rate or net Codex consumption. Complete ledger coverage means all available records were readable, not that every model request was measured. Lifetime request counters use a separate cumulative source. Never compare these denominators as if they were the same.

Do this only when you choose to spend Codex usage on a quality comparison. The benchmark above never starts these tasks automatically.

1. Choose a small, representative bug fix or navigation task with a known answer and executable acceptance checks. Prepare two clean disposable checkouts of the same commit. Keep the prompt, model, reasoning level and available tools identical.
2. Record the current bundle settings. Use the dashboard's existing module controls for the comparison. For an already validated managed request connection, use its **Pause request compression** and **Enable request compression** controls. Never hand-edit global routing or copy validation receipts; fresh team installations should leave unavailable request compression off.
3. Run one new task with the relevant module disabled and another with it enabled. New tasks avoid history differences and stale tool availability. Follow an explicit tool-reload prompt before testing if a configuration change requires it. Do not toggle modules while either task is running.
4. Check the final patch/answer against the same acceptance tests and original sources. Record missed requirements, invented facts, incorrect edits, fallback/retrieval errors, elapsed time, task-reported token usage (when exposed), and the bundle counter deltas. Do not add request, RTK and local-output savings together: they can overlap. If other tasks run concurrently, global counters cannot be attributed to this pair.
5. Repeat at least three matched pairs, alternating which mode runs first, then compare medians and all quality failures. A single pair is noisy. Cache state, inference variability and task differences limit causal claims even with this procedure. Estimated tokens avoided are not quota percentages; record actual task usage separately when available.
6. Restore the recorded settings through the dashboard. Keep the enabled mode only if the same correctness checks pass and latency/usage results support it. If one mode changes the solution or fails an acceptance check, investigate that case before increasing compression.

For Serena, use a symbol-navigation task with known definitions/references and validate the returned source locations. Compare with native search in its matched task; check that fallback results preserve the same information. Test modules individually before assessing the combined bundle, so a regression has an identifiable source.
