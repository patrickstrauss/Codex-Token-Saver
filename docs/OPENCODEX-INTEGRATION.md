# Install the OpenCodex integration candidate

The combined folder contains both built applications, checked upgrade scripts and
source patches. This is a local candidate based on OpenCodex 2.64.0, not an official
OpenCodex release. Automated local checks pass; your Windows restart and live provider
acceptance remain separate checks. The steps below describe a first migration;
an installation already repaired and connected does not need to repeat them.

## Your steps

1. Save your work and fully exit Codex, OpenCodex (including its proxy), and the Token
   Saver tray. Keep this folder. Right-click **Upgrade.cmd → Run as administrator**
   under the same Windows account. The script backs up changed source files, checks
   hashes, upgrades both apps and verifies the existing full-bundle runtimes.
2. Close the administrator window. Double-click **Connect.cmd normally** while Codex
   remains closed. It restores Token Saver's owned native route, starts the patched
   OpenCodex, verifies your selected settings, and requests the transform worker.
   `phase: warming` is expected while an old native worker remains.
3. **Restart your laptop once**, after Connect succeeds. This clears the old workers
   and loads the installed code. If you still need exact originals from recent native
   tool output, allow their 30-minute retention window to expire before restarting.
4. Open OpenCodex first, then **Codex Token Saver** from the Start menu if its tray
   icon is absent. Run **Check.cmd normally**; it must show
   `effective_enabled: true`. If it reports that OpenCodex is unavailable, fully close
   Codex and run Connect.cmd again. Allow up to a minute for pending activation.
   Then reopen Codex and use your existing chats and chosen models.

There is no need to restart before installing. The scripts never restart the laptop
or kill processes automatically. If a step fails, stop there and retain its output.
Do not manually copy executables, change provider URLs, or run the ordinary Install.cmd
over your current installation.

## Dashboard measurements

In OpenCodex mode the headline uses the worker's durable token-only ledger at
`proxy/transform-state/savings_events.jsonl`. Measurements start when live metering
is installed; earlier savings cannot be reconstructed. Native-proxy history stays
separate and does not populate this headline.

Each successful transform reply records estimated input and output tokens after
sending its response. Cached, unchanged, bypassed and diagnostic replies are included.
The first effectiveness rate uses submitted tool text in the selected window.
Whole-request effectiveness remains **Not reported**: protected conversation content
is not measured. Worker responses are not proof of provider acceptance or quota savings.
The ledger contains only a timestamp, token counts and outcome; measurement failures
cannot fail compression. Bounded reads disclose partial ledger coverage.
Worker outcome counts reset on restart, exclude cache hits, and include diagnostic checks.

RTK's totals cover commands actually routed through RTK. Small output, exact-output
options, complex shell scripts and ambiguous commands can produce no savings or bypass
filtering. A ready runtime does not imply every tool call is compressed.

## What stays yours

OpenCodex owns routing, credentials, catalog, voice and subagents. Token Saver owns the
local transform service, durable original retrieval, and its extension receipt.
RTK, file reads, Serena, and local summarization remain independent bundle features.
The upgrader replaces only listed source files and preserves runtime environments,
downloaded models, settings, credentials and history. It refuses running app binaries,
linked destinations, changed payloads, and concurrent source edits.

The handoff checks the root and profile model, provider, reasoning, approval and sandbox
settings and the credential-file hash. Unexpected changes stop activation and are
preserved for inspection. OpenCodex performs its ordinary owned client integration;
Token Saver does not install another global provider route. Custom homes must be
available in the environment of Connect.cmd, as in your normal OpenCodex launch.

## Acceptance after restart

Check.cmd verifies the saved settings and effective compression state. In Codex, make
one normal request with your selected provider, then one tool-heavy request and confirm
the bundle dashboard's request counters move. Test your usual Azure/LM Studio routes
if you use them. Enable/Pause should work without restarting OpenCodex. Exact retrieval
must still work after Pause. Native steering/injection and unsupported structured
results bypass compression. Plain text function and custom-tool results are eligible,
including arrays containing only unannotated input_text blocks. Savings estimates are not provider billing measurements.

The automated witness covers real local HTTP/SSE, WebSocket delta turns, full replay
after reconnect, simultaneous chats, and live pause/resume on an existing socket.
It does not replace this machine's reboot or real-provider acceptance.

## Recovery

Before Connect has ever run, **Rollback.cmd as administrator** restores the checked
source backup. Automatic rollback also runs if an upgrade write or runtime check fails.
External edits are never overwritten during rollback. Backups and journals are under
`%USERPROFILE%\CodexTokenSaver\upgrade-backups`.

After the connection handoff, use the bundle **Pause** control first. Pause works even
when OpenCodex is offline and keeps retrieval available. **Disconnect** removes only
the extension owned by this bundle while preserving OpenCodex routing. Run it with:

    "%USERPROFILE%\CodexTokenSaver\headroom\.venv\Scripts\python.exe" "%USERPROFILE%\CodexTokenSaver\opencodex_control.py" disconnect

Source rollback deliberately refuses once routing migration has started: an old bundle
must not be restored over active OpenCodex mode or unexpired originals. Returning to
native routing requires a separate checked handoff through OpenCodex's Restore controls;
automatic reverse migration is not qualified in this candidate. Full-bundle Disable
remains separate from ordinary Pause and requires a Windows restart.

An ordinary OpenCodex update can replace this patched binary. Keep this candidate and
its backup until the extension is ported to that release; capability checks refuse
unsupported versions instead of redirecting your requests silently.
