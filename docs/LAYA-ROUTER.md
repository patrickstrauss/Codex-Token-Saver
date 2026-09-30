# Laya-first bundle entry tool

The optional **Bundle tool router** card registers `bundle_laya_router.bundle_query` in Codex. **Only calls to this entry tool** pass through Laya. It does not change Codex's model, reasoning effort, provider, tool selection, or existing direct MCP tools. RTK and Headroom hooks/request compression continue independently.

Enable the card after the full installer validates its runtime and model. Reload MCP tools or restart Codex to discover `bundle_query`. No laptop reboot is needed. Fresh installations leave the new optional components Off. Turning the router Off prevents further work even through an already-loaded MCP connection; the local classifier exits when disabled or after five idle minutes.

## Call contract

```json
{
  "intent": "Search JavaScript for syntax matching console.log($A)",
  "project": "C:\\Projects\\Example",
  "path": "src",
  "pattern": "console.log($A)",
  "language": "javascript"
}
```

Every call provides an absolute project and a short intent. Supply relevant fields; the classifier cannot invent a path, AST pattern, session or task ID. Optional `exact: true` always preserves the selected tool's output and overrides the classifier's delivery suggestion. RTK reports still use RTK's own filtering, and summaries remain summaries; use exact source/retrieval tools for complete originals.

| Required inputs and selected recipe | Executed sequence |
| --- | --- |
| Existing project-relative file | Laya → Headroom file read |
| Symbol/name path or a source file | Laya → Serena project activation → symbol lookup/overview |
| Literal pattern, language, and existing path | Laya → ast-grep → optional Headroom output check |
| `git_operation`: status, diff, or log | Laya → RTK Git report → optional Headroom output check |
| Existing `browser_session` | Laya → Playwright CLI snapshot → optional Headroom output check |
| Local `task_id`, `summary_action: read` | Laya → saved LangMem summary |
| Local `task_id`, explicitly requested `summary_action: start` | Laya → LangMem → llama.cpp job |

Git reports are bounded to short status, diff statistics or the last ten commits. The facade exposes no arbitrary shell execution, browser navigation/evaluation, AST rewriting or source edits. Use the directly authorized tools for those operations. A browser snapshot requires a session created/attached separately. Summary jobs require both summary and model toggles On and an explicit user request; the router does not enable them.

## Decision and execution boundaries

Laya classifies the bounded intent using a stable seven-category menu and a separate exact/compact choice in one inference call. The bundle then checks the route against enabled components, existing project-contained paths and supplied arguments. It rejects unknown routes, truncated model inputs, missing parameters, unavailable tools and probabilities below **0.80**. No fallback tool runs behind the caller's back: an uncertain request returns a message to narrow it or use a direct tool. Component choices are checked again immediately before execution.

The category probability is not a guarantee of correctness or a calibrated safety score. Tool results remain authoritative and require review. The dashboard records completed/failed/blocked calls, the last sequence and routing time; it does not store intents, source, URLs or command arguments in routing metrics and does not claim quota/token savings.

One authenticated loopback worker at `127.0.0.1:8791` serves all bundle entry processes. It uses two CPU threads and a single loaded model, loads on the first request, processes requests serially and releases memory when idle. A busy/unavailable worker returns an error; direct tools remain usable. No conversation history or provider credentials are sent to Laya. The MCP wrapper remains lightweight; it does not import Torch.

## Pinned runtime and evidence

The bundle pins Laya **0.3.22**, all Python dependencies with hashes, and `convaiinnovations/laya-multilingual` revision **e4e9ddf21a7b1903b7acffd8814ad4307bf63a67**, including individual artifact SHA-256 hashes. Runtime inference is offline. Upstream normalizes tokenizer configuration in place, so the bundle keeps verified downloads intact and loads a separate working copy. These pins update with a qualified bundle release, not the existing Library updates menu.

September 30, 2026 local smoke corpus: **6 correct accepted routes, 2 blocked decisions, 0 incorrect accepted routes out of 8**. Median warm classification was **442 ms** and loading about **7.3 seconds** on this 32 GB Windows laptop. The two blocked examples concerned a function definition and a saved task summary. This is a small development regression corpus, not proof of general routing accuracy. Changing the classifier's choice menu degraded this corpus, so the deployed menu stays fixed and host validation applies eligibility afterwards. Do not infer production savings from these checks.

Reproduce with `scripts/qualify_laya.py BUNDLE_ROOT` under the Laya interpreter. `scripts/smoke_bundle_router.py TEST_CHECKOUT` additionally exercises real stdio MCP, the local worker, ast-grep, and Off enforcement. The latter temporarily changes the test checkout's component preferences; do not use it to benchmark active user work.

## Video and source assessment

The supplied [Sam Witteveen video](https://www.youtube.com/watch?v=zaLQ0AnY9dI) is titled **Using Jev In Your Agent Harness**. Its published chapter list covers model routing, tool/skill selection and progressive disclosure. This review obtained metadata/chapter information, not a usable transcript; it does not assert unverified demonstrations or savings figures from the video.

[Laya's Router](https://github.com/NandhaKishorM/laya/blob/v0.3.22/laya/router.py) selects Laya checkpoints. The bundle implements its own validated dispatcher using [typed choice decisions](https://github.com/NandhaKishorM/laya/blob/v0.3.22/laya/agent.py). Laya is a local classifier, not a replacement for Codex's agent loop. Its [package metadata](https://github.com/NandhaKishorM/laya/blob/v0.3.22/pyproject.toml) supplies the dependency/license basis; the [model repository](https://huggingface.co/convaiinnovations/laya-multilingual/tree/e4e9ddf21a7b1903b7acffd8814ad4307bf63a67) supplies pinned weights.
