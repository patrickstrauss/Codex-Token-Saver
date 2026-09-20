# Headroom request compression for Codex desktop

Open **Codex Token Saver** from Start or the tray, or use the [dashboard](http://127.0.0.1:8095/). The **Headroom request savings** panel shows connection state, backend readiness, saved-token estimates, and observed activity.

## Enable or pause

1. Choose **Enable request compression**. The app validates its component files and asks the supervisor to warm the engine if needed, including after a paused Windows login. It waits up to 30 seconds before changing routing. Failed warmup restores the previous compression setting and preserves Codex configuration. An existing custom provider or endpoint is preserved rather than replaced.
2. Restart Codex when convenient to apply the connection to tasks already loaded. Resume existing tasks afterward; no task migration is needed. The app never restarts Codex automatically.
3. Choose **Pause request compression** to restore the owned endpoint setting. Restart Codex when convenient to reload it. The relay remains available for tasks that still have the previous connection loaded.

This mode implements the user's requested change from the earlier local-output-only setup. It changes `openai_base_url` for the built-in provider to `http://127.0.0.1:8788/v1`. Model, reasoning, authentication, provider identity, approval behavior, and saved task history are preserved. The change also applies to CLI sessions using the same Codex configuration. It does not set a Windows system proxy or change the ChatGPT login endpoint.

## What is compressed

Codex model requests reach a lightweight local relay on port 8788. Eligible Responses requests pass through the separate Headroom backend on 8789. It uses the coding/token profile, deduplication, code compression, and the local Kompress model. User and system text, model selection, and supplied reasoning settings are protected. Other supported endpoint traffic passes through normally.

This follows the [Headroom desktop integration](https://github.com/gglucass/headroom-desktop)'s request-level approach. It is broader than the bundle's file tools and command hook. Savings depend on eligible content, repeated context, retrieval, and workload; matching another installation's percentage is not guaranteed. Output shaping is disabled because it can change verbosity or reasoning effort.

The existing **RTK**, **Headroom desktop**, and **Headroom CLI proxy** cards retain their original measurement scopes. The new request counter uses the dedicated backend's records. These totals can overlap and must not be added together. They are estimates, not ChatGPT quota or verified billed savings.

**Requests recorded by Headroom** counts backend requests. **Completed connections** counts HTTP/WebSocket connections observed by the relay. A WebSocket can carry many requests and update Headroom savings while its connection is still active. Missing measurements show **Unavailable**; zero means a valid counter has recorded no reduction.

## Recovering exact originals

`headroom_retrieve` accepts two reference formats. A **12-character hexadecimal reference** comes from the request proxy, including `<<ccr:...>>` markers. The tool retrieves that original from the managed local Headroom engine. A **24-character hexadecimal reference** comes from a local file or command read and uses the local originals store. Uppercase references are normalized before lookup.

Proxy originals normally expire after **30 minutes** under the installed SDK's default retention policy; a transform can set a different lifetime. Local originals are retained for **24 hours**. An expired or unavailable reference produces a clear error rather than empty or approximate content. Re-read a source or safely rerun a command only when its original output is still needed. Retrieval preserves Unicode and original line endings, and line ranges are applied to the original text.

Exact tool responses carry a locally authenticated receipt. The request adapter verifies that receipt and preserves the full tool result through compression and deduplication, including results nested in `functions.exec` JSON envelopes. It does not promote tool text into instructions. Local retrieval remains charged against local content savings; proxy retrieval does not add another local savings event.

The bridge uses only `127.0.0.1:8789`, verifies Headroom's service identity and the returned hash, refuses redirects and environment proxies, and limits each response to 8 MiB. Oversized results fail explicitly without returning a partial original.

## Deploying retrieval fixes safely

Source edits do not hot-reload running processes. Restarting Codex loads the updated MCP tools, but the independent request-proxy supervisor and backend continue running until separately restarted. Pausing request compression also retains those workers and existing connections.

Validate changes and prepare the replacement before touching live workers. Allow active requests and WebSocket connections to finish before a controlled restart of the managed backend; stopping the supervisor can interrupt both backend and relay connections. Do not claim that a Codex restart alone activates an adapter fix. Revalidate the final source hashes before enabling a changed connection.

The routing validation receipt includes `exact_retrieval.py`. Library updates must pass the isolated `exact_retrieval_protected` runtime probe before activating a candidate, alongside the existing model and request-invariant checks.

For this installed fix, finish active tasks and restart Windows to reload both components together. The backend writes `exact-retrieval-runtime.json` in its managed Headroom state directory only when starting to serve with the guard installed. Its PID must match the current backend listener and its source hashes must match the installed files; a configuration probe alone does not prove that the running backend has loaded the fix.

## Recovery

The **Codex Token Saver Proxy** scheduled task starts a supervisor at Windows login. The relay starts independently of the heavier Headroom runtime. If compression is unavailable before a new request is sent, the relay can use the normal official upstream connection. Already-dispatched requests are never automatically replayed by the relay. A failed in-flight request may still need user intervention.

The supervisor restarts owned processes after crashes. It leaves unrelated listeners and existing streams alone. Startup order at Windows login is not guaranteed: Codex can open before the relay is ready. A full laptop reboot/login test remains outstanding.

If Codex cannot connect, run `Restore-Codex-Direct.ps1` from `%USERPROFILE%\CodexTokenSaver`, then restart Codex. Pause or restore routing before disabling the **Codex Token Saver Proxy** startup task. `codex-saver.exe` follows the current configuration and is not an emergency bypass.

The Start menu shortcut **Codex Token Saver - Restore Direct** runs the same recovery and displays its result. `Install-ProxyStartup.ps1` repairs this shortcut and the supervisor's login task; `-Plan` previews its settings without installing, and `-Start` also starts the registered task. These operations do not enable request routing.

Library updates validate candidate request-runtime settings and, when installed, offline Kompress and exact recovery before selection. The running backend loads an update on its next restart; see [Library updates](LIBRARY-UPDATES.md) before restarting a service with active tasks.

## Local records

- `proxy\settings.json`: enabled/paused state and upstream mode.
- `proxy\route-receipt.json` and `proxy\backups`: owned endpoint restoration and original config backup.
- `proxy\validation.json`: validated component hashes and time; activation refuses missing, changed, or invalid validation records. Matching tested files remain valid without a calendar expiry. Library candidates receive their separate runtime checks before selection.
- `proxy\service-status.json`: supervisor state.
- `proxy\backend-state`: dedicated request savings and recovery state, separate from CLI and local-output records.

The dashboard's status reads do not enable routing. Enable/pause requests require its local origin and page token. Upstream credentials and request bodies are not returned in the dashboard status. Original content needed for exact recovery stays in Headroom's local cache.
