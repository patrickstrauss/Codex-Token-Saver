# Managed request service recovery

The September 20 audit found the supervisor absent, its saved status stale, and the request backend offline while the relay continued forwarding directly. The cause of the termination is still unknown; the recorded exit code does not establish who or what stopped it.

The existing tray checks the installed supervisor during its normal service refresh, at startup and every minute. A missing supervisor is launched hidden with a one-minute retry cooldown. The existing scheduled logon task remains the primary startup mechanism. No additional daemon or global route is installed. When the tray is closed, only the scheduled task's configured recovery applies; reopening the tray resumes its recovery checks.

A process creation fingerprint and a heartbeat no older than 30 seconds are required for a live status. A reused PID or old saved `available` flag is insufficient. An occupied supervisor lock with a stale heartbeat is reported, without terminating its owner. Healthy existing relay/backend listeners remain in use; the recovery path does not claim their PIDs or kill them.

Unexpected supervisor loop errors are retried with a delay and recorded as exception classes in `logs/proxy-supervisor.log`, with bounded rotation. Logs omit exception payloads, environment values and request content. Supervisor exit preserves workers so an interrupted supervisor does not itself close active streams. Explicit owned-worker shutdown remains available to isolated tests and managed maintenance. No request replay was introduced.

`GET /api/request-proxy` now includes `supervisor.live`, `supervisor.heartbeat_age_seconds` and `supervisor.last_error`. `enabled` describes the requested setting; `backend_ready` and `mode` describe current operation. Missing compression is reported explicitly even when source validation passed. Savings freshness uses the newer lifetime activity timestamp when retained history is older. Historical savings remain historical, and are not added to local-output or RTK totals.

The SDK's live stats omit `lifetime_metrics`; the controller therefore reads the same persisted ledger's `last_activity_at` for freshness even while the backend is online. This fallback changes only the activity timestamp. Live request and token counters remain authoritative, and an activity timestamp does not imply a positive saving on that request.

Validation includes isolated Windows subprocess recovery on random loopback ports, confirming that supervisor termination/restart preserves an existing relay, plus stale/reused PID handling, singleton and cooldown behavior, safe error logging, offline ledger freshness, routing preservation and the existing worker recovery tests. These tests do not establish the cause of the original termination or constitute a full Windows reboot test.
