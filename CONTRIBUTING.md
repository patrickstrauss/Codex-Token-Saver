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
