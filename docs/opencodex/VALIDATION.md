# Validation — 2026-09-27

Candidate branch: codex/opencodex-compatibility. OpenCodex baseline:
4cb43cb0a8c6b60318cf0d63ffa8e57fd18407b2 (v2.64.0).
Current source commit: 4e13350 (clean validation checkout; original prototype e76750c).

Continuation verification: **762 focused tests passed**: 224 bundle Python tests in
14 suites, 138 dashboard tests, 398 OpenCodex tests in seven files, and two offline
wire/core witness tests. TypeScript, structure and privacy checks passed. The exported
patch is checked against the baseline using a disposable Git index.

New cases cover conditional extension updates, readiness sanitization, external removal,
lost replies followed by cold starts, offline pause/disconnect cancelling warmup, damaged
settings, live policy gating, retrieval retention, owned-worker drain, and automatic
pending activation. Process/clock transition tests are isolated simulations, not reboot
or live migration evidence. Dashboard/legacy controls delegate to the extension.

The following table records the earlier checkpoint; its counts are not additional tests
to add to the continuation total.

| Check | Result |
| --- | --- |
| Bundle Python discovery, transform, retrieval, native runtime, integrations, disable, launch and summary coverage | 142 tests passed across 13 suites |
| Dashboard controls, app and component routes | 137 tests passed |
| Native C# launchers | Built in the isolated checkout; all four included launcher tests passed |
| Install configuration script | Passed transaction, rollback, concurrency, disabled-settings and idempotence assertions |
| OpenCodex consumer, Responses passthrough, test layout and optional-subsystem boundary | 240 tests passed in five files |
| Offline service/adapter/core witness | Two tests passed, 40 assertions; see offline-witness.json |
| OpenCodex TypeScript compiler | Passed with the installed TypeScript 7.0.2 entry point |
| OpenCodex structure and privacy scripts | Passed with direct Bun invocation |
| Patch application | git apply --check and apply passed against a clean baseline clone |
| Actual local compression SDK | Synthetic 7,475-character log compressed; one replacement; exact original recovered |

The witness uses a deterministic compressor inside the actual HTTP transform service.
The separate local SDK witness verifies the compression engine. Neither substitutes for
real provider billing or correctness comparisons.

Environment corrections: the isolated bundle initially lacked compiled launcher binaries;
they were built before rerunning the four launcher checks. Bun's package-bin wrapper failed,
so compiler and validation scripts ran directly with the same pinned dependencies.

The broad changed-test run was stopped without a suite result. It left an inaccessible
temporary test directory; the focused layout checks were rerun successfully in a clean
clone with the exact exported patch. No runtime code was relaxed to pass those checks.
The public documentation site build, full upstream suite, real WebSocket sockets/reconnects,
real providers, complete route migration, live install, login/reboot and upgrade qualification
remain pending.

The shared weekly meter was 0% at the initial checkpoint and 3% at this continuation
checkpoint. It is a coarse account meter, not exact per-chat accounting.
