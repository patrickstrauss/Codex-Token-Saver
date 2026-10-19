# Contributing

Open a focused issue or pull request describing the problem, expected behavior,
and a reproducible example with synthetic data. Do not upload real chats,
credentials, runtime directories, original-content caches or personal diagnostics.
Contributions to original project code use the root license; preserve upstream
notices on third-party material.

Development targets Windows x64 and PowerShell 5.1+. Use a separate Python 3.13
environment. Install `dashboard/requirements-dev.txt` and the pinned dependencies
needed by the module under test. Never test installation/removal against your
daily Codex profile. See `packaging/Smoke-Package.ps1` for the isolated profile.

Run the relevant `tests/` and `dashboard/tests/` tests, then build and smoke-test a
package on a clean Windows runner. The [release checklist](docs/RELEASE-CHECKLIST.md)
defines the acceptance gates. Download hashes, runtime constraints and upstream
licenses need review when dependency pins change. Keep public benchmark fixtures
deterministic and report regressions/overheads as well as reductions.

Release-tooling tests that use only the Python standard library:

```powershell
python -m unittest tests.test_release_audit tests.test_codex_context_benchmark tests.test_harness_clients tests.test_source_upgrade tests.test_performance_benchmark tests.test_storage_cleanup
```

Server-protocol checks use the installed Headroom Python and
`scripts/verify_harness_protocol.py`; see [client setup](docs/CODING-CLIENTS.md).
The native context benchmark defaults to a plan with no model calls. Read
[benchmark limits](docs/BENCHMARK.md) before opting in with `--run`.

Before releasing, build to a new version/output directory and audit the source ZIP:

```powershell
.\packaging\Build-Package.ps1 -Version local-preview -OutputDirectory .scratch\release-check
python scripts\check_release.py --package .scratch\release-check\Codex-Token-Saver-local-preview-windows-x64.zip --output .scratch\release-check\package-audit.json
.\packaging\Check-Secrets.ps1 -ReportPath .scratch\release-check\security-history.json
.\packaging\Check-Secrets.ps1 -Mode Directory -Target .scratch\release-check\Codex-Token-Saver-local-preview-windows-x64 -ReportPath .scratch\release-check\security-package.json
.\packaging\Test-SecretScan.ps1
```

Do not share full scanner findings or source snippets publicly. CI publishes
redacted reports and provenance; an explicitly requested release remains a draft
until owner review. Check [release status](docs/RELEASE-STATUS.md) before making
stable-release or live-client compatibility claims.
