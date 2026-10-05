# Test Serena in Codex

## Repeatable acceptance check

After installing the bundle, paste this command into PowerShell. It uses the installed Serena runtime, including an updated runtime when selected:

```powershell
& {
    $bundle = "$env:USERPROFILE\CodexTokenSaver"
    $runtime = 'serena\.venv\Scripts\python.exe'
    if (Test-Path "$bundle\serena\runtime.json") {
        $runtime = (Get-Content "$bundle\serena\runtime.json" -Raw | ConvertFrom-Json).python_path
    }
    & (Join-Path $bundle $runtime) "$bundle\scripts\verify_serena_navigation.py"
}
```

Expect exit code `0` and JSON containing `"ok": true`. Results and diagnostic stderr are saved under `CodexTokenSaver\logs\serena-navigation-report.json` and `serena-navigation-stderr.log`. A failure exits nonzero; an older report is not evidence of the failed run, so check `checked_at`.

This uses the real official Serena server and its Python and TypeScript language servers through the bundle MCP wrapper. It checks:

- Exactly four navigation tools before and after project activation.
- Initialization and tool listing without starting a Serena backend.
- Python and TypeScript symbol overviews, definitions and callers.
- Complete returned bodies against native source lines, authenticated exact-response receipts, and fresh results after file edits.
- Switching between two absolute checkout paths with different definitions, then switching back.
- Idle backend/LSP cleanup, restoration of the last checkout on the next lookup, and complete cleanup after client shutdown. The isolated check accelerates the two-minute idle timeout to two seconds.
- Unsupported text files and missing files returning errors; native file reads remain usable.
- Off/on in the same connection, using isolated preferences, and a real missing-runtime startup failure.
- Completed, failed and blocked activity counts with no source text or project paths in the aggregate ledger.

The check creates temporary projects, state and a small wrapper copy; it reads the installed dependencies. It does not change your live toggle, Codex configuration, provider route, model or reasoning setting. For the separate bridge interpreter used by your MCP configuration, append `--bridge-python "C:\path\to\python.exe"`. This verifies the backend contract; it does not prove Codex chooses Serena for every task, or measure token/quota savings.

## Try an ordinary coding task

Enable **Serena symbol navigation** in the bundle dashboard. Restart Codex once after installing this update so its tools and guidance reload. Open a task in the Codex-Token-Saver checkout and send:

> Explain how SerenaBridge.call_tool handles the live toggle and exact source responses. Find its callers and verify the implementation. Do not edit files.

Check the task's tool calls: expect `activate_project` with this checkout's absolute path, followed by a symbol overview, `find_symbol` with `include_body=true`, and reference lookup where useful. The explanation should match `serena_proxy.py`. Serena is guidance for relevant navigation; native tools are also valid when a query is unsupported or unhelpful.

To check an existing task after restarting Codex, resume it with:

> Use the enabled bundle Serena tools to activate this checkout by its absolute path. Find SerenaBridge.call_tool, retrieve its exact body and references, and explain what happens when Serena is off. Do not edit files.

For a project switch, open or resume a task in a different checkout and ask about a function that exists there. Verify that Codex activates that checkout before looking it up. If the tools are absent, check the dashboard's availability explanation and restart Codex after enabling Serena.

## See whether it was used

The dashboard's **Serena symbol navigation** row shows recent activity plus completed, failed and blocked calls. Its aggregate ledger is `CodexTokenSaver\serena\activity.json`; detailed tool names and results are visible in the Codex task. Official Serena also keeps local logs/state under `CodexTokenSaver\serena\state`.

The isolated acceptance check has its own counters, so it does not inflate your dashboard's live totals. A manual Codex query should update the live row. These counters show calls, not token savings. Use the isolated check above to test Off without disrupting other running tasks.

On 2026-10-05, the real Python/TypeScript fixture released 588.5 MiB of summed working sets after idle shutdown and resumed exact navigation in the correct checkout. Shared pages can be counted more than once; this is a fixture measurement, not a promised reduction for every chat. The report's `lifecycle` section records process ownership and working sets.
