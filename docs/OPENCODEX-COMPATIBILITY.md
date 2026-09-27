# OpenCodex compatibility — implementation checkpoint

Status: **experimental source candidate; full-bundle integration is not release-qualified**.
The stable installation, live route, selected model and reasoning settings were not changed.

The approved [design](superpowers/specs/2026-09-27-opencodex-compatibility-design.md)
keeps OpenCodex responsible for routing, credentials, catalog, voice and subagents.
Token Saver supplies local tool optimization and a transform-only Headroom service.
This avoids chaining a second model-routing proxy around OpenCodex.

Flow: Codex → OpenCodex history reconstruction → copy eligible tool text →
local Headroom transform → validate replacements or bypass → OpenCodex adapter →
selected provider. Originals stay in a separate durable local store for exact retrieval.

## Implemented

- Read-only OpenCodex resolve/readiness discovery and effective Codex route matching,
  including custom homes/profiles. Installation alone does not establish readiness.
- Honest dashboard status: existing OpenCodex without a qualified extension cannot
  enable the bundle's native request route. Independent local-tool controls remain.
- Protocol-v1 service with bounded inputs, bearer authentication, two worker slots,
  deadlines, overload bypass, circuit breaking, and durable 30-minute originals.
  Authenticated exact outputs, existing markers and unsupported structured results bypass.
- Retrieval bridge support for the transform service. Retrieval survives pause and
  process restart within retention. Compression includes recovery instructions when
  deciding whether the replacement is smaller.
- An upstream OpenCodex 2.64.0 source patch. It wraps adapter builds after history
  reconstruction, changes outbound copies, validates the entire transform reply,
  shares decisions through existing rebuilds, and preserves model/effort and original history.
- A repeatable offline consumer/adapter witness with isolated local endpoints.

The source patch is in [the integration directory](opencodex/README.md).
It targets commit 4cb43cb0a8c6b60318cf0d63ffa8e57fd18407b2.
It is not installed and does not publish a readiness capability.

## Verification scope

See [validation results](opencodex/VALIDATION.md) for counts and environment limitations.

| Area | Evidence / limitation |
| --- | --- |
| Discovery and native-route guard | Focused Python/dashboard regressions |
| Transform/retrieval | Protocol, invalid response, exact-protection, restart, pause, timeout, overload and recovery tests |
| Actual compression engine | Isolated installed-SDK witness compressed a synthetic log and recovered its exact original |
| Responses/Chat adapters | Real local transform HTTP service; two expected local fake-provider sends |
| Request pipeline | Three expected mocked provider sends through HTTP and WebSocket-prepared core, including native forwarding |
| TypeScript | Direct installed compiler check; the Bun package-bin wrapper failed to resolve on this machine |
| Real WebSocket socket/reconnect | Pending; a prepared turn into the core does not qualify the socket transport |
| Native steering/injection, runTurn adapters | Unsupported; bypass explicitly |
| Voice, catalog, images, compaction | No transform hook on these routes; live regression qualification pending |
| Migration/rollback/disable | Native ownership behavior retained; OpenCodex migration receipts and extension controls pending |
| Windows login/reboot/upgrades | Pending |
| OpenAI, Azure OpenAI, LM Studio usage | No paid or real-provider comparisons performed |

Estimates are not provider billing measurements. RTK, local-output and request savings
must not be summed because their counted work can overlap.

## Remaining release gates

Follow [implementation tasks 3–6](superpowers/plans/2026-09-27-opencodex-compatibility.md):

1. Complete transport/replay/cancellation qualification and publish the extension's
   capability through identity-checked OpenCodex readiness.
2. Add reversible migration receipts, drain existing native connections, and retain
   their retrieval references. Native and transform workers share port 8789; the
   supervisor must own the transition before enabling this mode.
3. Add validated OpenCodex configuration transactions and extension pause/disconnect
   controls. Pause must retain OpenCodex routing; uninstall must preserve its service.
4. Complete mode-aware launch, effective-home registrations, install/repair/disable,
   update and Windows reboot checks.
5. Qualify available real provider routes once the remaining quota permits it.

No automatic deployment or migration is included in this checkpoint.

## Offline witness

Use the prepared source patch and an interpreter with the bundle's existing
Headroom dependencies. The witness uses a temporary store, an ephemeral loopback
port and fake providers; it neither uses the live 8789 listener nor provider credentials.

    python scripts/verify_opencodex_transform.py --ocx-source PATH_TO_PATCHED_SOURCE --bun PATH_TO_BUN --output PATH_TO_REPORT.json

The report records source hashes, coverage, cleanup and qualification gaps; the sibling
log records assertions. A passed witness is evidence for those cases only.
