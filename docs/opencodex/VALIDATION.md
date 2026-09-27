# Validation — 2026-09-27

OpenCodex baseline: 4cb43cb0a8c6b60318cf0d63ffa8e57fd18407b2 (v2.64.0).
Candidate source: c7afc595633f41e27ab36bcb46c3d8965cf48bd9.
Bundle branch: codex/opencodex-compatibility.

## Current candidate evidence

- Offline wire/core/real-server witness: **3 tests, 85 assertions passed**. Real
  HTTP/SSE and WebSocket sockets cover delta, reconnect full replay, concurrent chats,
  plus pause/resume on an existing socket. The socket provider receives eight sends.
- OpenCodex focused regressions: **374 tests passed across six files** (130 + 244).
  Includes consumer, CLI control/readiness, process liveness, native Responses passthrough
  and test layout. Two CLI cases also passed against the rebuilt executable (18 assertions).
- Bundle discovery/control/migration, source upgrade, launcher and disable checks:
  34 + 9 + 17 + 16 tests respectively after the final migration regressions.
- TypeScript, structure SSOT and privacy checks passed. GUI TypeScript/Vite build passed.
  The standalone Windows x64 executable was rebuilt after the live-policy correction.
- Full bundle candidate-1 smoke passed: fresh pinned Headroom/RTK/dashboard/Serena/
  LangMem/llama runtimes, repair, quality benchmark, repeated installation and isolated
  config-preservation checks. Candidate-2 adds source upgrade and handoff tooling;
  its separate upgrade/runtime/rollback report is in the final delivery folder.
- All PowerShell upgrade entry points parse successfully.

The live-policy regression first demonstrated stale readiness after a persisted Pause;
the fix passes without restarting the server. A fixture-only invalid codexAccountMode
was corrected to apply only to the built-in OpenAI provider. No provider validation
was weakened. Python tests use the existing SDK interpreter for tomlkit-dependent
suites; the dashboard interpreter lacks that dependency.

The earlier checkpoint's 762 focused tests remains historical evidence, not an
additional count to add to this run. Process/clock drain tests do not prove a real reboot.

## Scope

The witness uses deterministic compression inside the real local service, with a
separate prior installed-SDK compression/exact-recovery witness. No paid provider was
called. No live install, route, credentials, chosen model or effort was modified.

Windows reboot/login, real OpenAI/Azure/LM Studio usage, automatic reverse routing,
and live voice/catalog/native-steering qualification remain open. The full upstream
suite and docs-site build were not rerun under the user's weekly quota cap.
The shared meter last read 4%; the user raised the cap from 5% to 8%.
