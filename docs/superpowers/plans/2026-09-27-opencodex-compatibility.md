# OpenCodex Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for the recommended inline execution, or superpowers:subagent-driven-development if explicitly selected. Steps use checkbox syntax for tracking.

**Goal:** Make the complete Token Saver bundle coexist with OpenCodex and provide optional, recoverable request compression without taking ownership of OpenCodex routing.

**Architecture:** Retain the native Codex integration. Add an OpenCodex control adapter and a versioned, transformation-only Headroom service, called from OpenCodex before provider serialization. Reuse the dashboard, component controls, exact-retrieval machinery, and managed worker.

**Tech Stack:** Existing Python/PowerShell/C# bundle; existing Headroom runtime; TypeScript/Bun in OpenCodex. No additional model, routing proxy, or global hook.

**Spec:** [Approved design](../specs/2026-09-27-opencodex-compatibility-design.md), approved by the user after the design turn.

## Global constraints

- “Keep original history and OpenCodex's persisted response state unchanged.”
- “The integration creates no additional provider retry, account fallback, or model/effort downgrade.”
- “Retrieval must remain usable while compression is paused.”
- “Unsupported paths bypass compression until qualified.”
- “Existing independent component toggles remain.”
- “Do not migrate active chat history or automatically restart Codex.”
- Preserve the selected model, reasoning, authentication, approval behavior, managed routing, and unrelated user edits.
- Windows is the release target. OpenCodex 2.64.0 / `4cb43cb0a8c6b60318cf0d63ffa8e57fd18407b2` is the inspected baseline, not a promise that every later version is compatible.
- Continue observing the user's 5% weekly-quota ceiling. Use one implementer, no paid-provider experiments during unit work, and checkpoint usage after each increment. Begin handover by a reported 4-percentage-point increase; a coarse/shared or stale meter cannot guarantee exact attribution. Do not assume approval removes the cap.
- Do not modify the stable installation during development. No automatic upstream update or live migration. Prepare reviewable packages and rollback receipts first.

## Review focus

1. A config file changes between preflight and write: preserve the external edit and report conflict (Task 4).
2. A retriever result is nested in a JSON envelope or contains CRLF/Unicode: return it exactly and never compress it again (Tasks 2–3).
3. Reconnects and provider retries revisit the same content: reuse the transform decision without adding a provider send (Task 3).
4. OpenCodex's shim resolves back to a bundle launcher: detect recursion before starting a process (Task 5).
5. Updates leave an old worker or stale compression reference alive: validate the serving runtime and retain retrieval while draining (Tasks 2, 4, 6).

## Delivery order and workspace

Increment A is Task 1: detection and honest partial status on unmodified OpenCodex, retaining existing local features. Increment B is Tasks 2–4: a qualified local protocol plus OpenCodex extension. Increment C is Tasks 5–6: complete local-feature/lifecycle qualification, packaging, and release evidence. Full compatibility requires all increments.

At execution, inspect attached worktrees and reuse a suitable checkout; otherwise create managed isolation using the worktree tools. Keep the approved spec and this plan available in that checkout. Preserve the three pre-existing untracked research documents. Use a separate OpenCodex source checkout pinned to the inspected commit; never edit `C:\Program Files\OpenCodex`.

Do not choose the provider insertion point from file names alone. Task 3 begins with a bounded call-path audit. Its result must identify every outbound serialization boundary or explicitly mark a path unsupported. If the public extension cannot be delivered, ship Increment A as partial compatibility and retain the remaining work as unshipped.

Paths below are repository-relative. Paths prefixed `OpenCodex:` belong to the separate upstream checkout. New module and API names are implementation decisions from this plan, not claims about existing APIs.

## File and interface map

| Unit | Files | Responsibility |
|---|---|---|
| Detection and control | New `opencodex_integration.py`; existing `bundle_controls.py`, `desktop_proxy_control.py` | Discovery, mode selection, status, reversible transitions |
| Transform service | New `request_transform.py`, `request_transform_service.py`; existing `proxy_runtime.py`, `desktop_proxy_service.py`, `proxy_retrieval.py` | Bounded text-only protocol, existing compressor, recovery, worker mode |
| Upstream consumer | New `OpenCodex:src/integrations/token-saver.ts`; existing `src/server/responses/`, configuration/capability handlers located in Task 3 | Select eligible fields, validate replacements, integrate once before serialization |
| Product controls | Existing `dashboard/proxy_routes.py`, `dashboard/static/proxy.js`, `dashboard/static/components.js` | Mode-specific actions and trustworthy status |
| Lifecycle | Existing `launch_codex.py`, `bundle_integrations.py`, `disable_bundle.py`, `packaging/configure_install.py` | Launch, registration, install/repair/disable ownership |
| Delivery | Existing package scripts and `.github/workflows/windows-package.yml`; new `scripts/verify_opencodex_integration.py` | Offline qualification, package matrix, real workflow witness |

## Task 1: Read-only detection and coexistence status

**Files:** Create `opencodex_integration.py`, `tests/test_opencodex_integration.py`; modify `bundle_controls.py`, `dashboard/static/components.js`; extend `dashboard/tests/test_bundle_controls.py` and `test_components_ui.py`.

**Interfaces:** Define frozen `OpenCodexProbe` with `installed: bool`, `version: str | None`, `config_home: Path | None`, `endpoint: str | None`, `ready: bool`, `transform_protocol: int | None`, `reason: str | None`. Produce `probe_opencodex(*, executable: Path | None, run: Callable) -> OpenCodexProbe`. `run(argv: list[str], timeout_seconds: float) -> CompletedProcess[str]` is injected for testing; no shell.

- [ ] Write tests `test_installed_is_not_ready`, `test_legacy_has_no_transform`, `test_probe_is_read_only`, and `test_wrong_listener_is_not_opencodex`. Assert installed 2.64.0 with no declared extension yields `transform_protocol is None`; no start/sync/ensure/config-write command is executed. Include nondefault ports, `CODEX_HOME`, malformed JSON, timeout, profile override, and absent executable.
- [ ] Run `python -m unittest discover -s tests -p test_opencodex_integration.py`; expect failure for the missing module/assertions, not a broken harness.
- [ ] Implement discovery through version and documented read-only machine-readable commands. Bound each subprocess to two seconds and returned text to 64 KiB; parse only allowlisted fields. Resolve effective profile/environment separately from installed-state detection. Never print secrets or conclude routing from a port alone.
- [ ] Add status copy `Unavailable: OpenCodex integration required` when the extension is absent. Preserve native proxy behavior, RTK, Headroom file tools, Serena, and experimental controls. Do not enable a component during status reads.
- [ ] Rerun the focused suite and the two dashboard tests; assert native status unchanged, optional components still usable, and unavailable differs from off. Commit only Task 1 files.

## Task 2: Recoverable, bounded transform service

**Files:** Create `request_transform.py`, `request_transform_service.py`, `tests/test_request_transform.py`, `tests/test_request_transform_service.py`; modify `proxy_runtime.py`, `desktop_proxy_service.py`, `proxy_retrieval.py`; extend existing exact/retrieval/runtime tests.

**Interfaces:** Define `TransformEntry(id: str, original_sha256: str, text: str)`, `TransformRequest(protocol: int, request_id: str, scope_id: str, budget_ms: int, entries: list[TransformEntry])`, and `TransformReply(protocol: int, request_id: str, outcome: str, replacements: list[Replacement])`. `Replacement` contains `id`, `original_sha256`, `replacement`, `retrieval_reference`, all strings. Outcomes are `compressed`, `unchanged`, `bypassed`, or `error`; only `compressed` may carry replacements. Produce `TransformService.transform(request: TransformRequest) -> TransformReply` and `create_transform_app(service: TransformService) -> ASGIApp`, using `starlette.types.ASGIApp` from the existing backend stack. Inject the compressor, original store, and monotonic clock for offline tests.

Protocol v1 decisions: `GET /v1/transform/capabilities`, `POST /v1/transform/tool-results`; 500 ms request budget, maximum 128 entries and 8 MiB UTF-8 request/response bodies, two active transforms and no waiting queue. Busy/cold requests bypass. Cache at most 128 decisions/32 MiB total with a 30-minute maximum TTL, further limited by referenced-original expiry. Cache keys include scope, content digest, policy version, and runtime generation. Cache failures/bypass for the logical content version to avoid repeated slow work during retries.

- [ ] Write tests asserting unchanged input for invalid hashes/duplicate IDs, oversized bodies, overload, timeout, missing originals, unknown schemas, and no net reduction. Assert authenticated exact text and existing compression markers remain byte-identical, including nested envelopes, CRLF, and Unicode. Assert no remote HTTP/provider send can occur from the transform service.
- [ ] Run both new test files individually with `python -m unittest discover -s tests -p <filename>`; expect the new behavior to fail before implementation. Use fake clocks/compressors, not the local model, for these tests.
- [ ] Implement strict parsing and whole-reply rejection. Reuse the existing Headroom policy/exact guard behind a narrow adapter; verify its pinned SDK call shape before binding it. Persist originals before returning replacements. Reuse the current 12-character retrieval store/bridge only if its real SDK contract passes; otherwise update protocol and both consumers together before continuing, rather than emulating a stock marker.
- [ ] Expose the two endpoints with a random local bearer stored under the bundle's ACL-protected state. Restrict capability/control access; keep it out of logs. A transform-only worker serves health/retrieval and these endpoints, with provider-forwarding routes absent. Preserve existing native worker mode. Update retrieval authentication as needed while keeping `read_proxy_original(content_hash)` source-compatible.
- [ ] Implement deadline cancellation, bounded concurrency/cache, and a circuit breaker: three consecutive service failures open it for 30 seconds, followed by one probe. Pausing or breaker-open skips compression but retains original retrieval. Do not unload/restart a model while an accepted operation is active.
- [ ] Run new suites plus `test_exact_retrieval.py`, `test_proxy_retrieval.py`, `test_desktop_retrieval_bridge.py`, `test_proxy_runtime.py`, and `test_runtime_receipt_serving.py`. Then perform one isolated real-SDK compression/retrieval check and prove there is no duplicate model worker. Commit Task 2 files.

## Task 3: OpenCodex consumer and complete transport coverage

**Files:** Create `OpenCodex:src/integrations/token-saver.ts`, `src/integrations/token-saver.test.ts`, `src/server/responses/token-saver.test.ts`; modify the exact existing config, capability, and request serialization owners identified by the initial audit. Record those verified paths in this plan before implementation; do not fabricate an upstream hook.

**Interfaces:** Define `TokenSaverConfig = { enabled: boolean; endpoint: string; tokenFile: string; protocol: 1 }`. Add optional `tokenSaver` config through OpenCodex's existing validated configuration machinery. Protocol v1 accepts only the fixed service origin `http://127.0.0.1:8789`; unrelated endpoint/custom-port support is outside this protocol. Produce `transformToolResults(request: Record<string, unknown>, context: TransformContext): Promise<Record<string, unknown>>`; `TransformContext` includes `scopeId: string`, `contentVersion: string`, `signal: AbortSignal`, `config: TokenSaverConfig`, and `localFetch: typeof fetch` injected without environment-proxy support. Its input is a canonical, hydrated outbound copy. The returned object may differ only at submitted tool-text locations.

- [ ] Trace HTTP/SSE, WebSocket create/delta/reconnect, native-forward, translated adapters, and internal retries from admission through final serialization. Record where original state is persisted and where each outbound copy is created. Confirm upstream test commands from its package manifest. No full-repository refactor.
- [ ] Write fixtures asserting selected provider/model/effort, call IDs, roles, schemas, original history, and opaque/image/audio data remain equal. Unknown fields remain equal. A malformed replacement causes the whole transform reply to be ignored. Assert no extra provider send and one transform decision for a retried content version. Exercise user cancellation and parallel scopes.
- [ ] Run `bun test src/integrations/token-saver.test.ts src/server/responses/token-saver.test.ts`; expect failures for the proposed integration only. Tests use fake service/provider endpoints and synthetic credentials.
- [ ] Implement extraction of supported textual tool outputs, one local authenticated call, strict response/hash validation, and copy-on-write replacement. Never send credentials, prompts, model routing metadata, or arbitrary request bodies to the service. Do not follow redirects or use environment proxies. Abort late replies and reuse decisions across existing retries.
- [ ] Add the default-off config and advertised protocol capability. Apply at all verified boundaries after hydration and before serialization. Server-retained history is not transformed; unsupported paths bypass explicitly. Leave voice, images, catalog, compaction, account selection, and OpenCodex's existing retry policy unchanged.
- [ ] Rerun the two suites and affected upstream transport/config tests identified during the audit. Run one cross-process fake-provider witness against the real Task 2 service, including marker retrieval through MCP. Commit the OpenCodex change separately; record the build SHA. No claim of full coverage if any required transport lacks a witness.

## Task 4: Reversible controls and migration

**Files:** Modify `opencodex_integration.py`, `bundle_controls.py`, `desktop_proxy_control.py`, `desktop_proxy_service.py`, `dashboard/proxy_routes.py`, `dashboard/static/proxy.js`; extend `tests/test_opencodex_integration.py`, `test_desktop_proxy_control.py`, `test_desktop_proxy_service.py`, `dashboard/tests/test_proxy_routes.py`, `test_proxy_ui.py`.

**Interfaces:** Produce `OpenCodexControl(root: Path, *, probe: Callable, run: Callable)` with `status() -> dict`, `set_enabled(enabled: bool) -> dict`, `prepare_migration() -> dict`, and `apply_migration(receipt_id: str) -> dict`. Match existing `proxy` injection in `BundleControls` rather than adding a generic plugin framework. Store mode and transition receipts in `proxy/integration.json`; leave strict `settings/components.json` untouched.

- [ ] Write tests for version/capability mismatch, pause without native restore, stale receipts, external edits, failed warmup, interrupted migration at each step, and active connections. Assert provider credentials, selected model/effort, history, unrelated TOML bytes, and OpenCodex processes survive disable/pause.
- [ ] Run the three focused root suites and two dashboard suites; establish the new failing cases first.
- [ ] Implement receipt states `prepared`, `native_restored`, `ocx_ready`, `extension_enabled`, `complete`, and `conflict`. Store scoped before/after fingerprints without secrets. Every mutation rechecks ownership. Restore only values still owned; never restore a whole stale config. Serialize bundle actions with existing locks and respect OpenCodex's own transaction API.
- [ ] Warm/validate before routing changes. Retain old native relay/backend until existing connections drain; then transition the shared worker safely to transform-only mode. Use the newly validated upstream config API for extension changes. If upstream setup unexpectedly alters selected settings/history/provider identity, stop the migration and report a recoverable conflict.
- [ ] Add mode-specific dashboard actions: pause compression, disconnect Token Saver, and explicitly switch to native Codex. Never call `ocx stop` or `ocx restore` for ordinary compression pause. Show requested, ready, bypass reason, recent activity, and reload requirements separately. Status reads must remain side-effect-free.
- [ ] Pass all focused regressions and an isolated interruption/resumption witness. Commit Task 4 files.

## Task 5: Launcher, all local components, and owned cleanup

**Files:** Modify `launch_codex.py`, `bundle_integrations.py`, `disable_bundle.py`, `packaging/configure_install.py`; extend `tests/test_launcher.py`, `test_native_codex_launchers.py`, `test_bundle_integrations.py`, `test_disable_bundle.py`, `test_summary_reader_coverage.py`, `packaging/test_configure_install.py`. Change native launcher/PowerShell startup code only if a demonstrated contract requires it.

**Interfaces:** Add `resolve_launch_command(arguments: list[str], *, mode: str, probe: OpenCodexProbe | None) -> list[str]`; use existing `run_cli` for execution. `mode` is `native` or `opencodex`, taken from the Task 4 receipt. Resolve the documented installed shim/runtime path; absence is an actionable error, not a guessed native fallback.

- [ ] Add regression tests for path spaces/Unicode, literal argv, shim recursion, custom config home, off/on toggles, and repeated install/repair/disable. Assert no change to model/reasoning/auth variables, no double MCP registration, and no rerun of an external command.
- [ ] Verify RTK filtering/exact bypass, trusted hook behavior, Headroom local originals, Serena four-tool exposure/project isolation, and experimental summary parsing under the actual OpenCodex-launched environment. Use synthetic rollout records for unfamiliar compaction; assert explicit incomplete/unsupported coverage without rewriting history.
- [ ] Run the listed root suites individually, and `python -m unittest discover -s packaging -p test_configure_install.py`; establish failures before changes. Then implement mode-aware launching and cleanup of only owned configuration. Preserve OpenCodex shim, journals, credentials, catalog, and service.
- [ ] Rerun affected tests plus existing RTK, MCP, Serena, and summary regressions only where changes touch those paths. Pass a temporary-profile install/repair/disable round trip. Commit Task 5 files.

## Task 6: Package and qualify the frozen candidate

**Files:** Create `scripts/verify_opencodex_integration.py` and `docs/OPENCODEX-INTEGRATION.md`; modify `packaging/Build-Package.ps1`, `packaging/Smoke-Package.ps1`, `packaging/verify_install.py`, `.github/workflows/windows-package.yml`, `docs/USING-BUNDLE.md`, `DESKTOP-REQUEST-PROXY.md`. Update runtime validation/hash lists wherever new files participate.

**Interfaces:** Witness CLI `python scripts/verify_opencodex_integration.py --bundle-root PATH --ocx-command PATH --output PATH` uses temporary config homes and fake providers by default. Output a credential-free JSON report with versions/source hashes, case results, bypass reasons, timings, provider-send counts, and cleanup status. No real-provider mode until separately bounded against remaining quota.

- [ ] Add package fixtures for native-only, unmodified OpenCodex, and compatible-extension installations, in both installation orders. Assert missing/mismatched extension produces honest partial status and no routing changes. Include rollback to an old runtime and retained-original retrieval.
- [ ] Pass the offline witness: HTTP/SSE, WebSocket, delta/reconnect, native-forward, translation, exact recovery, failures, concurrent chats, and component toggles. A skipped required case is not PASS.
- [ ] Freeze candidate hashes; run required root/dashboard checks once, then existing `packaging/Build-Package.ps1 -Version opencodex-candidate -OutputDirectory <temporary-directory>` and `packaging/Smoke-Package.ps1 -PackageDirectory <built-package>`. Use a resolved temporary directory inside the test workspace. Repeat only for a relevant failure or changed input.
- [ ] In a disposable Windows environment, validate actual reboot/login, process counts, model memory, retained retrieval, launcher selection, uninstall, and rollback. Preserve installed OpenCodex state. Record evidence; simulated startup is not reboot qualification.
- [ ] Prepare a small real-provider comparison for configured OpenAI, Azure OpenAI, and LM Studio routes. Require available credentials/models and a remaining-budget check; use one fixed tiny workflow per route with compression off/on. Compare correctness, provider usage/cache behavior, latency, and retrieval overhead. Do not repeatedly rerun inconclusive paid calls. An untested route remains unqualified.
- [ ] Document validated versions, supported paths, remaining limits, recovery actions, and separate savings scopes. Stage the package and OpenCodex integration for review; do not deploy or publish an upstream change automatically. Commit delivery files with the evidence references.

## Commands and completion criteria

For root Python tests, use an already available compatible interpreter with the pinned bundle dependencies. Record its absolute path; do not install into or modify the stable runtime. `python` above denotes that interpreter. For dashboard cases run its existing pytest environment from `dashboard/`, for example `python -m pytest tests/test_proxy_routes.py tests/test_proxy_ui.py`. Before each suite, confirm collection/startup so dependency failures are not confused with product failures. Prefer RTK for supported commands; use exact output for assertions/machine parsing.

Each implementation task follows red test → minimal code → green test → scoped commit. No implementation tests were run while writing this plan. Plan review covered the approved spec, existing bundle interfaces, test names, package commands, and the explicit unresolved upstream call-site audit.

Completion means all required offline and Windows witnesses pass, the supported real routes are explicitly qualified, recovery is proven, and reviewable artifacts exist. Code compilation or local-tool coexistence alone does not meet the full-bundle requirement. If the quota reserve is reached first, stop with the last validated increment, source/build IDs, exact evidence, and remaining work; do not label the overall integration complete.

Recommended execution: inline in this chat, one task at a time, preserving the current model/effort. This minimizes repeated context and suits the shared protocol dependencies. Independent review, if tooling and quota permit, should focus on routing ownership, exact retrieval, and transport coverage rather than duplicating the whole investigation.
