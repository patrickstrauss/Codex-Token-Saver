# Laya-first bundle entry tool

The **Bundle tool router** is the central gateway for explicit Token Saver work. Prefer `bundle_laya_router.bundle_query`: the local Laya classifier chooses a validated tool recipe and delivery sequence from a natural-language intent. A structural `pattern` + `language` selects ast-grep inside Laya's validation/toggle boundary, avoiding classifier loading and inference. Existing typed bundle MCP and CLI entry points use the same gateway. Typed routing reports `routing_probability: null`. Codex model/provider settings and non-bundle tools are unchanged. Automatic RTK hooks and Headroom request compression retain their fast paths.

Turn Laya On before requesting explicit bundle operations. An unknown operation, disabled component, or uncertain natural-language decision stops before execution. Exact original-content retrieval remains available through a clearly reported recovery route. Help/version and service-control operations do not count as task work. Do not invoke internal runtime paths to bypass the gateway.

After this gateway upgrade, restart Codex once when active work is finished so existing MCP processes load the new adapters. Refresh the dashboard to see **Recent activity**, its task/diagnostic/informational filters, and automatic hook coverage. New records contain only component, outcome, category, timestamp and a validated task UUID when supplied; existing mixed counters are not backfilled. A routing decision and the resulting component operation are separate records, not two model requests. No laptop restart is required.

Enable the card after the full installer validates its runtime and model. Reload MCP tools or restart Codex to discover `bundle_query`. No laptop reboot is needed. Fresh installations leave the new optional components Off. Turning the router Off prevents further work even through an already-loaded MCP connection; the local classifier exits when disabled or after five idle minutes.

After upgrading, restart Codex when the current task can pause: existing MCP processes must load the gateway code. The installer does not stop or edit running conversations. Supply `caller_task_id` only when the calling chat UUID is known; it is separate from `task_id`, which selects a summary target. Missing attribution stays unknown.

## Call contract

```json
{
  "intent": "Search JavaScript for syntax matching console.log($A)",
  "project": "C:\\Projects\\Example",
  "path": "src",
  "pattern": "console.log($A)",
  "language": "javascript",
  "max_matches": 50,
  "exact": true
}
```

Every call provides an absolute project and a short intent. Supply relevant fields; the classifier cannot invent a path, AST pattern, session or task ID. Optional `exact: true` prevents lossy output compression and overrides the classifier's delivery suggestion. Structural results always preserve exact matched text, even without that flag, but contain only the requested page. RTK reports still use RTK's own filtering, and summaries remain summaries; use exact source/retrieval tools for complete originals.

Prefer ast-grep for call shapes, nested expressions and repeated code structure. JavaScript `ipcMain.handle($$$ARGS)` finds handler registrations; Python `subprocess.run($$$ARGS)` finds subprocess calls. These exclude matching text in comments/strings. Use rg for literal text and Serena for named definitions/references. Do not duplicate searches to increase a usage counter. Select a narrow project-relative path and the source language; combining structural search with symbol/Git/browser/summary fields is rejected with guidance to split requests.

Structural `result` is JSON with `matches`, `total_matches`, `returned_matches`, `offset`, `next_offset` and `truncated`. Matches contain project-relative `file`, 1-based `line`/`column`/`end_line`/`end_column` (end exclusive) and unchanged `text`. Redundant captures/context are omitted. Pages default to 50 matches (maximum 200); repeat the query with `offset: next_offset` for more. Results are sorted by path and position; paging reruns the search, so edits can shift matches. These compact pages skip a second Headroom pass. The existing 2 MiB raw-output limit still asks callers to narrow oversized searches.

| Required inputs and selected recipe | Executed sequence |
| --- | --- |
| Existing project-relative file | Laya → Headroom file read |
| Symbol/name path or a source file | Laya → Serena project activation → symbol lookup/overview |
| Structural pattern, language, and existing path | Laya typed route → ast-grep → bounded exact match page |
| `git_operation`: status, diff, or log | Laya → RTK Git report → optional Headroom output check |
| Existing `browser_session` | Laya → Playwright CLI snapshot → optional Headroom output check |
| Local `task_id`, `summary_action: read` | Laya → saved LangMem summary |
| Local `task_id`, explicitly requested `summary_action: start` | Laya → LangMem → llama.cpp job |

Git reports are bounded to short status, diff statistics or the last ten commits. The facade exposes no arbitrary shell execution, browser navigation/evaluation, AST rewriting or source edits. Use the directly authorized tools for those operations. A browser snapshot requires a session created/attached separately. Summary jobs require both summary and model toggles On and an explicit user request; the router does not enable them.

## Decision and execution boundaries

For requests without explicit structural arguments, Laya classifies the bounded intent using a stable seven-category menu and a separate exact/compact choice in one inference call. The bundle then checks the route against enabled components, existing project-contained paths and supplied arguments. It rejects unknown routes, truncated model inputs, missing parameters, unavailable tools and probabilities below **0.80**. No fallback tool runs behind the caller's back: an uncertain request returns a message to narrow it or use a direct tool. Component choices are checked again immediately before execution.

Run `scripts/verify_structural_search.py BUNDLE_ROOT` with the bundle Headroom Python to check installed MCP routing, JavaScript/Python matching, pagination, exact text, empty results and output size. It uses disposable files, records diagnostics separately, and never changes component toggles. `--source CANDIDATE_CHECKOUT` checks candidate Python code against the installed runtimes before deployment.

The category probability is not a guarantee of correctness or a calibrated safety score. Tool results remain authoritative and require review. The dashboard records completed/failed/blocked calls, the last sequence and routing time; it does not store intents, source, URLs or command arguments in routing metrics and does not claim quota/token savings.

One authenticated loopback worker at `127.0.0.1:8791` serves all bundle entry processes. It uses two CPU threads and a single loaded model, loads on the first request, processes requests serially and releases memory when idle. A busy/unavailable classifier returns an error for natural-language requests; validated typed routes remain available through the central gateway while Laya is On. No conversation history or provider credentials are sent to Laya. The MCP wrapper remains lightweight; it does not import Torch.

## Pinned runtime and evidence

The bundle pins Laya **0.3.22**, all Python dependencies with hashes, and `convaiinnovations/laya-multilingual` revision **e4e9ddf21a7b1903b7acffd8814ad4307bf63a67**, including individual artifact SHA-256 hashes. Runtime inference is offline. Upstream normalizes tokenizer configuration in place, so the bundle keeps verified downloads intact and loads a separate working copy. These pins update with a qualified bundle release, not the existing Library updates menu.

September 30, 2026 local smoke corpus: **6 correct accepted routes, 2 blocked decisions, 0 incorrect accepted routes out of 8**. Median warm classification was **442 ms** and loading about **7.3 seconds** on this 32 GB Windows laptop. The two blocked examples concerned a function definition and a saved task summary. This is a small development regression corpus, not proof of general routing accuracy. Changing the classifier's choice menu degraded this corpus, so the deployed menu stays fixed and host validation applies eligibility afterwards. Do not infer production savings from these checks.

Reproduce classifier checks with `scripts/qualify_laya.py BUNDLE_ROOT` under the Laya interpreter. `scripts/smoke_bundle_router.py TEST_CHECKOUT` exercises real stdio MCP, Laya's typed structural route, ast-grep, and Off enforcement. The latter temporarily changes the test checkout's component preferences; do not use it to benchmark active user work.

October 1, 2026 structural-search qualification: 85 focused checks passed, followed by five real MCP searches covering JavaScript/Python, exact text, comments/strings, pagination and no matches. For the same 65 fixture matches, native ast-grep JSON was 58,056 bytes and the compact page 10,419 bytes (**82.1% smaller**); the first typed MCP search took 130 ms and required no classifier inference. These are fixture output/latency measurements, not measured quota savings or proof of automatic adoption by existing chats. Reload MCP tools or restart Codex after deployment so loaded servers and task guidance receive the changes.

## Video and source assessment

The supplied [Sam Witteveen video](https://www.youtube.com/watch?v=zaLQ0AnY9dI) is titled **Using Jev In Your Agent Harness**. Its published chapter list covers model routing, tool/skill selection and progressive disclosure. This review obtained metadata/chapter information, not a usable transcript; it does not assert unverified demonstrations or savings figures from the video.

[Laya's Router](https://github.com/NandhaKishorM/laya/blob/v0.3.22/laya/router.py) selects Laya checkpoints. The bundle implements its own validated dispatcher using [typed choice decisions](https://github.com/NandhaKishorM/laya/blob/v0.3.22/laya/agent.py). Laya is a local classifier, not a replacement for Codex's agent loop. Its [package metadata](https://github.com/NandhaKishorM/laya/blob/v0.3.22/pyproject.toml) supplies the dependency/license basis; the [model repository](https://huggingface.co/convaiinnovations/laya-multilingual/tree/e4e9ddf21a7b1903b7acffd8814ad4307bf63a67) supplies pinned weights.
