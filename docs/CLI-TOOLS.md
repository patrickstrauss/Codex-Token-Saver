# Browser and structural code tools

The full Windows bundle includes **Playwright CLI 0.1.22** and **ast-grep 0.45.3**, with an owned **Node 24.21.0 LTS** runtime. Core-only installation omits their runtimes. The Node download is SHA-256 pinned; every npm dependency has a SHA-512 integrity entry in `packaging/package-lock.json`. Installation runs no npm lifecycle scripts and changes no global Node installation or PATH. These pins, including Playwright CLI's upstream alpha Playwright dependency, update with a tested bundle release.

Enable **Browser automation** or **Structural code search** under **Your toolkit**. The controls add/remove their own guidance in Codex's user AGENTS.md, preserve other instructions, and block new wrapper invocations immediately when Off. Reload/open a new Codex chat to pick up changed guidance. Existing browser sessions remain owned by their caller: detach an external app or close your own session before switching Off. Full bundle disable also removes this guidance.

The cards display installed versions and recorded wrapper activity. New help/version calls are informational and do not advance operational use. Explicit operations pass through the Laya gateway; automatic RTK hook calls remain fast. New task activity separates operations, diagnostics, informational calls, and unknown callers. Older aggregate counters remain mixed historical records and are not backfilled. No command arguments, URLs, source, or browser content enter this ledger; underlying tools can still write their normal project artifacts. No token savings are inferred from activity counts. Do not invoke internal runtime paths to bypass the gateway.

Before `attach --cdp`, the wrapper checks whether the supplied endpoint accepts a connection. A successful check is not proof that the endpoint serves CDP; the CLI performs the actual attach. Failed browser commands retain their exit code and original output, while the dashboard receives only a fixed category such as unavailable connection, ambiguous selector, or timeout. Refresh the endpoint after restarting an Electron fixture; narrow selectors that match multiple elements. Failed browser actions are never retried automatically.

## Playwright CLI

```powershell
& "$env:USERPROFILE\CodexTokenSaver\bin\playwright-cli.exe" --help
& "$env:USERPROFILE\CodexTokenSaver\bin\playwright-cli.exe" -s=work open https://example.com --browser=msedge
& "$env:USERPROFILE\CodexTokenSaver\bin\playwright-cli.exe" -s=work snapshot
& "$env:USERPROFILE\CodexTokenSaver\bin\playwright-cli.exe" -s=work close
```

Use an installed Edge/Chrome browser, or run the CLI's documented browser installation command explicitly. Browser downloads, if requested, are scoped to `tools/playwright-browsers`; the installer does not silently download another browser. Use `--help` for the installed version's supported commands. Respect whichever browser tool/skill the host requires; bundle guidance does not override it.

For an Electron app whose owner has enabled a **loopback CDP endpoint**:

```powershell
& "$env:USERPROFILE\CodexTokenSaver\bin\playwright-cli.exe" -s=electron attach --cdp=http://127.0.0.1:9222
& "$env:USERPROFILE\CodexTokenSaver\bin\playwright-cli.exe" -s=electron snapshot
& "$env:USERPROFILE\CodexTokenSaver\bin\playwright-cli.exe" -s=electron detach
```

This controls Chromium renderer content. It is not native Windows UI automation or Electron main-process access. Apps without an enabled debugging endpoint cannot be attached this way; do not restart a user's running app just to create one. Playwright's separate experimental `_electron` API is for tests that launch/control an Electron application. The bundle does not install Electron or modify Codex/OpenCodex debugging settings.

Maintainer witness: `scripts/smoke_cli_electron.py --root BUNDLE --electron TEST_ELECTRON_EXE` uses a hidden disposable fixture, checks attach/snapshot/click/detach, then exits that fixture. Electron is a test dependency only.

## ast-grep

```powershell
& "$env:USERPROFILE\CodexTokenSaver\bin\ast-grep.exe" run --lang javascript --pattern 'console.log($A)' .\src
```

Single quotes keep PowerShell from expanding `$A`. Prefer `ast-grep`, not the ambiguous `sg` alias. Structural searches distinguish actual syntax from text in comments and strings. Keep `rg` for literal searches and Serena for symbols/references. Rewrite/update operations require an authorized edit and review of the resulting diff.

## RTK scope

RTK records supported external commands that actually pass through its wrapper. A trusted Codex hook routes eligible single Git/rg commands; PowerShell scripts, cmdlets, complex command sequences, and unsupported commands stay native. Consequently a script can run without changing the RTK dashboard. Zero-saving commands can increase command count without increasing saved tokens. The dashboard refreshes on its collector interval.

Sources: [Microsoft Playwright CLI](https://github.com/microsoft/playwright-cli), [Playwright Electron API](https://playwright.dev/docs/api/class-electron), [Electron debugging switch](https://www.electronjs.org/docs/latest/api/command-line-switches#--remote-debugging-portport), [ast-grep](https://github.com/ast-grep/ast-grep).
