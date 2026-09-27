# OpenCodex compatibility candidate

The implementation and Windows candidate packages are ready for a closed-app upgrade.
They are **not installed or release-qualified**. The live connection, model, reasoning
and credentials have not been changed by development. Start with
[installation and restart steps](OPENCODEX-INTEGRATION.md).

The approved [design](superpowers/specs/2026-09-27-opencodex-compatibility-design.md)
keeps OpenCodex responsible for routing, credentials, catalog, voice and subagents.
Token Saver supplies local tools and a transform-only Headroom service.

Codex → OpenCodex history reconstruction → copy eligible tool text → local Headroom
transform → validated replacement or unchanged text → OpenCodex adapter → provider.
Originals are retained durably for exact retrieval; model and effort stay unchanged.

## Implemented

- Identity-checked resolve/readiness discovery, capability gating and route matching.
- Strict protocol-v1 local service, private bearer token, bounded requests, deadlines,
  overload bypass, circuit breaking, and durable 30-minute exact originals.
- Outbound-copy transformation after history hydration, including forward-auth adapters.
  No additional provider retries. Native steering, runTurn and structured inputs bypass.
- Conditional extension updates with ownership receipts, external-edit detection and
  recovery after a lost reply. Offline Pause cancels pending activation.
- Live persisted extension policy at readiness and each dispatch. Enable/Pause works
  on subsequent turns of an established WebSocket without restarting OpenCodex.
- Mode-aware worker startup, pending activation, dashboard and legacy controls.
  Owned native workers drain for 30 minutes; unknown listeners are preserved.
- Mode-aware launcher and full-bundle disable that preserve OpenCodex routing.
- Checked source upgrader for both apps, hashed backups, per-file atomic writes,
  automatic rollback on failed writes and explicit rollback before routing handoff.
- Explicit migration through the native bundle's Pause and OpenCodex's owned startup,
  with model/effort/approval/sandbox/auth preservation checks.

## Evidence and remaining limits

| Area | Result |
| --- | --- |
| Local service and adapters | Real HTTP transform/retrieval and Responses/Chat serialization witnesses pass |
| HTTP/WebSocket server | Delta turn, full replay after reconnect, simultaneous chats and live toggles pass against a loopback provider |
| Packaged OpenCodex | CLI binary built with the GUI; conditional configuration tests pass against the executable |
| Full bundle | Fresh full installation, repair, repeated installation and local runtime/quality smoke passed |
| Source upgrade and rollback | Unit regressions pass; package witness recorded separately in the release folder |
| Migration | Native owned-route restoration and protected-setting checks pass in isolated fixtures |
| Windows restart/login | Requires the user's closed-app installation and reboot acceptance |
| OpenAI/Azure/LM Studio | Real-provider comparison and billing effects are not qualified |
| Voice/catalog/images/compaction | Their existing routes are not transformed; live regression acceptance remains |
| Return to native routing | Automatic reverse migration is not qualified; source rollback refuses after handoff |

See [validation details](opencodex/VALIDATION.md), the [source patch](opencodex/README.md),
and the [offline witness](opencodex/offline-witness.json).
RTK, output compression and request estimates overlap and must not be summed.
