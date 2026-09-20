# Headroom request compression for Codex desktop

The user authorized replacing the no-global-routing restriction with local proxy routing after validation. Preserve model, reasoning effort, account authentication and normal approvals.

Use the built-in OpenAI provider's `openai_base_url` override, avoiding custom provider identities or rewriting task history. A fast local relay on 127.0.0.1:8788 forwards HTTP/SSE and WebSocket traffic to the managed Headroom backend on 127.0.0.1:8789 when enabled and healthy. Otherwise it forwards to the original official OpenAI/ChatGPT destination. Never retry a request after dispatch or a WebSocket upgrade; only a failed backend connection before dispatch permits direct fallback.

The Headroom backend uses the coding compression profile, local Kompress ONNX assets, deduplication and request-history features. Output shaping and model/effort routing are disabled. Models are downloaded and verified before activation; cold startup must not block the relay.

A separate supervisor starts at login without the old ten-second delay, owns its child handles and restarts exited children with backoff. Pausing restores only our URL override and keeps the relay available in direct mode for already-running tasks that cached the endpoint. Existing backend connections drain naturally. Unrelated listeners and user changes remain untouched.

The dashboard exposes enable/pause, readiness, direct fallback status and separate request compression savings. Local-output and RTK history remain separately labeled. Updates preserve the integration and original recovery behavior.

Validation includes request/header/body integrity, HTTP/SSE and WebSocket forwarding, disconnect/no-replay behavior, unavailable backend, exact model/effort preservation, startup/process recovery, scoped config rollback, isolated compression/retrieval, real Codex CLI traffic through the same endpoint, and live UI. No forced laptop or Codex restart while tasks are active. A real desktop restart remains an explicit verification boundary until the user performs it.
