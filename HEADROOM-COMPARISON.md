# Headroom desktop comparison — September 13, 2026

This report records the earlier local-output integration. The subsequent [desktop request compression feature](DESKTOP-REQUEST-PROXY.md) adds the broader request path requested by the user, with explicit enable/pause controls and separate measurements. The audit findings below remain a record of the previous setup.

The earlier app had broader compression coverage. This bundle uses the same underlying Headroom library, but it sees selected file reads and command outputs rather than complete model requests. The difference is architectural, with different dashboard measurements as well.

## Documentation and wiring recheck

The user's linked [installation guide](https://extraheadroom.com/install-headroom-claude-code) and [desktop repository](https://github.com/gglucass/headroom-desktop#proxy-topology) confirm that the desktop product routes both Codex desktop and CLI requests through its proxy. Our local-output adapter is not an equivalent installation of that product.

The [desktop pipeline configuration](https://github.com/gglucass/headroom-desktop/blob/7379fbf5d371d382eee9e58e9c1707cbfba6aded/src-tauri/src/tool_manager.rs#L4256-L4429) pins Headroom 0.37.0, also installed here, and enables a coding profile, Kompress, deduplication and request-history features. Its output shaping can adjust verbosity and supplied reasoning effort. Our adapter disables Kompress and preserves the selected Codex reasoning settings. The SDK does not automatically inherit the proxy's [coding profile](https://github.com/headroomlabs-ai/headroom/blob/v0.37.0/headroom/agent_savings.py#L143-L179).

The installed SDK accepts and applies our call arguments. Missing user context changes relevance selection, not activation. Structured transforms remain enabled; plain text can pass through when Kompress is unavailable. Existing isolated SDK verification shows real compression and exact recovery. Thus the calls work, but the narrower coverage and configuration do not establish parity with the desktop product. Enabling ML needs separate latency/recovery validation; matching request-wide behavior requires revisiting the current no-global-proxy requirement.

The live recheck found 32 output checks: 3 compressed, 21 too small, 5 without further reduction and 3 failed commands, with 11,075 net estimated tokens saved. The dashboard now shows the last check time and outcome separately from savings. All 151 dashboard tests passed; live browser verification and unchanged configuration hashes are recorded in `logs/headroom-activity-diagnosis-20260913.json`.

## What was identified

The remaining `AppData\Local\com.extraheadroom.headroom` folder identifies the [Extra Headroom desktop product](https://github.com/gglucass/headroom-desktop). Bounded checks found no installed executable, uninstall registration, process, or recoverable savings history. Its exact previous version and settings are unknown. Browser storage and credentials were not inspected. This is not a matched benchmark of the user's previous installation.

The current upstream desktop source describes a Rust proxy on port 6767 in front of a managed Python Headroom runtime on 6768. Its Codex adapter sets provider routing and retags existing tasks. That exposes accumulated request context to compression. This bundle keeps Codex's direct connection and performs offline tool-output compression. Recreating the desktop app's full-request behavior would require the global routing expressly excluded from this installation after the earlier outage.

The current SDK path here disables Kompress model inference and receives one tool result at a time. It can reduce structured output, but cannot perform request-wide history deduplication or optimize full tool schemas. It also runs after RTK, so RTK's reductions are excluded from Headroom's baseline. The selected Codex model and reasoning settings remain independent of the local tokenizer.

## Measurement differences

The [upstream measurement guide](https://extraheadroom.com/docs/how-savings-are-measured) distinguishes new-input token percentages from a fallback billable-input cost basis, excludes cache reads from those percentages, and separates estimated output shaping. Historical samples can have a different basis.

Our dashboard measures signed local content-token reduction once per delivered read or command result, including headers and deducting later retrieval output. Command measurements occur before Codex truncation. They are not account usage, a verified context-window reduction, subscription quota, or billed savings. No attempt was made to inflate totals by multiplying savings across subsequent requests.

At the audit snapshot, this bundle had **11,075 net estimated tokens saved**. Command receipts showed 22 checks: three compressed outputs saving 5,700 tokens, 17 small outputs, and two failed commands preserved unchanged. All three encountered eligible large outputs compressed successfully. The hook log snapshot showed 190 checks with only one rewrite: 176 complex-syntax skips, 12 ambiguous-shell skips, and one dynamic-input skip. Native RTK compression can run without a hook rewrite, so these counts are separate.

## Applied improvements

- Eligible standalone external commands inside multiline PowerShell scripts can now be wrapped. Source text and command order are preserved; commands whose output is consumed by assignments, pipelines, subexpressions, control flow, or redirects are excluded. The hook never executes the pending command and preserves Codex's ordinary approval and sandbox handling.
- The command admission threshold is reduced from 6 KiB / 1,500 tokens to 1 KiB / 350 tokens in both Python and the native RTK launcher. Compression still must save both bytes and tokens after recovery instructions. Failed, exact, binary, unsupported, slow, oversized, and non-beneficial output passes through.
- Exact mode is honored by the runner at execution time, including when an earlier PowerShell statement sets `HEADROOM_EXACT=1`.
- The dashboard shows checked, wrapped, and skipped hook calls, readable skip reasons, and the limited coverage scope. Unreadable logs are reported as unavailable rather than zero activity.

The hook definition and user trust are preserved. Future calls in existing tasks use the updated scripts and native launcher; a new task is unnecessary. Reloading the dashboard displays its new diagnostics. No proxy, provider, authentication, model, or reasoning changes are part of this repair.

## Validation and remaining limits

An isolated real-SDK medium JSON fixture fell from **726 to 324 tokens** including recovery instructions: **402 tokens saved**, versus zero under the old bundle threshold. The critical record remained visible and the exact original was verified from the recovery cache. A medium log fixture remained unchanged because its candidate did not save tokens. These are synthetic comparisons of this bundle's old and new admission thresholds, not comparisons against the previous desktop app. Synthetic activity is excluded from production counters.

`parity-verification.json` records 146 core tests and 119 dashboard tests passing, an actual multiline hook rewrite in this existing task, a browser layout check, and byte-identical Codex configuration and hook definition. The full-request coverage gap remains; these improvements do not establish performance parity with the proxy desktop app. A true laptop reboot remains untested.

Backups are under `backups\headroom-parity-20260913`. The audit's separate synthetic temporary folder `headroom\headroom-audit-qun7x73j` remains: automatic approval review rejected its cleanup with “blocked by policy.” It is not production savings history.
