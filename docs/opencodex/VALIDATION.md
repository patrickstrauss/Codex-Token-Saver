# Validation — 2026-09-27

OpenCodex baseline: 4cb43cb0a8c6b60318cf0d63ffa8e57fd18407b2 (v2.64.0).
Candidate source: f6278f4b99ed24ce421838eea728b03d42aaeef9.
Bundle branch: codex/opencodex-compatibility.

## Installed repairs

- Windows GUI path regression reproduced, then fixed: 8 focused OpenCodex tests,
  46 assertions, TypeScript and structure checks passed. The rebuilt executable served
  HTML and both entry assets from an isolated home without a GUI-path override.
- Installed with a checksum-checked executable backup and restarted through `ocx restart`.
  The live dashboard rendered Online with its three configured providers.
- Token Saver runtime smoke passed. A cold synthetic transform timed out and safely
  bypassed; a fresh request compressed successfully and retrieved the exact original.
- Serena's Codex-side disabled flag was outside the bundle's comment marker.
  Enable/disable now handles that field as part of the owned MCP table: 16 tests passed.
  The user approved restoration; a live stdio session activated this checkout and read
  symbols and original bodies. Existing Codex tasks still need to reload their MCP tools.
- Installed runtime and dashboard checks are local; no provider probe was sent.
  Shared weekly meter: 5%, within the approved 8% cap.

## Earlier candidate evidence

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
called by that witness. Subsequent live repairs are recorded above. Provider settings,
credentials, chosen model and effort were preserved.

Windows reboot/login, real OpenAI/Azure/LM Studio usage, automatic reverse routing,
and live voice/catalog/native-steering qualification remain open. The full upstream
suite and docs-site build were not rerun under the user's weekly quota cap.
The full upstream suite was not repeated for these focused repairs under the quota cap.

## 2026-09-27 current Codex tool-result format repair

Observed real local replay shapes (counts only, no request content copied):
90 text-only tool outputs across three recent replay files, mostly custom-tool
outputs, with 74 larger than the selection threshold. The original integration
accepted only string function outputs, so these were all skipped.

OpenCodex now accepts both function/custom-tool outputs and text-only input_text
arrays that exactly match parsed text. Mixed-media, annotated, unknown and encrypted
blocks remain unchanged. Original history, call identity and array wire shape are preserved.
Three regressions failed before the change, then 19 focused tests passed (82 assertions).
The isolated real-service/adapter/server witness passed 3 tests (85 assertions),
including custom text blocks and forwarded function text blocks. Exact retrieval,
HTTP/WebSocket and retry reuse were verified without live provider probes.
TypeScript, structure and privacy checks passed. The rebuilt executable passed its
two CLI control tests (18 assertions) and version check.

The checked replacement executable is installed with the prior executable backed up.
The forced process-restart command was blocked by approval review. The documented
ocx restart command subsequently drained the old process and verified its replacement.
Live process19060 serves the repaired executable. Worker compressed outcomes advanced
from1 to4; two were explicitly local diagnostic calls, so at least one new compression
came from normal traffic. Recent OpenAI requests completed with status200.
The local replay diagnostic compressed13 replacements from33 eligible outputs in203ms;
a single recent output compressed in16ms. No separate paid-provider probe was sent.
Early requests bypassed; their detailed reason was not retained. This verifies the
observed OpenAI route, not other providers or a future reboot. No Windows restart is needed.
