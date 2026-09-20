# Library updater

The user wants an easy way to update the libraries used by Codex Token Saver. Provide a local dashboard panel with manual version checks, component updates, progress, errors, and rollback.

Manage RTK and the Headroom desktop runtime plus its Python dependencies. Preserve the custom dashboard adapter, tray, hooks, all savings history, selected model/reasoning, credentials, and direct Codex connection. The experimental CLI proxy remains separate. Do not start checks or install updates automatically at login.

Use PyPI's Headroom package metadata and RTK's official GitHub release metadata. Pin the candidate from a completed server-side check. Do not accept arbitrary package names, versions, URLs, paths, or shell commands from the browser. Verify RTK's official SHA-256 digest. Run package installation through bundled uv with official PyPI, configuration disabled, and no interpreter downloads.

Stage Headroom in a new managed virtual environment. Check dependencies and run real offline compression, exact recovery, and MCP import validation with separate test state. Only then atomically activate its manifest entry. New tool processes use the selected packages; active processes keep their previous imports until restarted. Invalid selection falls back to the baseline runtime. No Codex configuration change is required.

Stage and verify RTK before atomically replacing only the underlying executable. Preserve the custom launcher and keep a verified previous binary for rollback. If the executable is busy, retain the current version and report a retryable failure; do not stop user commands.

The dashboard performs long work in a background job, enforces one updater across processes, and reports stage/message/error. Mutating routes require the expected loopback Host, same Origin, and an unpredictable page token. GET status never installs or checks online. Restart or network failures leave the active version intact.

Validation includes mocked failure boundaries, real current-release installation and rollback in an isolated bundle, dashboard API/JavaScript tests, and a browser check of the installed panel. Do not count fixture activity as production savings.
