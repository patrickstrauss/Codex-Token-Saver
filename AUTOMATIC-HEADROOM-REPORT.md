# Automatic Headroom for desktop — September 13, 2026

Automatic command compression is installed. The native RTK launcher checks eligible human-readable output in Codex without selecting a Headroom tool. The additional PreToolUse hook was reviewed and trusted by the user, and an actual command rewrite was observed in this existing desktop task. Codex retains its direct connection, model, reasoning, sandbox, and approval behavior.

## Verified behavior

- The root regression suite passed **135 tests**, including an actual native launcher → real Python worker → offline Headroom → cache/database integration check. Final optional-hook safeguards were then checked separately.
- The dashboard regression suite passed **114 tests**; 19 relevant checks also passed after the final banner wording update.
- A real RTK search in this desktop task automatically produced a command-check record: 1,207 stdout bytes, exit 0, unchanged because the output was small. After the user trusted the hook, another supported command was automatically rewritten and completed normally. These are real installed-path observations.
- An isolated successful-output fixture measured 5,606 original tokens and 1,841 returned tokens. After exact targeted retrieval, its estimated net reduction was **3,703 tokens**. The critical record remained present and the stored original was byte-exact. Fixture savings are excluded from the real dashboard.
- Commands execute once. Missing, broken, or timed-out optional compression returns original output. Failed commands preserve their output and exit code. Native RTK executes before its optional compressor, so a broken Python installation cannot stop RTK from running.
- Exact originals are stored locally for 24 hours. Measurements include returned metadata and subsequent retrieval costs. Bookkeeping happens after output delivery; a bookkeeping failure can undercount but cannot justify claiming undelivered reductions.

## Coverage and limits

Automatic RTK checks cover selected searches, Git summaries, and supported test/build output. The extra hook covers supported simple PowerShell calls with explicit Windows executable paths. Complex scripts, pipelines, ambiguous bare commands, machine output, patch/exact modes, interactive output, failed commands, small output, and long/oversized streams pass unchanged. Ordinary chat and browser tools are outside this coverage. Use `HEADROOM_EXACT=1` when exact RTK output is required.

The dashboard distinguishes checked commands, skipped output, hook observations, and measured reduction. A zero token counter can coexist with successful automatic checks when output is small or already compact. Command measurements precede Codex's own truncation; they are stdout reduction estimates, not verified account quota, billing, or model-context savings. Headroom's RTK baseline is RTK's emitted output, so it does not claim RTK's own earlier reduction.

## Why this design

The installed Codex engine's PostToolUse feedback retains raw typed results inside JavaScript tool execution, so using that mechanism would not reliably reduce desktop output. The implementation instead filters the actual command output before Codex receives it. The extra hook rewrites only the pending command and never executes it outside the normal command tool. See [official hooks documentation](https://learn.chatgpt.com/docs/hooks) and the [installed-version implementation](https://github.com/openai/codex/blob/b5bffd3ec4db487e7e3dec59663875b0ef7b72ca/codex-rs/core/src/tools/registry.rs#L220).

## Records and recovery

- `automatic-verification.json`: installed-state observations and unchanged settings, apart from the user's hook trust record.
- `logs/automatic-all-unit-tests.log`, `logs/automatic-final-hook-tests.log`, and `logs/automatic-command-fixture-result.json`: verification evidence.
- `automatic-headroom.json`: original hook registration receipt. Trust was granted through Codex by the user, not by the installer.
- `backups/automatic-rtk-20260913-reconstructed/`: clearly labeled reconstructed prior native launcher for rollback; the underlying `tools/rtk.exe` was never modified.

Existing tasks work; a new task or Codex restart is unnecessary for this update. Dashboard/tray were restarted independently. A full laptop reboot remains untested. Do not enable global Headroom proxy routing.
