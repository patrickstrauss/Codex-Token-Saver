# Request proxy implementation plan

**Goal:** Provide the broader request compression used by Headroom desktop while recovering safely from backend/startup failures.

**Architecture:** Fast relay, separate managed compression backend, independent supervisor, scoped built-in-provider override and guarded dashboard controls.

**Tech stack:** Python, aiohttp, installed Headroom SDK, ONNX Runtime, Windows scheduled task, Flask dashboard.

- [x] Implement and test managed coding-profile backend and isolated local-model warmup.
- [x] Implement and test transparent HTTP/SSE/WebSocket relay with pre-dispatch fallback only.
- [x] Implement and test supervised lifecycle, Windows logon startup and pause that preserves cached connections.
- [x] Implement and test scoped atomic routing activation/rollback and validation gating.
- [x] Add guarded dashboard controls and separate request-savings reporting.
- [x] Verify startup, backend failure, model/effort preservation and actual Codex requests before activation.
- [x] Enable authorized routing, verify dashboard and record recovery instructions and restart boundary.

Validation: 260 core tests and 175 dashboard tests passed. Real Codex optimized/direct requests, backend crash recovery, durable savings, and installed Restore Direct/re-enable passed. Routing enabled in proxy/activation.json. A full Windows reboot was not performed; Codex itself was left running for the user's active tasks.
