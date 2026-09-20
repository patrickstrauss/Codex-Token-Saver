# Automatic desktop Headroom

User intent: general desktop coding work should use Headroom without the model selecting a special file tool, while Codex retains its direct connection and selected model/reasoning.

The installed engine is 0.154.0-alpha.6.2. Its PostToolUse feedback preserves raw typed values in JavaScript tool execution; it cannot honestly provide transparent output compression. The outer custom code tool is not hookable. See the official hook documentation and exact source commit `b5bffd3ec4db487e7e3dec59663875b0ef7b72ca`.

Implementation:

1. Native RTK executes once and optionally filters eligible successful stdout after execution. Missing/broken/stalled optional compression returns raw bytes. Preserve arguments, exit codes, stdin, stderr, and non-Codex behavior. Prevent double filtering.
2. Optional PreToolUse hook rewrites only safely understood explicit Windows PowerShell native-executable calls through a native Headroom runner. The hook never executes the command. Keep existing sandbox/approval checks. Complex or ambiguous syntax passes unchanged.
3. Local offline Headroom compression must be beneficial after metadata; retain exact originals for 24 hours. Record delivered estimates separately from checked/skipped command activity. Synthetic tests use isolated state.
4. Dashboard/tray display command and file measurements; distinguish configuration, hook observations, skipped output, and actual estimated reduction. Counts do not establish account savings or post-truncation context reduction.
5. Install the exact optional hook, preserving all unrelated config and existing hooks. Leave trust review to the user in Settings → Hooks. Do not bypass trust or configure any network proxy.

Acceptance: native argument/stream/exit tests; failure/no-replay/timeout tests; actual SDK compression plus exact retrieval; hook AST safety tests; existing regression suites; live RTK activity from this desktop task; dashboard verification. Automatic extra-command hook remains pending user Trust until explicitly completed.
